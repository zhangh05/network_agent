"""Run store — write sanitized run records to workspace."""

import json
import time
from pathlib import Path
from typing import Optional

from memory.redaction import redact_text

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def write_run_record(state, ws_id: str = "default") -> str:
    """Write a sanitized run record. No full configs, no keys.

    If state.session_id is set, the run is automatically associated
    with that session via add_run_to_session.

    Returns run_id.
    """
    from workspace.manager import ensure_workspace
    ws_id = ensure_workspace(ws_id)

    run_dir = WS_ROOT / ws_id / "runs"
    run_id = state.request_id or f"run_{int(time.time())}"

    result = state.skill_results or state.tool_results or {}
    llm_ctx = state.context.get("llm", {})

    # Build sanitized counts (no full config strings)
    dc_lines = 0
    if result.get("deployable_config"):
        dc_lines = len(result.get("deployable_config", "").split("\n"))

    safe_warnings = [redact_text(str(w))[:300] for w in (state.warnings or [])[:20]]
    artifact_refs = _safe_ref_list(state.context.get("artifact_refs", []))
    if not artifact_refs:
        artifact_refs = _safe_artifact_refs_from_context(state)

    record = {
        "run_id": run_id,
        "workspace_id": ws_id,
        "session_id": state.session_id or "",
        "request_id": state.request_id,
        "created_at": state.created_at,
        "user_input_summary": redact_text(state.user_input or "")[:120],
        "intent": state.intent,
        "capability": state.context.get("capability_id", ""),
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "runtime_mode": state.runtime_mode,
        "started_at": state.created_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": _safe_status(state, result),
        "result_counts": {
            "deployable_lines": dc_lines,
            "manual_review": len(result.get("manual_review", [])),
            "semantic_near": len(result.get("semantic_near", [])),
            "unsupported": len(result.get("unsupported", [])),
        },
        "final_response_summary": redact_text(state.final_response or "")[:300],
        "verification": {},
        # ── Quality summary (counts only, no full config) ──
        "quality_summary": _safe_quality_summary(result),
        "manual_review_count": len(result.get("manual_review", [])),
        "llm_metadata": {
            "used": llm_ctx.get("used", False),
            "provider": llm_ctx.get("provider", ""),
            "model": llm_ctx.get("model", ""),
            "task": llm_ctx.get("task", ""),
            "config_source": llm_ctx.get("config_source", "default"),
            "fallback_reason": llm_ctx.get("fallback_reason"),
        },
        "memory_written": state.context.get("memory_written", False),
        "workspace_updated": state.context.get("workspace_updated", False),
        "artifact_refs": artifact_refs,
        "report_refs": _safe_ref_list(state.context.get("report_refs", [])),
        "job_refs": _safe_ref_list(state.context.get("job_refs", [])),
        "trace_id": state.trace_id or "",
        "artifacts": [],
        "warnings": safe_warnings,
        "error": state.error,
        "sensitivity": "internal",
        "redaction_applied": True,
    }

    (run_dir / f"{run_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )

    # Associate run with session if session_id is present
    if state.session_id:
        try:
            from workspace.session_store import add_run_to_session, auto_title_from_input
            add_run_to_session(state.session_id, run_id, ws_id)
            # Auto-title session from first meaningful user input
            if state.user_input and len(state.user_input.strip()) > 0:
                auto_title_from_input(state.session_id, state.user_input, ws_id)
        except Exception:
            pass

    return run_id


def _safe_quality_summary(result: dict) -> dict:
    """Extract safe quality summary counts — no full config, no secrets."""
    qs = result.get("quality_summary", {})
    keys = [
        "source_residue_count",
        "silent_drop_count",
        "unsupported_count",
        "safe_drop_count",
        "review_required_count",
    ]
    if isinstance(qs, dict):
        safe = {}
        for key in keys:
            value = qs.get(key, 0)
            safe[key] = value if isinstance(value, int) else 0
        return safe
    # Build from direct result fields
    return {
        "source_residue_count": 0,
        "silent_drop_count": 0,
        "review_required_count": len(result.get("manual_review", [])),
        "unsupported_count": len(result.get("unsupported", [])),
        "safe_drop_count": 0,
    }


def _safe_status(state, result: dict) -> str:
    if state.error:
        return "error"
    if state.context.get("capability_status") == "planned":
        return "planned"
    if isinstance(result, dict) and result.get("ok") is False:
        return "error"
    return "ok"


def _safe_ref_list(items) -> list:
    """Return reference IDs/summaries only, stripped of paths and long content."""
    safe = []
    if not isinstance(items, list):
        return safe
    for item in items[:50]:
        if isinstance(item, str):
            value = redact_text(item)
            if "/" not in value and "\\" not in value:
                safe.append(value[:120])
        elif isinstance(item, dict):
            safe_item = {}
            for key in ("artifact_id", "report_id", "job_id", "type", "title", "summary"):
                if key in item:
                    safe_item[key] = redact_text(str(item[key]))[:200]
            if safe_item:
                safe.append(safe_item)
    return safe


def _safe_artifact_refs_from_context(state) -> list:
    refs = []
    for key in ("input_artifacts", "output_artifacts", "report_artifacts"):
        for art_id in state.context.get(key, [])[:20]:
            refs.append({"artifact_id": redact_text(str(art_id))[:120], "type": key})
    return refs


def get_run(run_id: str, ws_id: str = "default") -> dict:
    """Get a run record."""
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def list_runs(ws_id: str = "default", limit: int = 50) -> list:
    """List recent run records."""
    from workspace.manager import ensure_workspace
    ws_id = ensure_workspace(ws_id)

    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return []

    runs = []
    for f in sorted(runs_dir.glob("*.json"), reverse=True):
        if f.name.endswith(".trace.json"):
            continue
        try:
            runs.append(json.loads(f.read_text()))
            if len(runs) >= limit:
                break
        except Exception:
            pass
    return runs


def get_last_run(ws_id: str = "default") -> Optional[dict]:
    """Get the most recent run record."""
    runs = list_runs(ws_id, limit=1)
    return runs[0] if runs else None
