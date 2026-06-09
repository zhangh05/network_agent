# agent/nodes/context_loader.py
"""Context loader — loads workspace state, memory hits, registry info."""

import json
import logging
import os

from agent.state import NetworkAgentState

logger = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_context(state: NetworkAgentState) -> NetworkAgentState:
    """Load context: workspace state, memory hits, module/skill registries."""

    ws_id = state.workspace_id or "default"

    # ═══ 1. Workspace state ═══
    try:
        from workspace.manager import get_workspace_state
        ws = get_workspace_state(ws_id)
        state.context["workspace_state"] = ws

        # Handle context_ref=last_result
        if state.context.get("context_ref") == "last_result":
            summary = ws.get("last_result_summary", "")
            counts = ws.get("last_result_counts", {})
            samples_mr = ws.get("last_manual_review_samples", [])
            samples_us = ws.get("last_unsupported_samples", [])
            state.context["last_result"] = {
                "has_result": bool(ws.get("last_intent")),
                "last_intent": ws.get("last_intent"),
                "summary": summary,
                "counts": counts,
                "manual_review_samples": samples_mr[:5],
                "unsupported_samples": samples_us[:5],
                "llm_metadata": ws.get("llm_metadata", {}),
            }
    except Exception:
        logger.debug("context_loader: workspace state load failed", exc_info=True)
        state.context["last_result"] = {"has_result": False}

    # ═══ 2. Memory hits via retriever ═══
    try:
        from memory.retriever import retrieve_for_context
        hits = retrieve_for_context(
            query=state.user_input or "",
            project_id=ws_id,
            limit=5,
        )
        state.context["memory_hits"] = hits
    except Exception:
        logger.debug("context_loader: memory retriever failed", exc_info=True)
        state.context["memory_hits"] = []

    # ═══ 3. Module registry ═══
    try:
        with open(os.path.join(ROOT, "modules", "registry.json"), encoding="utf-8") as f:
            modules = json.load(f)
        state.context["modules"] = {
            m["module_name"]: m["status"] for m in modules.get("modules", [])
        }
    except Exception:
        logger.debug("context_loader: module registry load failed", exc_info=True)

    # ═══ 4. Skill registry ═══
    try:
        with open(os.path.join(ROOT, "skills", "registry.json"), encoding="utf-8") as f:
            skills = json.load(f)
        state.context["skills"] = {
            s["skill_name"]: s.get("enabled", False) for s in skills.get("skills", [])
        }
    except Exception:
        logger.debug("context_loader: skill registry load failed", exc_info=True)

    # ── 5. Build ContextBundle ──
    try:
        from context.builder import build_context_bundle
        ctx_ref = state.context.get("context_ref", "")
        bundle = build_context_bundle(
            workspace_id=state.workspace_id or "default",
            user_input=state.user_input or "",
            intent=state.intent or "",
            capability_id=state.context.get("capability_id", ""),
            payload=state.payload,
            context_ref=ctx_ref,
            state_context=state.context,
            run_id=state.request_id,
            trace_id=state.trace_id or "",
        )
        state.context["context_bundle"] = bundle.as_dict()
        state.context["safe_llm_context"] = bundle.safe_llm_context.as_dict() if bundle.safe_llm_context else {}
        state.context["execution_context"] = bundle.execution_context.as_dict() if bundle.execution_context else {}
        state.context["citations"] = bundle.citations
    except Exception:
        logger.warning("context_loader: context_bundle build failed", exc_info=True)

    # ── Trace: context_loaded ──
    state.trace_events.append({
        "event_id": "context_loaded",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": "context_loaded",
        "name": "context_loaded",
        "status": "success",
        "duration_ms": 0.0,
        "summary": f"memory_hits={len(state.context.get('memory_hits', []))} last_result={state.context.get('last_result', {}).get('has_result', False)}",
        "metadata": {},
        "redaction_applied": False,
    })

    return state
