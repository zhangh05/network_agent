# agent/runtime/context_builder.py
"""ContextBuilder — builds TurnContext from session + turn + services."""

import uuid
from agent.core.turn_context import TurnContext
from agent.context.snapshot import RuntimeSnapshot, build_runtime_snapshot
from agent.llm.config import resolve_provider_config


def build_turn_context(session, turn, services) -> TurnContext:
    """Build complete TurnContext for a turn execution.

    v0.8: when services.capability_registry is available, RuntimeSnapshot
    is built from the CapabilityRegistry (truth-source). Otherwise, falls
    back to the skill/module snapshots and tags the snapshot with a
    fallback warning.

    v0.8.1: per-turn SkillSelector + dynamic tool metadata.
    - SkillSelector.select() decides which skills to inject this turn
    - The LLM still receives the full model-visible tool catalog; tool
      descriptions carry risk/source/approval metadata so the model can
      choose deliberately.
    - ToolRegistry remains the safety filter: forbidden / planned / disabled
      or non-LLM-callable tools are never exposed.
    - On any error from the selector, fall back to v0.8 behavior
      (all enabled tools, no dynamic metadata) and record a warning
    """
    ctx = TurnContext(
        turn_id=turn.turn_id,
        session_id=session.session_id,
        workspace_id=session.workspace_id or "default",
        trace_id=str(uuid.uuid4()),
        user_input=turn.op.user_input if turn.op else "",
    )
    # v3.1.1: Carry sub-agent flag from session metadata to context
    if hasattr(session, 'metadata') and (session.metadata or {}).get('is_sub_agent'):
        ctx.metadata['is_sub_agent'] = True

    # 1. Load model config
    try:
        cfg = resolve_provider_config()
        ctx.model_config = cfg
    except Exception:
        ctx.model_config = {"enabled": False, "provider_type": "disabled"}

    # 2. Load history window
    if hasattr(session, 'history') and session.history:
        ctx.history_window = list(session.history[-8:])

    # 3. Build ToolRouter — v1.0.3.1 per-turn fresh instance.
    # The shared services.tool_service holds a ToolRouter whose registry
    # is safe to share. We build a fresh router per turn from the
    # immutable ToolRegistry. This eliminates cross-talk between
    # concurrent turns. The per-turn whitelist is baked in later in
    # step 6 (SkillSelector), creating exactly one ToolRouter per turn.
    #
    # Keep the service-level dispatch boundary attached to the per-turn
    # router. Tests, tracing wrappers, and future policy adapters patch
    # services.tool_service.dispatch; visibility remains per-turn because
    # build_tool_call() still runs on the fresh router.
    if services and services.tool_service:
        from agent.tools.router import ToolRouter
        router = services.tool_service
        if isinstance(router, ToolRouter):
            # Build a fresh router — no whitelist yet; that is applied in step 6
            ctx.tool_router = ToolRouter.for_turn(router.registry)
            ctx.tool_router.dispatch_delegate = router.dispatch
        else:
            ctx.tool_router = router

    # 4. Build SkillRegistry snapshot
    skill_snap = {}
    if services and services.skill_service:
        try:
            skill_snap = services.skill_service.snapshot()
        except Exception:
            skill_snap = {}
    ctx.skill_snapshot = skill_snap

    # 5. Build ModuleRegistry snapshot
    module_snap = {}
    if services and services.module_service:
        try:
            module_snap = services.module_service.snapshot()
        except Exception:
            module_snap = {}
    ctx.module_snapshot = module_snap

    # 6. v0.8.1 SkillSelector: per-turn skills + full LLM-visible tool catalog.
    cap_reg = getattr(services, "capability_registry", None) if services else None
    selector = getattr(services, "skill_selector", None) if services else None
    user_msg = ctx.user_input or ""

    selected_skills: list[str] = []
    selected_visible_tools: list[str] = []
    dynamic_visibility = False
    selector_warnings: list[str] = []
    tool_scene = {}
    rule_tool_scene = {}

    if selector is not None and cap_reg is not None:
        try:
            selected_skills = list(selector.select(user_msg, capability_registry=cap_reg))
            from agent.tools.router import ToolRouter
            from agent.llm.tool_adapter import from_llm_tool_name
            from agent.runtime.tool_category_router import route_tool_scene
            if ctx.tool_router is not None:
                base_reg = getattr(ctx.tool_router, "registry", None) or (
                    ctx.tool_router if hasattr(ctx.tool_router, "list_model_visible") else None
                )
                if base_reg is not None:
                    session_meta = getattr(session, "metadata", None) or {}
                    previous_scene = session_meta.get("last_tool_scene") if isinstance(session_meta, dict) else None
                    previous_rule_scene = session_meta.get("last_rule_tool_scene") if isinstance(session_meta, dict) else None
                    if _is_tool_followup(user_msg) and isinstance(previous_scene, dict):
                        rule_tool_scene = dict(previous_rule_scene or previous_scene)
                        rule_tool_scene["reason"] = (
                            str(rule_tool_scene.get("reason") or "")
                            + "；follow-up 继承上一轮工具场景"
                        ).strip("；")
                        rule_tool_scene["followup_inherited"] = True
                    else:
                        rule_tool_scene = route_tool_scene(
                            user_input=user_msg,
                            session_context={
                                **session_meta,
                                "workspace_id": ctx.workspace_id,
                                "selected_skills": selected_skills,
                            },
                        )
                    from agent.runtime.tool_planner import plan_tools
                    from tool_runtime.tool_namespace import TOOL_NAMESPACE
                    tool_scene = plan_tools(
                        user_input=user_msg,
                        safe_context={},
                        rule_scene=rule_tool_scene,
                        available_catalog={"tools": list(TOOL_NAMESPACE)},
                        model_config=ctx.model_config,
                    )
                    allowed_tools = list(tool_scene.get("candidate_tools") or [])
                    ctx.tool_router = ToolRouter.for_turn(base_reg, allowed_tool_ids=allowed_tools)
                    if services and services.tool_service and hasattr(services.tool_service, "dispatch"):
                        ctx.tool_router.dispatch_delegate = services.tool_service.dispatch
                    selected_visible_tools = sorted({
                        from_llm_tool_name(t["function"]["name"])
                        for t in ctx.tool_router.model_visible_tools()
                    })
                    ctx.visible_tool_ids = selected_visible_tools
                    dynamic_visibility = True
        except Exception as e:
            # v1.0.3.1: never crash. Fall back to v0.8 behavior.
            selector_warnings.append(f"skill_selector_error: {e!r}")
            dynamic_visibility = False

    # 7. Build RuntimeSnapshot
    visible_tools = []
    all_tools_count = 0
    if ctx.tool_router:
        try:
            visible_tools = ctx.tool_router.model_visible_tools()
        except Exception:
            pass
        try:
            if ctx.tool_router.registry:
                all_tools_count = len(ctx.tool_router.registry.list_all())
        except Exception:
            all_tools_count = len(visible_tools)

    # v0.8: prefer CapabilityRegistry when available.
    base_enabled = []
    if services and services.skill_service:
        try:
            base_enabled = [s.skill_id for s in services.skill_service.list_enabled_skills()
                            if s.skill_id == "assistant_chat"]
        except Exception:
            base_enabled = []
    snapshot = build_runtime_snapshot(
        tool_count=all_tools_count,
        visible_tool_count=len(visible_tools),
        workspace_id=ctx.workspace_id,
        session_id=ctx.session_id,
        model=ctx.model_config.get("model", ""),
        capability_registry=cap_reg,
        skill_snap=skill_snap,
        module_snap=module_snap,
        base_enabled_skills=base_enabled,
        selected_skills=selected_skills,
        selected_visible_tools=selected_visible_tools,
        dynamic_tool_visibility=dynamic_visibility,
    )
    if selector_warnings:
        snapshot.metadata = dict(snapshot.metadata or {})
        snapshot.metadata.setdefault("warnings", []).extend(selector_warnings)
    if tool_scene:
        snapshot.metadata = dict(snapshot.metadata or {})
        snapshot.metadata["tool_scene"] = tool_scene
        snapshot.metadata["rule_tool_scene"] = rule_tool_scene
    ctx.runtime_snapshot = snapshot.to_dict()

    # 8. Build safe_context — enrich with full context bundle
    #    v1.0.3.5: integrate context.builder.build_context_bundle() so
    #    RAG hits, memory, artifact refs, and workspace state enter the
    #    LLM context, not just {workspace_id, session_id}.
    from context.builder import build_context_bundle
    from context.schemas import ContextBudget
    try:
        # Derive intent from selected_skills (first non-base skill)
        derived_intent = ctx.metadata.get("intent", "")
        if not derived_intent and selected_skills:
            for s in selected_skills:
                if s not in ("assistant_chat", "capability_discovery"):
                    derived_intent = s
                    break
        derived_cap = ctx.metadata.get("capability_id", "") or derived_intent
        bundle = build_context_bundle(
            workspace_id=ctx.workspace_id,
            user_input=user_msg,
            intent=derived_intent,
            capability_id=derived_cap,
            budget=ContextBudget(),
            run_id=turn.turn_id if turn else "",
            trace_id=ctx.trace_id,
        )
        ctx.safe_context = _safe_context_from_bundle(bundle, ctx)
    except Exception as e:
        # Fallback to minimal context if full bundle build fails
        ctx.safe_context = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}
        ctx.metadata.setdefault("context_errors", []).append(str(e)[:200])

    if tool_scene:
        ctx.safe_context["tool_scene"] = tool_scene
        ctx.safe_context["tool_plan"] = tool_scene.get("tool_plan", [])
        ctx.safe_context["rule_tool_scene"] = rule_tool_scene

    # ── v2.1: Inject loaded skills into context ──
    # Read from session metadata first (skill.load writes there),
    # then fall back to ctx.metadata for sub-agent/inject cases.
    session_loaded = getattr(session, 'metadata', {}) or {}
    loaded_skills = (session_loaded.get("loaded_skills") or
                     ctx.metadata.get("loaded_skills") or {})
    if loaded_skills:
        skill_lines = ["## Loaded Skills", ""]
        for skill_name, skill_info in loaded_skills.items():
            prompt = skill_info.get("skill_prompt", "")[:3000] if isinstance(skill_info, dict) else ""
            if prompt:
                skill_lines.append(f"### {skill_name}")
                skill_lines.append(prompt)
                skill_lines.append("")
        if len(skill_lines) > 2:
            ctx.safe_context["loaded_skills_section"] = "\n".join(skill_lines)

    # v1.0.3: store selected_skills and visible_tools in ctx.metadata
    # so loop.py can include them in AgentResult.metadata.
    ctx.metadata["selected_skills"] = selected_skills
    ctx.metadata["visible_tools"] = selected_visible_tools
    ctx.visible_tool_ids = selected_visible_tools
    if tool_scene:
        ctx.metadata["tool_scene"] = tool_scene
        ctx.metadata["rule_tool_scene"] = rule_tool_scene
        ctx.metadata["tool_planner"] = tool_scene.get("tool_planner", {})
        if hasattr(session, "metadata"):
            if session.metadata is None:
                session.metadata = {}
            session.metadata["last_tool_scene"] = tool_scene
            session.metadata["last_rule_tool_scene"] = rule_tool_scene

    return ctx


