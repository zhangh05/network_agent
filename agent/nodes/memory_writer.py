"""Memory writer node — memory + workspace state + run record with artifact refs."""

import json, os, time
from agent.state import NetworkAgentState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write_memory(state: NetworkAgentState) -> NetworkAgentState:
    """Write memory, workspace state, and run record with policy enforcement."""
    if state.error:
        return state

    result = state.skill_results or state.tool_results or {}
    ws_id = state.workspace_id or "default"
    memory_written = False
    workspace_updated = False

    # ═══ Build artifact refs (sanitized) ═══
    artifact_refs = _build_artifact_refs(state, ws_id)

    # ═══ 1. Memory run_summary with artifact_refs ═══
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
            artifact_refs=artifact_refs,
        )
        memory_written = bool(mid)
    except Exception:
        pass

    # ═══ 2. Workspace state update with artifact counts ═══
    try:
        from workspace.manager import update_workspace_state
        from memory.redaction import redact_text
        from artifacts.store import get_run_artifacts

        mr = result.get("manual_review", [])
        us = result.get("unsupported", [])
        dc = result.get("deployable_config", "")

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
            "last_input_artifacts": state.context.get("input_artifacts", []),
            "last_output_artifacts": state.context.get("output_artifacts", []),
            "current_artifacts": artifact_refs[:20],
            "artifact_counts": _compute_artifact_counts(ws_id),
            "last_manual_review_samples": [
                {"reason": redact_text(r.get("reason", "")[:80])} for r in mr[:5]
            ],
            "last_unsupported_samples": [
                {"reason": redact_text(r.get("reason", "")[:80])} for r in us[:5]
            ],
            "last_audit_summary": result.get("audit", {}),
            "llm_metadata": state.context.get("llm", {}),
        }
        update_workspace_state(ws_id, patch)
        workspace_updated = True
    except Exception:
        pass

    # ═══ 3. Run record with artifact refs ═══
    try:
        from workspace.run_store import write_run_record
        write_run_record(state, ws_id)
    except Exception:
        pass

    state.context["memory_written"] = memory_written
    state.context["workspace_updated"] = workspace_updated
    state.context["artifact_refs"] = artifact_refs
    return state


def _build_artifact_refs(state, ws_id) -> list:
    """Build sanitized artifact refs — no content, no key, no absolute path."""
    refs = []
    all_ids = (state.context.get("input_artifacts", []) +
               state.context.get("output_artifacts", []))
    seen = set()
    try:
        from artifacts.store import get_artifact
        for aid in all_ids:
            if aid in seen:
                continue
            seen.add(aid)
            rec = get_artifact(ws_id, aid)
            if not rec:
                continue
            # Exclude temp and secret from memory
            if rec.sensitivity == "secret" or rec.scope == "temp":
                continue
            ref = {
                "artifact_id": rec.artifact_id,
                "artifact_type": rec.artifact_type,
                "title": rec.title,
                "summary": rec.summary[:200] if rec.summary else "",
                "scope": rec.scope,
                "sensitivity": rec.sensitivity,
                "sha256_short": rec.sha256[:12] if rec.sha256 else "",
                "metadata": {
                    "line_count": rec.metadata.get("line_count", 0) if rec.metadata else 0,
                    "probable_vendor": rec.metadata.get("probable_vendor", "") if rec.metadata else "",
                },
            }
            refs.append(ref)
    except Exception:
        pass
    return refs


def _compute_artifact_counts(ws_id) -> dict:
    try:
        from artifacts.store import list_artifacts
        arts = list_artifacts(ws_id, limit=1000)
        counts = {
            "total": len(arts),
            "input_config": 0, "output_config": 0, "report": 0,
            "topology_json": 0, "topology_image": 0,
            "inspection_log": 0, "knowledge_doc": 0,
            "sensitive": 0, "secret": 0,
        }
        for a in arts:
            t = a.get("artifact_type", "unknown")
            if t in counts:
                counts[t] += 1
            s = a.get("sensitivity", "")
            if s in ("sensitive", "secret"):
                counts[s] += 1
        return counts
    except Exception:
        return {"total": 0}
