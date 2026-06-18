# backend/api/workspace_routes.py
"""Workspace, Run, Report & Trace routes."""

from flask import jsonify, request
from workspace.ids import validate_session_id, validate_workspace_id
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


def _validated_session_id(raw):
    try:
        return validate_session_id(raw), None
    except ValueError:
        return None, (jsonify({"ok": False, "error": "invalid_session_id"}), 400)


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

    @app.route("/api/workspaces", methods=["POST"])
    def api_workspace_create():
        data = request.get_json(silent=True) or {}
        ws_id = data.get("workspace_id", "")
        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id required"}), 400
        from workspace.manager import ensure_workspace
        from workspace.ids import validate_workspace_id
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400
        ensure_workspace(ws_id)
        from workspace.manager import get_workspace_state
        state = get_workspace_state(ws_id)
        return jsonify({"ok": True, "workspace": state})

    @app.route("/api/workspaces/<ws_id>/state")
    def api_workspace_state(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from workspace.manager import get_workspace_state
        return jsonify(get_workspace_state(ws_id))

    @app.route("/api/workspaces/<ws_id>", methods=["DELETE"])
    def api_workspace_delete(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from workspace.manager import delete_workspace
        return jsonify(delete_workspace(ws_id))

    @app.route("/api/workspaces/batch-delete", methods=["POST"])
    def api_workspace_batch_delete():
        data = request.get_json(silent=True) or {}
        ws_ids = data.get("workspace_ids", [])
        if not isinstance(ws_ids, list) or len(ws_ids) == 0:
            return jsonify({"ok": False, "error": "workspace_ids must be a non-empty list"}), 400
        from workspace.manager import batch_delete_workspaces
        return jsonify(batch_delete_workspaces(ws_ids))

    @app.route("/api/workspaces/<ws_id>/rename", methods=["POST"])
    def api_workspace_rename(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        new_id = data.get("new_workspace_id", "")
        if not new_id:
            return jsonify({"ok": False, "error": "new_workspace_id required"}), 400
        from workspace.manager import rename_workspace
        new_id_validated, err2 = _validated_ws_id(new_id)
        if err2:
            return err2
        return jsonify(rename_workspace(ws_id, new_id_validated))

    # ── Runs ──
    @app.route("/api/runs/recent")
    def api_runs_recent():
        """Recent runs — safe summaries, no full config.

        Query params:
          workspace_id  (default: "default")
          limit         (default: 10, max: 100)
          session_id    (optional: exact session scope for sidebar)
          session_status (default: "active", set to "" for all sessions)
        """
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        limit, err = _validated_limit(default=10, max_value=100)
        if err:
            return err
        session_id = request.args.get("session_id", "").strip()
        if session_id:
            session_id, err = _validated_session_id(session_id)
            if err:
                return err

        from workspace.run_store import list_runs, run_sort_key
        from workspace.session_store import get_session, list_sessions

        # Fetch more runs than needed to account for filtering
        raw_runs = list_runs(ws_id, limit=limit * 5)
        runs_sorted = sorted(raw_runs, key=run_sort_key, reverse=True) if raw_runs else []

        # session_status="" means no filter (all sessions for RuntimeAudit)
        session_status = request.args.get("session_status", "active")
        if session_id:
            session = get_session(session_id, ws_id)
            if not session or (session_status and session.get("status") != session_status):
                recent = []
                session_titles = {}
            else:
                recent = [r for r in runs_sorted if r.get("session_id", "") == session_id][:limit]
                session_titles = {session_id: session.get("title", "")}
        elif session_status == "":
            # No filtering — return runs from all sessions
            recent = runs_sorted[:limit]
            session_titles: dict = {}
        else:
            # Filter: only show runs from sessions with the given status
            # (default "active" — matches sidebar which only shows active sessions)
            active_sessions = list_sessions(ws_id, status=session_status)
            active_session_ids = {s["session_id"] for s in active_sessions if s.get("session_id")}

            recent = []
            for r in runs_sorted:
                sid = r.get("session_id", "")
                # Include run if: no session_id, or session matches filter
                if not sid or sid in active_session_ids:
                    recent.append(r)
                    if len(recent) >= limit:
                        break

            # Build session_id → title lookup
            session_titles = {s.get("session_id", ""): s.get("title", "") for s in active_sessions if s.get("session_id")}

        safe_recent = []
        # Whitelist of safe fields for public run history (never expose secrets, configs, or prompts)
        _SAFE_RUN_KEYS = frozenset({
            "run_id", "workspace_id", "session_id", "intent",
            "active_module", "selected_skill", "status", "error",
            "warnings", "quality_summary", "elapsed_ms", "created_at",
            "node_timings", "trace_id", "user_input_summary", "final_response",
        })
        for r in recent:
            safe_run = {k: v for k, v in r.items() if k in _SAFE_RUN_KEYS}
            # Attach session title so the frontend can show run→session association
            safe_run["session_title"] = session_titles.get(r.get("session_id", ""), "")
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
        from workspace.run_store import list_runs, run_sort_key
        runs = sorted(list_runs(ws_id, limit=limit), key=run_sort_key, reverse=True)
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
        return jsonify({
            "ok": True,
            "trace": trace,
            "events": trace.get("events", []),
            "run_id": trace.get("run_id", run_id),
        })

    @app.route("/api/workspaces/<ws_id>/traces")
    def api_workspace_traces(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from observability.store import list_traces
        return jsonify({"traces": list_traces(ws_id)})

    # REMOVED (pre-v3.0): /api/agent/runs/<run_id>/trace (duplicate of workspace-scoped trace)

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
