# backend/api/workspace_routes.py
"""Workspace, Run, Report & Trace routes."""

from flask import jsonify, request
from workspace.ids import validate_workspace_id
from artifacts.store import sanitize_record


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _invalid_limit():
    return jsonify({"ok": False, "error": "invalid_limit"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def _validated_limit(default=100, max_value=500):
    from backend.api.params import parse_limit
    try:
        return parse_limit(request.args, default=default, max_value=max_value), None
    except ValueError:
        return None, _invalid_limit()


def register_workspace_routes(app):
    """Register workspace, run, report, and trace API routes."""

    # ── Workspace ──
    @app.route("/api/workspaces")
    def api_workspaces_list():
        from workspace.manager import list_workspaces
        return jsonify({"workspaces": list_workspaces()})

    @app.route("/api/workspaces/<ws_id>/state")
    def api_workspace_state(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from workspace.manager import get_workspace_state
        return jsonify(get_workspace_state(ws_id))

    # ── Runs ──
    @app.route("/api/runs/recent")
    def api_runs_recent():
        """Recent runs for the default workspace — safe summaries, no full config."""
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        limit, err = _validated_limit(default=10, max_value=100)
        if err:
            return err
        from workspace.run_store import list_runs
        runs = list_runs(ws_id, limit=limit)
        runs_sorted = sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True) if runs else []
        recent = runs_sorted[:limit]
        safe_recent = []
        for r in recent:
            safe_run = {k: v for k, v in r.items() if k not in ("source_config", "deployable_config", "prompt", "full_context", "safe_context")}
            safe_recent.append(safe_run)
        return jsonify({"runs": safe_recent, "count": len(safe_recent)})

    @app.route("/api/runs/<run_id>")
    def api_run_detail(run_id):
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from workspace.run_store import get_run
        result = get_run(run_id, ws_id)
        if not result:
            return jsonify({"ok": False, "error": "run not found"}), 404
        return jsonify(result)

    @app.route("/api/workspaces/<ws_id>/runs")
    def api_workspace_runs(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        limit, err = _validated_limit(default=100, max_value=500)
        if err:
            return err
        from workspace.run_store import list_runs
        return jsonify({"runs": list_runs(ws_id, limit=limit)})

    @app.route("/api/workspaces/<ws_id>/history")
    def api_workspace_history(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        limit, err = _validated_limit(default=100, max_value=500)
        if err:
            return err
        from workspace.run_store import list_runs
        runs = sorted(list_runs(ws_id, limit=limit), key=lambda r: r.get("created_at", ""), reverse=True)
        return jsonify({"workspace_id": ws_id, "runs": runs, "count": len(runs)})

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>")
    def api_workspace_run(ws_id, run_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from workspace.run_store import get_run
        result = get_run(run_id, ws_id)
        if not result:
            return jsonify({"ok": False, "error": "run not found"}), 404
        return jsonify(result)

    # ── Trace (Observability) ──
    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/trace")
    def api_workspace_trace(ws_id, run_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from observability.store import get_trace
        trace = get_trace(run_id, ws_id)
        if not trace:
            return jsonify({"ok": False, "error": "trace not found"}), 404
        return jsonify({"ok": True, "trace": trace})

    @app.route("/api/workspaces/<ws_id>/traces")
    def api_workspace_traces(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from observability.store import list_traces
        return jsonify({"traces": list_traces(ws_id)})

    @app.route("/api/agent/runs/<run_id>/trace")
    def api_agent_run_trace(run_id):
        from observability.store import get_trace
        trace = get_trace(run_id, "default")
        if not trace:
            return jsonify({"ok": False, "error": "trace not found"}), 404
        return jsonify({"ok": True, "trace": trace})

    # ── Reports / Export ──
    @app.route("/api/reports/create", methods=["POST"])
    def api_report_create():
        data = request.get_json(silent=True) or {}
        workspace_id, err = _validated_ws_id(data.get("workspace_id", "default"))
        if err:
            return err
        from reports_engine.schemas import ReportRequest
        from reports_engine.service import create_report as svc_create_report
        req = ReportRequest(
            workspace_id=workspace_id,
            run_id=data.get("run_id", ""),
            report_type=data.get("report_type", "config_translation"),
            title=data.get("title", ""),
            format=data.get("format", "markdown"),
            include_deployable_config=data.get("include_deployable_config", False),
            sensitivity=data.get("sensitivity", "internal"),
        )
        result = svc_create_report(req)
        return jsonify(result.as_dict())

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/report", methods=["POST"])
    def api_workspace_run_report(ws_id, run_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        from reports_engine.service import create_config_translation_report
        result = create_config_translation_report(
            ws_id, run_id, {},
            fmt=data.get("format", "markdown"),
            include_deployable=data.get("include_deployable_config", False),
        )
        return jsonify(result.as_dict())

    @app.route("/api/workspaces/<ws_id>/reports")
    def api_workspace_reports(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from artifacts.store import list_artifacts
        arts = list_artifacts(ws_id, artifact_type="report")
        return jsonify({"reports": arts})

    @app.route("/api/workspaces/<ws_id>/reports/<artifact_id>/content")
    def api_report_content(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from artifacts.store import read_artifact_content
        allow = request.args.get("allow_sensitive", "0") == "1"
        content = read_artifact_content(ws_id, artifact_id, allow_sensitive=allow)
        if content is None:
            return jsonify({"ok": False, "error": "content not accessible"}), 403
        return jsonify({"ok": True, "content": content})