def _is_tool_followup(user_msg: str) -> bool:
    text = (user_msg or "").strip().lower()
    if not text:
        return False
    markers = (
        "不对", "错了", "搞错", "调用有问题", "没调用", "没有调用",
        "继续", "再来", "重新", "重试", "有shell", "有 shell",
        "你肯定", "能显示", "刚才", "上一轮", "上一步",
        "wrong", "retry", "again", "continue", "use the tool",
        # v2.3.3: additional follow-up indicators
        "用错了", "调错了", "不是这个工具", "换一个工具",
        "再试", "再调", "调用失败", "重来",
        "这个不行", "不行", "没有用", "没效果",
    )
    return any(marker in text for marker in markers)


def _safe_context_from_bundle(bundle, ctx) -> dict:
    """Extract the LLM-safe key-value context from a ContextBundle.

    Returns a flat dict suitable for safe_context injection.
    Falls back to minimal data if the bundle is empty."""
    safe = {
        "workspace_id": ctx.workspace_id,
        "session_id": ctx.session_id,
    }
    if not bundle:
        return safe
    # Inject context bundle data
    if hasattr(bundle, "safe_context") and bundle.safe_context:
        sc = bundle.safe_context
        safe["intent"] = getattr(sc, "intent", "") or ""
        if hasattr(sc, "artifact_refs") and sc.artifact_refs:
            safe["artifact_refs"] = list(sc.artifact_refs)
        if hasattr(sc, "memory_hits") and sc.memory_hits:
            # v2.3.2: Extend injection scan to memory_hits
            from agent.runtime.rag_injection_scan import scan_chunks
            mem_scan = scan_chunks(list(sc.memory_hits), source="memory")
            safe["memory_hits"] = mem_scan["safe_chunks"] + mem_scan["summary_chunks"]
            if mem_scan["blocked_chunks"]:
                blocked_ids = [b.get("chunk_id", "") for b in mem_scan["blocked_chunks"]]
                ctx.metadata["memory_blocked_count"] = len(mem_scan["blocked_chunks"])
                ctx.metadata["memory_blocked_ids"] = blocked_ids
                ctx.metadata.setdefault("injection_warnings", []).extend(mem_scan["warnings"])
        if hasattr(sc, "knowledge_hits") and sc.knowledge_hits:
            # v2.3.1: RAG injection scan before entering SafeContext
            # v3.0.0: knowledge content is user-curated, use reduced scan sensitivity
            from agent.runtime.rag_injection_scan import scan_chunks
            scan_result = scan_chunks(list(sc.knowledge_hits), source="knowledge",
                                      source_type="knowledge")
            safe["knowledge_hits"] = scan_result["safe_chunks"] + scan_result["summary_chunks"]
            # Record blocked chunks for audit trace and user feedback
            blocked_count = len(scan_result["blocked_chunks"])
            summary_count = len(scan_result["summary_chunks"])
            if blocked_count > 0:
                blocked_ids = [b.get("chunk_id", "") for b in scan_result["blocked_chunks"]]
                ctx.metadata["rag_blocked_count"] = blocked_count
                ctx.metadata["rag_blocked_ids"] = blocked_ids
                ctx.metadata["rag_blocked_reasons"] = [
                    {"chunk_id": b.get("chunk_id"), "patterns": b.get("patterns", [])}
                    for b in scan_result["blocked_chunks"]
                ]
                ctx.metadata.setdefault("injection_warnings", []).extend(scan_result["warnings"])
            if summary_count > 0:
                ctx.metadata["rag_summarized_count"] = summary_count
            if scan_result["warnings"]:
                ctx.metadata.setdefault("context_warnings", []).extend(scan_result["warnings"])
        if hasattr(sc, "citations") and sc.citations:
            safe["citations"] = list(sc.citations)
        if hasattr(sc, "context_sources") and sc.context_sources:
            safe["context_sources"] = list(sc.context_sources)
        if hasattr(sc, "retrieval_diagnostics") and sc.retrieval_diagnostics:
            safe["retrieval_diagnostics"] = dict(sc.retrieval_diagnostics)
        if hasattr(sc, "warnings") and sc.warnings:
            safe["context_warnings"] = list(sc.warnings)
    if hasattr(bundle, "workspace_state") and bundle.workspace_state:
        safe["workspace_state"] = dict(bundle.workspace_state)
    ec = getattr(bundle, "execution_context", None) or getattr(bundle, "exec_context", None)
    if ec:
        safe["capability_id"] = getattr(ec, "capability_id", "") or ""
        safe["source_config_artifact_id"] = getattr(ec, "source_config_artifact_id", "") or ""

    # v3.0.0: Auto-compact if context exceeds model budget
    safe = _auto_compact_context(safe, ctx, bundle)
    return safe


