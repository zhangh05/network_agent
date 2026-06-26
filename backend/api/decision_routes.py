# backend/api/decision_routes.py
"""Decision Report API — read per-turn decision reports."""

from __future__ import annotations

from flask import jsonify

from backend.core.responses import error_response, item_response
from workspace.ids import validate_workspace_id


def register_decision_routes(app):
    """Register decision report read routes."""

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/decision")
    def api_run_decision(ws_id: str, run_id: str):
        """GET /api/workspaces/<ws>/runs/<run_id>/decision

        Returns the full (redacted) decision report for a run.
        """
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            body, code = error_response("INVALID_WORKSPACE_ID", "invalid workspace_id", 400)
            return jsonify(body), code

        from agent.runtime.decision_report.writer import read_decision_report
        report = read_decision_report(str(run_id), ws_id)

        if not report:
            body, code = error_response(
                "DECISION_REPORT_NOT_FOUND",
                "decision report not found for this run",
                404,
            )
            return jsonify(body), code

        body, code = item_response(report, workspace_id=ws_id)
        return jsonify(body), code
