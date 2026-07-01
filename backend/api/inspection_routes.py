"""Inspection API routes.

CMDB-driven device health inspection. Frontend talks to these
directly; the canonical tool ``inspection.manage`` is also registered
for LLM-driven flows.

Endpoints (all require workspace_id):
    POST /api/inspection/tasks            — run an inspection
    GET  /api/inspection/tasks            — list recent tasks
    GET  /api/inspection/tasks/<id>       — get task details
    POST /api/inspection/tasks/<id>/cancel — cancel (MVP: not_supported)
    GET  /api/inspection/tasks/<id>/report — render md|json|html report JSON
    GET  /api/inspection/tasks/<id>/report.html — render viewable HTML report
"""

from __future__ import annotations

from flask import Response, jsonify, request

from workspace.ids import validate_workspace_id

from agent.modules.inspection import service as inspection_service


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw: str = ""):
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def register_inspection_routes(app):
    """Register all inspection routes on the given Flask app."""

    @app.route("/api/inspection/tasks", methods=["POST"])
    def api_inspection_tasks_create():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        scope = data.get("scope") or {}
        if not isinstance(scope, dict):
            return jsonify({"ok": False, "error": "scope_must_be_object"}), 400

        # The runner persists / runs synchronously. The frontend polls
        # task_get once this returns. Status is one of:
        #   pending → running → succeeded | failed | partial
        # v3.9.14 — clamp to the same range the service layer enforces
        # so callers see consistent behaviour regardless of which
        # entry point (HTTP API, service call, or tool) they use.
        try:
            mc = int(data.get("max_concurrency", 3) or 3)
        except (TypeError, ValueError):
            mc = 3
        if mc < 1:
            mc = 1
        if mc > 16:
            mc = 16

        task = inspection_service.create_task(
            workspace_id=ws_id,
            profile_id=str(data.get("profile_id", "") or ""),
            scope=scope,
            created_by=str(data.get("created_by", "user") or "user"),
            session_id=str(data.get("session_id", "") or ""),
            max_concurrency=mc,
        )

        status_code = 200
        if task.status == "failed":
            status_code = 400
        return jsonify({
            "ok": status_code == 200,
            "task_id": task.task_id,
            "status": task.status,
            "profile_id": task.profile_id,
            "scope": {
                "region": task.scope.region,
                "location": task.scope.location,
                "type": task.scope.type,
                "vendor": task.scope.vendor,
                "tags": list(task.scope.tags),
                "asset_ids": list(task.scope.asset_ids),
                "limit": task.scope.limit,
            },
            "summary": {
                "total_devices": task.total_assets,
                "succeeded_devices": task.succeeded,
                "failed_devices": task.failed,
                "skipped_devices": task.skipped,
                "findings_total": task.warnings + task.criticals + task.infos,
                "findings_critical": task.criticals,
                "findings_warning": task.warnings,
                "findings_info": task.infos,
            },
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "error": task.error,
        }), status_code

    @app.route("/api/inspection/tasks", methods=["GET"])
    def api_inspection_tasks_list():
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        try:
            limit = int(request.args.get("limit", "50") or 50)
        except ValueError:
            limit = 50
        items = inspection_service.list_tasks(ws_id, limit=limit)  # service clamps to [1, 200] (v3.9.14)
        return jsonify({
            "ok": True,
            "workspace_id": ws_id,
            "items": items,
            "count": len(items),
        })

    @app.route("/api/inspection/tasks/<task_id>", methods=["GET"])
    def api_inspection_tasks_get(task_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        task = inspection_service.get_task(ws_id, task_id)
        if task is None:
            return jsonify({"ok": False, "error": "task_not_found"}), 404
        from dataclasses import asdict
        return jsonify({"ok": True, "task": asdict(task)})

    @app.route("/api/inspection/tasks/<task_id>/cancel", methods=["POST"])
    def api_inspection_tasks_cancel(task_id):
        ws_id, err = _validated_ws_id(
            (request.get_json(silent=True) or {}).get("workspace_id", "")
            or request.args.get("workspace_id", "")
        )
        if err:
            return err
        result = inspection_service.cancel_task(ws_id, task_id)
        return jsonify(result), (200 if result.get("supported") else 501)

    @app.route("/api/inspection/tasks/<task_id>/report", methods=["GET"])
    def api_inspection_tasks_report(task_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        fmt = (request.args.get("format", "md") or "md").lower()
        if fmt not in ("md", "markdown", "json", "html"):
            return jsonify({"ok": False, "error": f"unsupported_format: {fmt}"}), 400
        if fmt == "markdown":
            fmt = "md"
        result = inspection_service.render_report(ws_id, task_id, fmt)
        if not result.get("ok"):
            status_code = 404 if result.get("error") == "task_not_found" else 400
            return jsonify(result), status_code
        return jsonify(result)

    @app.route("/api/inspection/tasks/<task_id>/report.html", methods=["GET"])
    def api_inspection_tasks_report_html(task_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        result = inspection_service.render_report(ws_id, task_id, "html")
        if not result.get("ok"):
            status_code = 404 if result.get("error") == "task_not_found" else 400
            return jsonify(result), status_code
        filename = str(result.get("filename") or f"inspection_{task_id}.html")
        headers = {"Content-Disposition": f'inline; filename="{filename}"'}
        return Response(
            str(result.get("content") or ""),
            mimetype="text/html; charset=utf-8",
            headers=headers,
        )