# ── v3.0.0: Auto-compact ──

def _estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for CJK+EN mixed text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _estimate_context_tokens(safe_context: dict) -> int:
    """Estimate total tokens for a safe_context dict."""
    import json
    try:
        text = json.dumps(safe_context, ensure_ascii=False)
        return _estimate_tokens(text)
    except Exception:
        return len(str(safe_context)) // 4


def _estimate_history_tokens(history_window: list) -> int:
    """Estimate tokens for history window."""
    import json
    try:
        total = 0
        for h in history_window:
            if hasattr(h, 'content'):
                total += _estimate_tokens(str(h.content))
            elif isinstance(h, dict):
                total += _estimate_tokens(json.dumps(h, ensure_ascii=False))
        return total
    except Exception:
        return len(str(history_window)) // 4


def _auto_compact_context(safe_context: dict, ctx, bundle) -> dict:
    """v3.0.0: Auto-compact safe_context when it exceeds the model budget.

    Applies layered compression in priority order:
      1. trim_history     — drop oldest 2 turns from history window
      2. drop_low_score   — discard knowledge chunks with score < threshold
      3. summarize_memory — replace memory_hits with condensed summaries
      4. drop_extras      — remove workspace_state, citations, diagnostics

    Only compacts when estimated tokens exceed 85% of the model's budget.
    """
    try:
        model = ctx.model_config.get("model", "") if ctx.model_config else ""
        from context.schemas import resolve_budget_for_model
        budget = resolve_budget_for_model(model)
        budget_tokens = budget.max_chars // 4 if budget.max_chars else 3000
    except Exception:
        budget_tokens = 3000  # conservative default

    estimated = _estimate_context_tokens(safe_context)
    threshold = int(budget_tokens * 0.85)

    if estimated <= threshold:
        return safe_context  # within budget, no compaction needed

    compacted = dict(safe_context)
    ctx.metadata["auto_compact"] = True
    ctx.metadata["compact_pre_tokens"] = estimated

    # Layer 1: trim history (drop oldest 2 turns)
    if hasattr(bundle, "compressed_items") and bundle.compressed_items:
        history_count = len([i for i in bundle.compressed_items if getattr(i, "item_type", "") == "history_turn"])
        if history_count > 4:
            ctx.metadata["compact_layer"] = "trim_history"
            ctx.metadata["compact_history_before"] = len(ctx.history_window)
            ctx.history_window = ctx.history_window[2:] if len(ctx.history_window) >= 4 else [ctx.history_window[-1]] if ctx.history_window else []
            ctx.metadata["compact_history_after"] = len(ctx.history_window)
            if _estimate_context_tokens(compacted) + _estimate_history_tokens(ctx.history_window) <= threshold:
                ctx.metadata["compact_post_tokens"] = _estimate_context_tokens(compacted) + _estimate_history_tokens(ctx.history_window)
                return compacted

    # Layer 2: drop low-score knowledge chunks
    knowledge_hits = compacted.get("knowledge_hits", [])
    if isinstance(knowledge_hits, list) and len(knowledge_hits) > 1:
        # Keep only chunks with score above median or keep top 3
        scored = []
        for k in knowledge_hits:
            score = k.get("score", 0) if isinstance(k, dict) else 0
            scored.append((score, k))
        scored.sort(key=lambda x: x[0], reverse=True)
        keep_count = max(1, min(3, len(scored)))
        compacted["knowledge_hits"] = [k for _, k in scored[:keep_count]]
        ctx.metadata["compact_layer"] = "drop_low_score"
        ctx.metadata["compact_knowledge_before"] = len(knowledge_hits)
        ctx.metadata["compact_knowledge_after"] = keep_count
        if _estimate_context_tokens(compacted) <= threshold:
            ctx.metadata["compact_post_tokens"] = _estimate_context_tokens(compacted)
            return compacted

    # Layer 3: summarize memory hits
    memory_hits = compacted.get("memory_hits", [])
    if isinstance(memory_hits, list) and len(memory_hits) > 1:
        summaries = []
        for m in memory_hits:
            if isinstance(m, dict):
                title = m.get("title", "") or m.get("summary", "") or ""
                summaries.append(title[:80])
        if summaries:
            compacted["memory_hits"] = [{"summary": " | ".join(summaries)[:500]}]
            ctx.metadata["compact_layer"] = "summarize_memory"
            ctx.metadata["compact_memory_before"] = len(memory_hits)
            if _estimate_context_tokens(compacted) <= threshold:
                ctx.metadata["compact_post_tokens"] = _estimate_context_tokens(compacted)
                return compacted

    # Layer 4: drop extras (workspace_state, citations, diagnostics)
    for k in ("workspace_state", "citations", "retrieval_diagnostics", "context_sources"):
        compacted.pop(k, None)
    ctx.metadata["compact_layer"] = "drop_extras"

    ctx.metadata["compact_post_tokens"] = _estimate_context_tokens(compacted)
    return compacted
