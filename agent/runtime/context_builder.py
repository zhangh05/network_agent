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
    back to the legacy skill/module snapshots and tags the snapshot with
    a fallback warning.

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

    if selector is not None and cap_reg is not None:
        try:
            selected_skills = list(selector.select(user_msg, capability_registry=cap_reg))
            from agent.tools.router import ToolRouter
            if ctx.tool_router is not None:
                base_reg = getattr(ctx.tool_router, "registry", None) or (
                    ctx.tool_router if hasattr(ctx.tool_router, "list_model_visible") else None
                )
                if base_reg is not None:
                    ctx.tool_router = ToolRouter.for_turn(base_reg)
                    if services and services.tool_service and hasattr(services.tool_service, "dispatch"):
                        ctx.tool_router.dispatch_delegate = services.tool_service.dispatch
                    selected_visible_tools = sorted({
                        t["function"]["name"].replace("__", ".", 1)
                        for t in ctx.tool_router.model_visible_tools()
                    })
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
    ctx.runtime_snapshot = snapshot.to_dict()

    # 8. Build safe_context — enrich with full context bundle
    #    v1.0.3.5: integrate context.builder.build_context_bundle() so
    #    RAG hits, memory, artifact refs, and workspace state enter the
    #    LLM context, not just {workspace_id, session_id}.
    from context.builder import build_context_bundle
    from context.schemas import ContextBudget
    try:
        bundle = build_context_bundle(
            workspace_id=ctx.workspace_id,
            user_input=user_msg,
            intent=ctx.metadata.get("intent", ""),
            capability_id=ctx.metadata.get("capability_id", ""),
            budget=ContextBudget(),
            run_id=turn.turn_id if turn else "",
            trace_id=ctx.trace_id,
        )
        ctx.safe_context = _safe_context_from_bundle(bundle, ctx)
        
        # ── v2.1: Inject loaded skills into context ──
        loaded_skills = ctx.metadata.get("loaded_skills") or {}
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
    except Exception as e:
        # Fallback to minimal context if full bundle build fails
        ctx.safe_context = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}
        ctx.metadata.setdefault("context_errors", []).append(str(e)[:200])

    # v1.0.3: store selected_skills and visible_tools in ctx.metadata
    # so loop.py can include them in AgentResult.metadata.
    ctx.metadata["selected_skills"] = selected_skills
    ctx.metadata["visible_tools"] = selected_visible_tools

    return ctx


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
            safe["memory_hits"] = list(sc.memory_hits)
        if hasattr(sc, "knowledge_hits") and sc.knowledge_hits:
            safe["knowledge_hits"] = list(sc.knowledge_hits)
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
    return safe
