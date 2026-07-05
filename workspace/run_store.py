"""Run store — write sanitized run records to workspace."""

import json
import os
import time
from pathlib import Path
from typing import Optional

from agent.runtime.utils import now_iso, from_iso
from workspace.redaction import redact_text

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def _safe_run_id(raw: str) -> str:
    """Validate or generate a safe run_id used as a path segment.

    Reject anything that could escape the workspace via `..`, `/`, etc.
    Falls back to ``run_<epoch>`` if the supplied value is unsafe.
    """
    from workspace.ids import validate_run_id

    if raw:
        try:
            return validate_run_id(raw)
        except ValueError:
            pass
    return f"run_{int(time.time() * 1000)}"


def write_run_record(state, ws_id: str = "default") -> str:
    """Write a sanitized run record. No full configs, no keys.

    If state.session_id is set, the run is automatically associated
    with that session via add_run_to_session.

    Returns run_id.
    """
    from workspace.manager import ensure_workspace
    ws_id = ensure_workspace(ws_id)

    run_dir = WS_ROOT / ws_id / "runs"
    run_id = _safe_run_id(state.request_id or f"run_{int(time.time())}")
    created_at = getattr(state, "created_at", "") or now_iso()

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
        "created_at": created_at,
        "user_input_summary": redact_text(state.user_input or "")[:120],
        "intent": state.intent,
        "capability": state.context.get("capability_id", ""),
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "runtime_mode": state.runtime_mode,
        "started_at": created_at,
        "finished_at": now_iso(),
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

    from core.graph.projection_events import append_run_record_written
    event_id = append_run_record_written(
        workspace_id=ws_id,
        session_id=state.session_id or "",
        run_id=run_id,
        record=record,
    )
    record["ssot_event_id"] = event_id
    record["projection_of"] = "GraphStore"

    # ── Atomic write (P1-18): UUID tmp + fsync before rename ──
    import uuid as _uuid
    from pathlib import Path
    record_path = run_dir / f"{run_id}.json"
    tmp_path = record_path.with_name(f"{run_id}.{_uuid.uuid4().hex[:8]}.tmp")
    tmp_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.fsync(tmp_path.open("r+").fileno())
    tmp_path.rename(record_path)

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
    """Derive the run record's `status` field from runtime truth.

    v3.9.1 fix: previously this read `result.get("ok")`, but `result` at the
    call site (write_run_record) was `state.skill_results or state.tool_results
    or {}`, which is the *tool skill payload* (deployable_config / manual_review
    / unsupported / semantic_near / audit) — it does NOT carry `ok`. So
    `result.get("ok")` was always None, and status always fell through to "ok"
    even when the run actually failed. Meanwhile _merge_result_projection later
    wrote the real `ok` field, producing the inconsistency seen by the UI
    (list says "ok", detail says "failed").

    Order of precedence:
    1. explicit state.error → "error"
    2. state.context.capability_status == "planned" → "planned"
    3. state.result_ok explicitly False → "error"
    4. state.result_errors non-empty → "error"
    5. otherwise → "ok"
    """
    if state.error:
        return "error"
    if state.context.get("capability_status") == "planned":
        return "planned"
    # Prefer the explicit AgentResult fields placed on state by the caller
    # (turn_persistence.persist_run_record).
    result_ok = getattr(state, "result_ok", None)
    if result_ok is False:
        return "error"
    # Dict result payloads are still accepted by persistence callers. If an
    # explicit state.result_ok is absent, use the dict's ok field.
    if result_ok is None and isinstance(result, dict):
        dict_ok = result.get("ok")
        if dict_ok is False:
            return "error"
    result_errors = getattr(state, "result_errors", None)
    if result_errors:  # non-empty list
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
    from workspace.ids import validate_run_id, validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    run_id = validate_run_id(run_id)
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.json"
    if path.is_file():
        try:
            return _normalize_run_record(json.loads(path.read_text()))
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
        if not _is_run_record_file(f):
            continue
        try:
            runs.append(_normalize_run_record(json.loads(f.read_text())))
        except Exception:
            pass
    runs.sort(key=run_sort_key, reverse=True)
    return runs[:limit]


def _is_run_record_file(path: Path) -> bool:
    """Return True only for canonical run records.

    The runs directory also stores sidecar JSON documents such as
    ``*.trace.json`` and ``*.decision.json``. Those must never be surfaced as
    user-visible run rows.
    """
    name = path.name
    if not name.endswith(".json"):
        return False
    return not (
        name.endswith(".trace.json")
        or name.endswith(".decision.json")
    )


def run_sort_key(record: dict) -> tuple:
    """Sort newest first by the canonical timezone-aware ISO timestamp."""
    stamp = record.get("created_at") or record.get("started_at") or record.get("finished_at") or ""
    parsed = _timestamp_seconds(stamp)
    if parsed is not None:
        return (1, parsed, str(record.get("run_id", "")))
    return (0, str(stamp), str(record.get("run_id", "")))


def _timestamp_seconds(value: str) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return from_iso(text)
    except ValueError:
        return None


def _normalize_run_record(record: dict) -> dict:
    """Return only canonical run records."""
    return record if isinstance(record, dict) else {}


def get_last_run(ws_id: str = "default") -> Optional[dict]:
    """Get the most recent run record."""
    runs = list_runs(ws_id, limit=1)
    return runs[0] if runs else None


def write_sub_agent_run(
    ws_id: str,
    child_session_id: str,
    parent_run_id: str,
    child_run_id: str,
    instruction: str,
    ok: bool,
    final_response: str,
    tool_calls_count: int,
    steps: int,
    visible_tool_ids: list,
) -> str:
    """v3.2.0 (Guardian): write a structured run record for a sub-agent.

    Sub-agents normally re-use the main `write_run_record` path indirectly
    via their inner `run_turn`. This helper captures the *parent-visible*
    audit footprint: who spawned whom, with what tools, and what the child
    returned. The record uses the parent_run_id as the canonical run_id so
    a sub-agent invocation is a single line in the parent timeline.
    """
    from workspace.manager import ensure_workspace
    from workspace.redaction import redact_text
    ws_id = ensure_workspace(ws_id)

    run_dir = WS_ROOT / ws_id / "runs"
    run_id = parent_run_id
    created_at = now_iso()

    record = {
        "run_id": run_id,
        "workspace_id": ws_id,
        "session_id": child_session_id,
        "request_id": child_run_id,
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": now_iso(),
        "kind": "sub_agent",
        "is_sub_agent": True,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "child_session_id": child_session_id,
        "user_input_summary": redact_text(instruction or "")[:300],
        "intent": "sub_agent",
        "status": "ok" if ok else "error",
        "final_response_summary": redact_text(final_response or "")[:500],
        "tool_calls_count": tool_calls_count,
        "steps": steps,
        "visible_tool_ids": list(visible_tool_ids or [])[:200],
        "sensitivity": "internal",
        "redaction_applied": True,
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    # P1-19: use child_run_id for filename so children don't overwrite each other
    import uuid as _uuid
    write_id = child_run_id or f"{parent_run_id}.sub.{_uuid.uuid4().hex[:8]}"
    record_path = run_dir / f"{write_id}.json"
    tmp_path = record_path.with_name(f"{write_id}.{_uuid.uuid4().hex[:8]}.tmp")
    tmp_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.fsync(tmp_path.open("r+").fileno())
    tmp_path.rename(record_path)
    return write_id
