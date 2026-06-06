"""Run store — write sanitized run records to workspace."""

import json
import os
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def write_run_record(state, ws_id: str = "default") -> str:
    """Write a sanitized run record. No full configs, no keys.

    Returns run_id.
    """
    from workspace.manager import ensure_workspace
    ensure_workspace(ws_id)

    run_dir = WS_ROOT / ws_id / "runs"
    run_id = state.request_id or f"run_{int(time.time())}"

    result = state.tool_results or {}
    llm_ctx = state.context.get("llm", {})

    # Build sanitized counts (no full config strings)
    dc_lines = 0
    if result.get("deployable_config"):
        dc_lines = len(result.get("deployable_config", "").split("\n"))

    record = {
        "run_id": run_id,
        "workspace_id": ws_id,
        "request_id": state.request_id,
        "user_input_summary": (state.user_input or "")[:120],
        "intent": state.intent,
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "runtime_mode": state.runtime_mode,
        "started_at": state.created_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "error" if state.error else "ok",
        "result_counts": {
            "deployable_lines": dc_lines,
            "manual_review": len(result.get("manual_review", [])),
            "semantic_near": len(result.get("semantic_near", [])),
            "unsupported": len(result.get("unsupported", [])),
        },
        "verification": {},
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
        "artifacts": [],
        "warnings": state.warnings or [],
        "error": state.error,
        "sensitivity": "internal",
        "redaction_applied": True,
    }

    (run_dir / f"{run_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
    return run_id


def get_run(run_id: str, ws_id: str = "default") -> dict:
    """Get a run record."""
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
    ensure_workspace(ws_id)

    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return []

    runs = []
    for f in sorted(runs_dir.glob("*.json"), reverse=True):
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
