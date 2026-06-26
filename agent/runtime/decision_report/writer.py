# agent/runtime/decision_report/writer.py
"""Decision Report writer — atomic write to workspaces/<ws>/runs/<run_id>.decision.json."""

from __future__ import annotations

import json
import time
from pathlib import Path


def write_decision_report(
    report: dict,
    *,
    ws_root=None,
) -> str | None:
    """Write a decision report to disk using atomic write (tmp → rename).

    Path: <ws_root>/<workspace_id>/runs/<run_id>.decision.json

    Returns the relative report path on success, None on failure.
    Does NOT raise — failure is recorded as a turn warning, not a turn failure.
    """
    try:
        run_id = str(report.get("run_id", ""))
        ws_id = str(report.get("workspace_id", ""))

        if not run_id:
            return None

        # Resolve ws_root
        if ws_root is None:
            from workspace.run_store import WS_ROOT
            ws_root = WS_ROOT

        runs_dir = Path(ws_root) / ws_id / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        report_path = runs_dir / f"{run_id}.decision.json"
        tmp_path = report_path.with_suffix(".decision.tmp")

        # Apply redaction
        from agent.runtime.decision_report.redaction import redact_decision_report
        safe_report = redact_decision_report(report)

        # Update trace summary from the actual trace file if it exists
        _enrich_trace_summary(safe_report, runs_dir, run_id)

        # Atomic write: tmp → rename
        tmp_path.write_text(
            json.dumps(safe_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.rename(report_path)

        return f"runs/{run_id}.decision.json"

    except Exception:
        return None


def _enrich_trace_summary(report: dict, runs_dir: Path, run_id: str) -> None:
    """If a trace file exists, fill real/synthetic/missing counts.

    Reads from workspaces/<ws>/runs/<run_id>.trace.json.
    """
    try:
        trace_path = runs_dir / f"{run_id}.trace.json"
        if not trace_path.is_file():
            return

        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))

        report["trace_summary"] = {
            "real_event_count": trace_data.get("real_event_count", 0),
            "synthetic_event_count": trace_data.get("synthetic_event_count", 0),
            "missing_event_count": trace_data.get("missing_event_count", 0),
        }
    except Exception:
        pass


def get_decision_report_path(run_id: str, ws_id: str, ws_root=None) -> Path | None:
    """Return the path to a decision report file if it exists."""
    try:
        if ws_root is None:
            from workspace.run_store import WS_ROOT
            ws_root = WS_ROOT
        path = Path(ws_root) / ws_id / "runs" / f"{run_id}.decision.json"
        return path if path.is_file() else None
    except Exception:
        return None


def read_decision_report(run_id: str, ws_id: str, ws_root=None) -> dict | None:
    """Read a decision report from disk."""
    path = get_decision_report_path(run_id, ws_id, ws_root)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
