# backend/api/job_routes.py
"""Job API routes — job CRUD and worker management."""

from flask import jsonify, request
from workspace.ids import validate_workspace_id
from jobs.redaction import sanitize_job_record_for_api


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


def register_job_routes(app):
    """Register all job API routes on the Flask app."""

    @app.route("/api/jobs", methods=["POST"])
    def api_job_create():
        data = request.get_json(silent=True) or {}
        workspace_id, err = _validated_ws_id(data.get("workspace_id", "default"))
        if err:
            return err
        from jobs.manager import create_job
        try:
            rec = create_job(
                workspace_id=workspace_id,
                job_type=data.get("job_type", "agent_run"),
                title=data.get("title", ""),
                payload=data.get("payload", {}),
                input_artifacts=data.get("input_artifacts", []),
                enqueue=data.get("enqueue", True),
            )
            if data.get("run_immediately"):
                from jobs.runner import run_job
                run_job(rec.workspace_id, rec.job_id)
            return jsonify({"ok": True, "job": sanitize_job_record_for_api(rec.as_dict())})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/jobs")
    def api_jobs_list():
        ws = request.args.get("workspace_id")
        if ws:
            ws, err = _validated_ws_id(ws)
            if err:
                return err
        status = request.args.get("status")
        jtype = request.args.get("job_type")
        lim, err = _validated_limit(default=100, max_value=500)
        if err:
            return err
        from jobs.store import list_jobs
        return jsonify({"jobs": list_jobs(ws_id=ws, status=status, job_type=jtype, limit=lim)})

    @app.route("/api/jobs/<job_id>")
    def api_job_detail(job_id):
        ws = request.args.get("workspace_id", "")
        if ws:
            ws, err = _validated_ws_id(ws)
            if err:
                return err
        from jobs.store import get_job, list_jobs
        if ws:
            rec = get_job(ws, job_id)
            if not rec:
                return jsonify({"ok": False, "error": "job not found"}), 404
            return jsonify({"ok": True, "job": sanitize_job_record_for_api(rec.as_dict())})
        for j in list_jobs():
            if j.get("job_id") == job_id:
                return jsonify({"ok": True, "job": j})
        return jsonify({"ok": False, "error": "job not found"}), 404

    @app.route("/api/workspaces/<ws_id>/jobs")
    def api_workspace_jobs(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from jobs.store import list_jobs
        return jsonify({"jobs": list_jobs(ws_id=ws_id)})

    @app.route("/api/workspaces/<ws_id>/jobs/<job_id>")
    def api_workspace_job_detail(ws_id, job_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from jobs.store import get_job
        rec = get_job(ws_id, job_id)
        if not rec:
            return jsonify({"ok": False, "error": "job not found"}), 404
        return jsonify({"ok": True, "job": sanitize_job_record_for_api(rec.as_dict())})

    @app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
    def api_job_cancel(job_id):
        ws, err = _validated_ws_id((request.get_json(silent=True) or {}).get("workspace_id", "default"))
        if err:
            return err
        from jobs.manager import cancel_job
        try:
            rec = cancel_job(ws, job_id)
            return jsonify({"ok": True, "job": sanitize_job_record_for_api(rec.as_dict())})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/jobs/<job_id>/retry", methods=["POST"])
    def api_job_retry(job_id):
        ws, err = _validated_ws_id((request.get_json(silent=True) or {}).get("workspace_id", "default"))
        if err:
            return err
        from jobs.manager import retry_job
        try:
            rec = retry_job(ws, job_id)
            return jsonify({"ok": True, "job": sanitize_job_record_for_api(rec.as_dict())})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/jobs/<job_id>/events")
    def api_job_events(job_id):
        ws, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        from jobs.store import list_events
        return jsonify({"events": list_events(ws, job_id)})

    @app.route("/api/jobs/<job_id>/logs")
    def api_job_logs(job_id):
        ws, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        from jobs.store import list_logs
        return jsonify({"logs": list_logs(ws, job_id)})

    @app.route("/api/jobs/<job_id>/artifacts")
    def api_job_artifacts(job_id):
        ws, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        from jobs.store import get_job
        rec = get_job(ws, job_id)
        if not rec:
            return jsonify({"ok": False, "error": "job not found"}), 404
        return jsonify({"input_artifacts": rec.input_artifacts,
                        "output_artifacts": rec.output_artifacts,
                        "report_artifacts": rec.report_artifacts})

    @app.route("/api/jobs/worker/run-once", methods=["POST"])
    def api_worker_run_once():
        from jobs.worker import run_once
        result = run_once()
        return jsonify({"ok": True, **result})

    @app.route("/api/jobs/worker/status")
    def api_worker_status():
        from jobs.worker import get_worker_state
        return jsonify(get_worker_state())
