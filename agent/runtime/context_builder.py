# agent/runtime/context_builder.py
"""ContextBuilder — builds TurnContext from session + turn + services.

The builder is intentionally an orchestration pipeline. Heavy responsibilities
are delegated to focused helpers:
- context_history.py     — in-memory/disk history window handling
- context_tools.py       — tool scene routing and per-turn visibility
- cognition/scene_decision.py   — unified scene decision
- cognition/evidence_pipeline.py — evidence extraction + injection scan
- tool_planning/planner.py      — ToolPlannerV2 planning
"""

from __future__ import annotations

import uuid

from agent.core.turn_context import TurnContext
from agent.context.snapshot import build_runtime_snapshot
from agent.llm.config import resolve_provider_config
from agent.runtime.context_history import initial_history_window
from agent.runtime.context_tools import (
    build_base_tool_router,
    persist_tool_scene_to_session,
)
from agent.runtime.state.hooks import prepare_runtime_state_for_turn, runtime_state_prompt_block


def build_turn_context(session, turn, services) -> TurnContext:
    """Build complete TurnContext for a turn execution.

    Delegates to ContextPipeline (13-stage pipeline).
    """
    from agent.runtime.context_pipeline.pipeline import ContextPipeline
    pipeline = ContextPipeline()
    return pipeline.run(session, turn, services)


# ─── Helper functions ─────────────────────────────────────────────────


def _resolve_model_config() -> dict:
    try:
        return resolve_provider_config()
    except Exception:
        return {"enabled": False, "provider_type": "disabled"}


def _snapshot_service(service, label: str) -> dict:
    if not service:
        return {}
    try:
        return service.snapshot()
    except Exception:
        return {}


def _select_skills(selector, cap_reg, user_msg: str, ctx=None) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    if selector is None or cap_reg is None:
        if ctx is not None:
            ctx.metadata["selector_status"] = "unavailable"
        return [], warnings
    try:
        selected = list(selector.select(user_msg or "", capability_registry=cap_reg))
        if ctx is not None:
            ctx.metadata["selector_status"] = "ok"
        return selected, warnings
    except Exception as exc:
        msg = f"skill_selector_error: {exc!r}"
        warnings.append(msg)
        if ctx is not None:
            ctx.metadata["selector_status"] = "failed"
            ctx.metadata.setdefault("selector_errors", []).append(str(exc)[:200])
        return [], warnings


def _compute_scene_decision(ctx, session):
    """Compute SceneDecision for the current turn."""
    try:
        from agent.runtime.cognition.scene_decision import decide_scene

        session_meta = getattr(session, "metadata", None) or {}
        previous_scene = session_meta.get("last_tool_scene") if isinstance(session_meta, dict) else None
        previous_rule_scene = session_meta.get("last_rule_tool_scene") if isinstance(session_meta, dict) else None

        decision = decide_scene(
            ctx.user_input or "",
            session_context=session_meta if isinstance(session_meta, dict) else {},
            previous_scene=previous_scene,
            previous_rule_scene=previous_rule_scene,
            intent=ctx.metadata.get("intent", ""),
        )
        ctx.metadata["scene_decision_status"] = "ok"
        return decision
    except Exception as e:
        ctx.metadata["scene_decision_status"] = "failed"
        ctx.metadata.setdefault("context_errors", []).append(f"scene_decision: {e!s}"[:200])
        return None


def _prepare_runtime_state(ctx, session) -> None:
    try:
        prepare_runtime_state_for_turn(ctx, session=session)
        ctx.metadata["runtime_state_status"] = "ok"
    except Exception as exc:
        ctx.metadata["runtime_state_status"] = "failed"
        ctx.metadata.setdefault("context_errors", []).append(f"runtime_state: {exc!s}"[:200])


def _build_evidence(ctx, turn, selected_skills: list[str], services=None):
    """Run EvidencePipeline to produce EvidenceBundle."""
    from agent.runtime.cognition.evidence_pipeline import EvidencePipeline

    pipeline = EvidencePipeline()
    try:
        return pipeline.build(ctx, services=services)
    except Exception as e:
        ctx.metadata["safe_context_status"] = "failed"
        ctx.metadata.setdefault("context_errors", []).append(str(e)[:200])
        from agent.runtime.cognition.evidence_models import EvidenceBundle
        return EvidenceBundle()


