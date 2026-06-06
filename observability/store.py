# observability/store.py
"""Trace store — write/read trace records to workspace runs directory."""

import json
import os
from pathlib import Path
from typing import Optional


def _get_ws_root():
    """Get workspace root (deferred, respects test monkeypatches)."""
    try:
        from workspace.manager import WS_ROOT
        return WS_ROOT
    except ImportError:
        return Path(__file__).resolve().parent.parent / "workspaces"


def write_trace(trace, ws_id: str = "default") -> str:
    """Write a trace record to workspace runs directory. Returns trace_id."""
    from workspace.manager import ensure_workspace
    ensure_workspace(ws_id)

    trace_id = trace.trace_id
    run_id = trace.run_id

    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Redact before writing
    from observability.redaction import redact_trace
    data = redact_trace(trace.as_dict())

    path = runs_dir / f"{run_id}.trace.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    return trace_id


def get_trace(run_id: str, ws_id: str = "default") -> Optional[dict]:
    """Get a trace record by run_id."""
    WS_ROOT = _get_ws_root()
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.trace.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_traces(ws_id: str = "default", limit: int = 50) -> list:
    """List trace records for a workspace."""
    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return []

    traces = []
    for f in sorted(runs_dir.glob("*.trace.json"), reverse=True):
        try:
            trace = json.loads(f.read_text())
            traces.append({
                "trace_id": trace.get("trace_id", ""),
                "run_id": trace.get("run_id", ""),
                "workspace_id": trace.get("workspace_id", ""),
                "status": trace.get("status", ""),
                "total_duration_ms": trace.get("total_duration_ms", 0),
                "node_count": trace.get("node_count", 0),
                "event_count": len(trace.get("events", [])),
            })
            if len(traces) >= limit:
                break
        except Exception:
            pass
    return traces


def append_event(trace_id: str, event, ws_id: str = "default"):
    """Append an event to an existing trace."""
    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return

    for path in sorted(runs_dir.glob("*.trace.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            if data.get("trace_id") == trace_id:
                events = data.get("events", [])
                events.append(event.as_dict() if hasattr(event, "as_dict") else event)
                data["events"] = events
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                return
        except Exception:
            pass
