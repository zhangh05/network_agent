# backend/api/state_routes.py
"""Runtime State API — Phase 2 endpoints.

GET  /api/runtime/tasks?workspace_id=&session_id=
GET  /api/runtime/tasks/<task_id>?workspace_id=
GET  /api/runtime/tasks/<task_id>/events?workspace_id=
GET  /api/runtime/tasks/<task_id>/checkpoints?workspace_id=
"""

from __future__ import annotations


def register_state_routes(app):
    """Register runtime state API routes on the Flask app."""

    @app.route("/api/runtime/tasks")
    def api_runtime_tasks():
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")
        session_id = request.args.get("session_id", "")

        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400

        try:
            from agent.runtime.durable.store import list_tasks
            tasks = list_tasks(ws_id, session_id=session_id)
            return jsonify({
                "ok": True,
                "tasks": [t.to_dict() for t in tasks],
                "count": len(tasks),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>")
    def api_runtime_task_detail(task_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")

        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400

        try:
            from agent.runtime.durable.store import get_task
            task = get_task(ws_id, task_id)
            if not task:
                return jsonify({"ok": False, "error": "task not found"}), 404
            # Ensure boundary: task must belong to this workspace
            if task.workspace_id != ws_id:
                return jsonify({"ok": False, "error": "task not found in workspace"}), 404
            return jsonify({"ok": True, "task": task.to_dict()})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>/events")
    def api_runtime_task_events(task_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")

        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400

        try:
            from agent.runtime.durable.store import get_task, get_events
            task = get_task(ws_id, task_id)
            if not task or task.workspace_id != ws_id:
                return jsonify({"ok": False, "error": "task not found"}), 404
            events = get_events(ws_id, task_id)
            return jsonify({"ok": True, "events": events, "count": len(events)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>/checkpoints")
    def api_runtime_task_checkpoints(task_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")

        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400

        try:
            from agent.runtime.durable.store import get_task, get_checkpoints
            task = get_task(ws_id, task_id)
            if not task or task.workspace_id != ws_id:
                return jsonify({"ok": False, "error": "task not found"}), 404
            checkpoints = get_checkpoints(ws_id, task_id)
            return jsonify({"ok": True, "checkpoints": checkpoints, "count": len(checkpoints)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    # ── Phase 3: Control endpoints (POST) ──

    @app.route("/api/runtime/tasks/<task_id>/checkpoint", methods=["POST"])
    def api_task_checkpoint(task_id):
        from flask import request, jsonify
        ws_id = (request.args.get("workspace_id", "") or
                 (request.get_json(silent=True) or {}).get("workspace_id", ""))
        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400
        try:
            from agent.runtime.durable.control import checkpoint_task
            reason = (request.get_json(silent=True) or {}).get("reason", "manual")
            cp = checkpoint_task(task_id, ws_id, reason=reason)
            if not cp:
                return jsonify({"ok": False, "error": "task not found"}), 404
            return jsonify({"ok": True, "checkpoint_id": cp.checkpoint_id})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>/cancel", methods=["POST"])
    def api_task_cancel(task_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")
        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400
        try:
            from agent.runtime.durable.control import cancel_task
            result = cancel_task(task_id, ws_id)
            code = 200 if result["ok"] else (404 if "not found" in result.get("error","") else 400)
            return jsonify(result), code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>/resume", methods=["POST"])
    def api_task_resume(task_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")
        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400
        try:
            from agent.runtime.durable.control import resume_task
            result = resume_task(task_id, ws_id)
            code = 200 if result["ok"] else (404 if "not found" in result.get("error","") else 400)
            return jsonify(result), code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/runtime/tasks/<task_id>/steps/<step_id>/retry", methods=["POST"])
    def api_task_retry_step(task_id, step_id):
        from flask import request, jsonify
        ws_id = request.args.get("workspace_id", "")
        if not ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400
        try:
            from agent.runtime.durable.control import retry_step
            result = retry_step(task_id, step_id, ws_id)
            code = 200 if result["ok"] else (404 if "not found" in result.get("error","") else 400)
            return jsonify(result), code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500