# ── P1-B: RetrievalTriggerPolicy integration ──────────────────────────

def _evaluate_retrieval_policy(ctx, session) -> None:
    """Run RetrievalTriggerPolicy before evidence building.

    Produces a RetrievalDecision stored in ctx.metadata["retrieval_decision"].
    This guides the EvidencePipeline to decide what to retrieve.
    """
    try:
        from agent.runtime.retrieval.trigger_policy import RetrievalTriggerPolicy

        session_meta = getattr(session, "metadata", None) or {}
        scene_decision = getattr(ctx, "scene_decision", None)
        is_simple = getattr(scene_decision, "is_simple_chat", False) if scene_decision else False
        is_factual = getattr(scene_decision, "is_factual_query", False) if scene_decision else False

        # Check if session has meaningful history (more than just a greeting)
        history = getattr(ctx, "history_window", None) or []
        session_has_history = len(history) > 1

        # Check for file/artifact refs in context
        safe_ctx = ctx.safe_context if hasattr(ctx, "safe_context") else {}
        file_ids = list(safe_ctx.get("file_ids", []) or [])
        artifact_ids = list(safe_ctx.get("artifact_ids", []) or [])
        artifact_refs = ctx.metadata.get("artifact_refs", []) or []
        has_file_refs = bool(file_ids or artifact_ids or artifact_refs)

        # Check for tool retry state
        is_tool_retry = bool(ctx.metadata.get("required_tool_retry_used"))

        # ── Determine index availability ──
        has_memory_index = True  # UnifiedRetriever always has the index
        has_knowledge_index = True  # Same

        policy = RetrievalTriggerPolicy()
        decision = policy.evaluate(
            user_input=ctx.user_input or "",
            session_meta=session_meta,
            ctx_meta=ctx.metadata,
            has_memory_index=has_memory_index,
            has_knowledge_index=has_knowledge_index,
            is_simple_chat=is_simple,
            is_factual_query=is_factual,
            session_has_history=session_has_history,
            has_file_refs=has_file_refs,
            file_ids=file_ids,
            artifact_ids=artifact_ids,
            is_tool_retry=is_tool_retry,
        )

        ctx.metadata["retrieval_decision"] = decision.to_dict()

        # Augment scene_decision with policy signals
        if scene_decision and hasattr(scene_decision, "needs_memory"):
            # Don't downgrade: if scene already said required, keep it
            if decision.memory_required and not scene_decision.needs_memory:
                scene_decision.needs_memory = True
                scene_decision.is_memory_task = True
        if scene_decision and hasattr(scene_decision, "needs_knowledge"):
            if decision.knowledge_required and not scene_decision.needs_knowledge:
                scene_decision.needs_knowledge = True
                scene_decision.is_knowledge_task = True

    except Exception:
        ctx.metadata.setdefault("context_warnings", []).append(
            "retrieval_policy_evaluation_failed"
        )


