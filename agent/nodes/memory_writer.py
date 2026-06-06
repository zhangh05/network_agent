"""Memory writer node — memory + workspace state + run record with redaction/policy."""

import json, os, time
from agent.state import NetworkAgentState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write_memory(state: NetworkAgentState) -> NetworkAgentState:
    """Write memory, workspace state, and run record with policy enforcement.

    Uses memory.writer (redaction + policy), workspace.manager (policy-gated state),
    and workspace.run_store (sanitized run records).
    """
    if state.error:
        return state

    result = state.tool_results or {}
    ws_id = state.workspace_id or "default"

    memory_written = False
    workspace_updated = False

    # ═══ 1. Memory run_summary via memory.writer (with redaction + policy) ═══
    try:
        from memory.writer import write_run_summary

        counts = ""
        if state.intent == "translate_config":
            dc = result.get("deployable_config", "")
            mr = result.get("manual_review", [])
            us = result.get("unsupported", [])
            dlines = len(dc.split("\n")) if dc else 0
            counts = f" | d:{dlines} mr:{len(mr)} us:{len(us)}"

        llm_ctx = state.context.get("llm", {})
        mid = write_run_summary(
            intent=state.intent or "unknown",
            skill=state.selected_skill or "none",
            module=state.active_module or "unknown",
            counts=counts,
            llm_metadata=llm_ctx if llm_ctx.get("used") else None,
            project_id=ws_id,
        )
        memory_written = bool(mid)
    except Exception:
        pass

    # ═══ 2. Workspace state update (sanitized, no full configs) ═══
    try:
        from workspace.manager import update_workspace_state, get_workspace_state
        from memory.redaction import contains_secret, redact_text
        from memory.policy import can_write_workspace_state

        mr = result.get("manual_review", [])
        us = result.get("unsupported", [])
        dc = result.get("deployable_config", "")

        # Build sanitized state patch — no full configs, no secrets
        patch = {
            "last_run_id": state.request_id,
            "last_intent": state.intent,
            "last_active_module": state.active_module,
            "last_result_summary": (
                f"intent={state.intent} module={state.active_module} "
                f"deployable={len(dc.split(chr(10))) if dc else 0} "
                f"manual_review={len(mr)} unsupported={len(us)}"
            )[:200],
            "last_result_counts": {
                "deployable_lines": len(dc.split("\n")) if dc else 0,
                "manual_review_count": len(mr),
                "unsupported_count": len(us),
            },
            "last_manual_review_samples": [
                {"reason": redact_text(r.get("reason", "")[:80])}
                for r in mr[:5]
            ],
            "last_unsupported_samples": [
                {"reason": redact_text(r.get("reason", "")[:80])}
                for r in us[:5]
            ],
            "last_audit_summary": result.get("audit", {}),
            "llm_metadata": state.context.get("llm", {}),
        }

        # Policy check before writing state
        if can_write_workspace_state(patch):
            update_workspace_state(ws_id, patch)
            workspace_updated = True
    except Exception:
        pass

    # ═══ 3. Run record via workspace.run_store (sanitized) ═══
    try:
        from workspace.run_store import write_run_record
        from memory.redaction import contains_secret

        write_run_record(state, ws_id)
    except Exception:
        pass

    # ═══ Update state context ═══
    state.context["memory_written"] = memory_written
    state.context["workspace_updated"] = workspace_updated

    return state
