"""Run store — write run records to workspace."""

import json, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

def write_run_record(state, ws_id="default"):
    from workspace.manager import ensure_workspace
    ensure_workspace(ws_id)
    run_dir = WS_ROOT / ws_id / "runs"
    run_id = state.request_id or f"run_{int(time.time())}"
    record = {
        "run_id": run_id, "workspace_id": ws_id, "request_id": state.request_id,
        "user_input_summary": (state.user_input or "")[:120],
        "intent": state.intent, "active_module": state.active_module,
        "selected_skill": state.selected_skill, "runtime_mode": state.runtime_mode,
        "started_at": state.created_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "error" if state.error else "ok",
        "result_counts": {
            "deployable": len((state.tool_results or {}).get("deployable_config", "").split("\n")) if (state.tool_results or {}).get("deployable_config") else 0,
            "manual_review": len((state.tool_results or {}).get("manual_review", [])),
        },
        "llm_metadata": state.context.get("llm", {}),
        "memory_written": True, "warnings": state.warnings,
        "error": state.error, "sensitivity": "internal", "redaction_applied": True,
    }
    (run_dir / f"{run_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return run_id