def _enrich_retrieval_decision_from_evidence(ctx, evidence_bundle) -> None:
    """Enrich the RetrievalDecision with actual retrieval results.

    Called after EvidencePipeline has executed.
    Updates ctx.metadata["retrieval_decision"] with hit/miss/error status.
    """
    try:
        rd = ctx.metadata.get("retrieval_decision")
        if not rd or not isinstance(rd, dict):
            return

        from agent.runtime.retrieval.unknown_feedback import (
            UnknownFeedback,
            enrich_retrieval_decision,
        )
        from agent.runtime.retrieval.trigger_policy import RetrievalDecision

        # Reconstruct the decision object
        mem_pre = rd.get("_pre_decisions", {})
        decision = RetrievalDecision(
            memory_status=mem_pre.get("memory_status", "not_applicable"),
            memory_required=mem_pre.get("memory_required", False),
            memory_reason=mem_pre.get("memory_reason", ""),
            knowledge_status=mem_pre.get("knowledge_status", "not_applicable"),
            knowledge_required=mem_pre.get("knowledge_required", False),
            knowledge_reason=mem_pre.get("knowledge_reason", ""),
            file_evidence_status=mem_pre.get("file_evidence_status", "not_applicable"),
            file_evidence_required=mem_pre.get("file_evidence_required", False),
            file_evidence_reason=mem_pre.get("file_evidence_reason", ""),
            queries=list(mem_pre.get("queries", [])),
        )

        # Extract actual results from EvidenceBundle
        memory_results = []
        knowledge_results = []
        if evidence_bundle is not None:
            memory_results = (
                getattr(evidence_bundle, "memory_items", None)
                or getattr(evidence_bundle, "memory_layer", None)
            )
            if hasattr(memory_results, "items"):
                memory_results = memory_results.items
            elif not isinstance(memory_results, list):
                memory_results = []

            knowledge_results = (
                getattr(evidence_bundle, "knowledge_items", None)
                or getattr(evidence_bundle, "knowledge_layer", None)
            )
            if hasattr(knowledge_results, "items"):
                knowledge_results = knowledge_results.items
            elif not isinstance(knowledge_results, list):
                knowledge_results = []

        # Build feedback for misses
        mem_feedback = None
        if not memory_results and decision.memory_status not in ("skipped", "not_applicable"):
            mem_feedback = UnknownFeedback.for_no_match("memory")

        k_feedback = None
        if not knowledge_results and decision.knowledge_status not in ("skipped", "not_applicable"):
            k_feedback = UnknownFeedback.for_no_match("knowledge")

        # Enrich
        decision = enrich_retrieval_decision(
            decision,
            memory_results=list(memory_results),
            knowledge_results=list(knowledge_results),
            memory_feedback=mem_feedback,
            knowledge_feedback=k_feedback,
        )

        # Write back — preserve _pre_decisions for audit
        enriched = decision.to_dict()
        enriched["_pre_decisions"] = rd.get("_pre_decisions", {})
        ctx.metadata["retrieval_decision"] = enriched

    except Exception:
        ctx.metadata.setdefault("context_warnings", []).append(
            "retrieval_decision_enrichment_failed"
        )


def _safe_context_from_evidence(ctx, evidence_bundle) -> dict:
    """Convert EvidenceBundle to safe_context dict."""
    safe = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}
    if evidence_bundle is not None and hasattr(evidence_bundle, "to_safe_context"):
        safe.update(evidence_bundle.to_safe_context())
    return safe


def _inject_runtime_state_snapshot(ctx) -> None:
    block = runtime_state_prompt_block(ctx)
    if not block:
        return
    ctx.safe_context["runtime_state_snapshot"] = ctx.metadata.get("runtime_state_snapshot", {})
    ctx.safe_context["runtime_state_summary"] = ctx.metadata.get("runtime_state_snapshot_summary", "")
    ctx.safe_context["runtime_state_section"] = block


def _plan_tools_v2(ctx, evidence_bundle, session, services, selected_skills: list[str]) -> dict:
    """Use ToolPlannerV2 to plan tools from SceneDecision + EvidenceBundle."""
    result = {
        "selected_visible_tools": [],
        "dynamic_visibility": False,
        "tool_scene": {},
        "rule_tool_scene": {},
        "warnings": [],
    }
    cap_reg = getattr(services, "capability_catalog", None) if services else None
    if cap_reg is None or ctx.tool_router is None:
        return result

    scene_decision = getattr(ctx, "scene_decision", None)
    if scene_decision is None:
        return result

    try:
        from agent.tools.router import ToolRouter
        from agent.llm.tool_adapter import from_llm_tool_name
        from agent.runtime.tool_planning.planner import ToolPlannerV2
        from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene

        base_reg = getattr(ctx.tool_router, "registry", None) or (
            ctx.tool_router if hasattr(ctx.tool_router, "list_model_visible") else None
        )
        if base_reg is None:
            return result

        planner = ToolPlannerV2()
        # v3.9.4: business capabilities are guidance only. All canonical
        # tools are known to the planner; scene signals choose the visible set.
        available_catalog = {
            "tools": list(TOOL_NAMESPACE),
            "business_capabilities": list(cap_reg or []),
        }
        tool_scene = planner.plan(
            scene_decision,
            evidence_bundle=evidence_bundle,
            available_catalog=available_catalog,
            model_config=ctx.model_config,
        )
        rule_tool_scene = scene_to_rule_scene(scene_decision)

        allowed_tools = list(tool_scene.get("candidate_tools") or [])
        ctx.tool_router = ToolRouter.for_turn(base_reg, allowed_tool_ids=allowed_tools)
        if services and getattr(services, "tool_service", None) and hasattr(services.tool_service, "dispatch"):
            ctx.tool_router.dispatch_delegate = services.tool_service.dispatch

        visible_tools = sorted({
            from_llm_tool_name(t["function"]["name"])
            for t in ctx.tool_router.model_visible_tools()
        })
        ctx.visible_tool_ids = visible_tools
        result.update({
            "selected_visible_tools": visible_tools,
            "dynamic_visibility": True,
            "tool_scene": tool_scene,
            "rule_tool_scene": rule_tool_scene,
        })
    except Exception as e:
        result["warnings"].append(f"skill_selector_error: {e!r}")
    return result


def _tool_counts(ctx) -> tuple[list, int]:
    visible_tools = []
    all_tools_count = 0
    if ctx.tool_router:
        try:
            visible_tools = ctx.tool_router.model_visible_tools()
        except Exception:
            visible_tools = []
        try:
            if ctx.tool_router.registry:
                all_tools_count = len(ctx.tool_router.registry.list_all())
        except Exception:
            all_tools_count = len(visible_tools)
    return visible_tools, all_tools_count


def _base_enabled_skills(services) -> list[str]:
    """Return 'assistant_chat' — always available as base conversational capability."""
    return ["assistant_chat"]


def _inject_loaded_skills(ctx, session) -> None:
    """Inject loaded capability contracts into safe_context.
    
    v3.3: Renamed from 'loaded skills' to 'loaded capabilities'.
    Uses the session's loaded_capabilities metadata to expose tool/contract info.
    """
    session_loaded = getattr(session, "metadata", {}) or {}
    loaded = (session_loaded.get("loaded_capabilities") or 
              session_loaded.get("loaded_skills") or 
              ctx.metadata.get("loaded_capabilities") or 
              ctx.metadata.get("loaded_skills") or {})
    if not loaded:
        return

    contracts = []
    for cap_id, cap_info in loaded.items():
        if not isinstance(cap_info, dict):
            continue
        contracts.append({
            "capability_id": cap_id,
            "capability_ids": list(cap_info.get("capability_ids") or []),
            "module_ids": list(cap_info.get("module_ids") or []),
            "tool_ids": list(cap_info.get("tool_ids") or []),
            "prompt_hints": list(cap_info.get("prompt_hints") or []),
            "safety_notes": list(cap_info.get("safety_notes") or []),
        })
    if contracts:
        ctx.safe_context["loaded_capabilities"] = contracts


def _write_context_metadata(
    *,
    ctx,
    session,
    selected_skills: list[str],
    selected_visible_tools: list[str],
    tool_scene: dict,
    rule_tool_scene: dict,
) -> None:
    ctx.metadata["selected_skills"] = selected_skills
    ctx.metadata["visible_tools"] = selected_visible_tools
    ctx.visible_tool_ids = selected_visible_tools
    if tool_scene:
        ctx.metadata["tool_scene"] = tool_scene
        ctx.metadata["rule_tool_scene"] = rule_tool_scene
        ctx.metadata["tool_planner"] = tool_scene.get("tool_planner", {})
        if tool_scene.get("visibility"):
            ctx.metadata["tool_visibility"] = tool_scene.get("visibility")
        # ── P0: Persist ToolPlanningDecision for audit/inspection ──
        if tool_scene.get("tool_planning_decision"):
            ctx.metadata["tool_planning_decision"] = tool_scene["tool_planning_decision"]
        persist_tool_scene_to_session(session, tool_scene, rule_tool_scene)
