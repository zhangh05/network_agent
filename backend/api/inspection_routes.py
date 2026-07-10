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
    GET  /api/inspection/profiles         — list built-in inspection profiles
    GET  /api/inspection/scripts          — get vendor command scripts
    PUT  /api/inspection/scripts/<vendor> — update vendor commands
    POST /api/inspection/scripts/<vendor>/upload — upload .txt script file
    DELETE /api/inspection/scripts/<vendor> — reset vendor to defaults
"""

from __future__ import annotations

from flask import Response, jsonify, request

from workspace.ids import validate_workspace_id

from agent.modules.inspection import service as inspection_service
from agent.modules.inspection.profiles import (
    VENDOR_COMMAND_PROFILES,
    load_vendor_commands,
    save_vendor_commands,
    delete_vendor_commands,
    upload_vendor_script_file,
    is_read_only_command,
)


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw=""):
    """Return ``(workspace_id, error_response)``.

    ``raw`` may be ``None`` (Flask's request.args.get default with a
    missing key returns ``None``), an empty string, or a non-empty
    string. Empty / None map to the same 400 so callers can rely on
    the explicit error instead of an unexpected attribute access.
    """
    if raw is None:
        return None, _invalid_ws()
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def _task_create_status(task) -> int:
    err = getattr(task, "error", "") or ""
    if getattr(task, "status", "") == "failed":
        if err.startswith("unknown_profile") or err == "no_assets_matched_scope":
            return 422
        if err.startswith("runner_internal"):
            return 500
        return 400
    return 200


def _cancel_status(result: dict) -> int:
    if result.get("ok"):
        return 200
    err = str(result.get("error", "") or "")
    if err == "task_not_found":
        return 404
    if err.startswith("task_already_"):
        return 409
    if result.get("supported") is False:
        return 501
    return 400


def register_inspection_routes(app):
    """Register all inspection routes on the given Flask app."""

    @app.route("/api/inspection/tasks", methods=["POST"])
    def api_inspection_tasks_create():
        # v3.10: explicitly fail on a non-JSON body. The previous
        # ``request.get_json(silent=True) or {}`` accepted a missing
        # or non-JSON body silently, letting a form-urlencoded
        # payload produce a "successful" task_create with no scope
        # — silent failure.
        if not request.is_json:
            return jsonify({"ok": False, "error": "expected_application_json"}), 415
        data = request.get_json(silent=False) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        scope = data.get("scope") or {}
        if not isinstance(scope, dict):
            return jsonify({"ok": False, "error": "scope_must_be_object"}), 400
        # Require at least one target dimension — prevent accidental full-CMDB scans.
        if not scope.get("region") and not scope.get("asset_ids"):
            return jsonify({
                "ok": False,
                "error": "scope_required",
                "message": "巡检任务必须指定范围（region 或 asset_ids），不能对全量 CMDB 发起巡检。",
            }), 400

        # The runner persists / runs synchronously. The frontend polls
        # get once this returns. Status is one of:
        #   pending → running → succeeded | failed | partial
        # v3.9.14 — clamp to the same range the service layer enforces
        # so callers see consistent behaviour regardless of which
        # entry point (HTTP API, service call, or tool) we use.
        try:
            mc = int(data.get("max_concurrency", 3) or 3)
        except (TypeError, ValueError):
            mc = 3
        if mc < 1:
            mc = 1
        if mc > 16:
            mc = 16

        # v3.10: when the caller passes ``async_run=true`` the route
        # fires the task off on a daemon thread and returns
        # immediately with status=pending. Without this a fleet of
        # 50 devices blocks the HTTP request for 90+ seconds and
        # nginx / curl timeouts become the operator's main
        # complaint.
        async_run = bool(data.get("async_run", False))
        if async_run:
            pending = inspection_service.start_background_task(
                workspace_id=ws_id,
                profile_id=str(data.get("profile_id", "") or ""),
                scope=scope,
                created_by=str(data.get("created_by", "user") or "user"),
                session_id=str(data.get("session_id", "") or ""),
                max_concurrency=mc,
            )
            status_code = _task_create_status(pending)
            if status_code != 200:
                return jsonify({
                    "ok": False,
                    "task_id": pending.task_id,
                    "status": pending.status,
                    "error": pending.error,
                    "async_run": True,
                }), status_code
            return jsonify({
                "ok": True,
                "task_id": pending.task_id,
                "status": pending.status,
                "async_run": True,
                "tracking": pending.tracking,
                "note": "task running in background; poll /api/inspection/tasks/<task_id>",
            }), 202

        task = inspection_service.create_task(
            workspace_id=ws_id,
            profile_id=str(data.get("profile_id", "") or ""),
            scope=scope,
            created_by=str(data.get("created_by", "user") or "user"),
            session_id=str(data.get("session_id", "") or ""),
            max_concurrency=mc,
        )

        # v3.10: distinguish "could not start" (422) from "ran but
        # failed" (200 with status="failed"). unknown_profile and
        # no_assets_matched_scope are caller errors (422); a run
        # that completed with some devices down is just a 200.
        status_code = _task_create_status(task)
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
                "partial_devices": task.partial,
                "findings_total": task.warnings + task.criticals + task.infos,
                "findings_critical": task.criticals,
                "findings_warning": task.warnings,
                "findings_info": task.infos,
            },
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "tracking": task.tracking,
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
        return jsonify(result), _cancel_status(result)

    @app.route("/api/inspection/tasks/<task_id>/report", methods=["GET"])
    def api_inspection_tasks_report(task_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        # v3.10: format normalisation moved to the service layer
        # so HTTP and tool callers see the same 400 shape.
        fmt = request.args.get("format", "md") or "md"
        result = inspection_service.render_report(ws_id, task_id, fmt)
        if not result.get("ok"):
            err = result.get("error", "")
            if err == "task_not_found":
                status_code = 404
            elif err.startswith("unsupported_format"):
                status_code = 400
            else:
                status_code = 400
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

    # ── script management ──────────────────────────────────────────

    @app.route("/api/inspection/profiles", methods=["GET"])
    def api_inspection_profiles():
        """List built-in inspection profiles."""
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        profiles = inspection_service.list_profiles()
        return jsonify({"ok": True, "profiles": profiles})

    @app.route("/api/inspection/scripts", methods=["GET"])
    def api_inspection_scripts_get():
        """Get vendor command scripts (with override status)."""
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        vendor = (request.args.get("vendor") or "").strip()
        script_type = (request.args.get("script_type") or "general").strip()
        if script_type not in ("general", "log"):
            return jsonify({"ok": False, "error": "invalid_script_type", "expected": "general|log"}), 400
        if not vendor:
            # Return a summary of all vendors (built-in keys)
            vendors: list[dict] = []
            for vkey, vp in VENDOR_COMMAND_PROFILES.items():
                overrides = load_vendor_commands(ws_id, vkey, script_type=script_type)
                vendors.append({
                    "vendor": vkey,
                    "source": "file" if overrides else "builtin",
                    "command_count": len(overrides.get("commands", [])) if overrides else 0,
                    "override_count": len(overrides.get("commands", [])) if overrides else 0,
                    "has_pre_commands": bool(
                        overrides.get("pre_commands") if overrides.get("pre_commands") is not None else vp.pre_commands
                    ) if overrides else bool(vp.pre_commands),
                    "has_post_commands": bool(
                        overrides.get("post_commands") if overrides.get("post_commands") is not None else vp.post_commands
                    ) if overrides else bool(vp.post_commands),
                })
            return jsonify({"ok": True, "vendors": vendors})

        vkey = vendor.lower().replace(" ", "_")
        builtin = VENDOR_COMMAND_PROFILES.get(vkey)
        if builtin is None:
            return jsonify({"ok": False, "error": "unknown_vendor",
                            "available": sorted(VENDOR_COMMAND_PROFILES.keys())}), 404

        overrides = load_vendor_commands(ws_id, vkey, script_type=script_type)
        # v4.1: built-in commands are empty — scripts come from workspace overrides
        effective_commands = list(overrides.get("commands", [])) if overrides else []
        if overrides:
            pre = overrides.get("pre_commands")
            effective_pre = list(pre if pre is not None else (builtin.pre_commands or []))
            post = overrides.get("post_commands")
            effective_post = list(post if post is not None else (builtin.post_commands or []))
        else:
            effective_pre = list(builtin.pre_commands) if builtin.pre_commands else []
            effective_post = list(builtin.post_commands) if builtin.post_commands else []

        return jsonify({
            "ok": True,
            "vendor": vkey,
            "source": "file" if overrides else "builtin",
            "commands": effective_commands,
            "builtin_commands": [],  # v4.1: no built-in commands
            "pre_commands": effective_pre,
            "post_commands": effective_post,
        })

    @app.route("/api/inspection/scripts/<vendor>", methods=["PUT"])
    def api_inspection_scripts_update(vendor):
        """Update vendor command overrides (JSON body)."""
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        vkey = (vendor or "").strip().lower().replace(" ", "_")
        builtin = VENDOR_COMMAND_PROFILES.get(vkey)
        if builtin is None:
            return jsonify({"ok": False, "error": "unknown_vendor",
                            "available": sorted(VENDOR_COMMAND_PROFILES.keys())}), 404

        script_type = (data.get("script_type") or "general").strip()
        if script_type not in ("general", "log"):
            return jsonify({"ok": False, "error": "invalid_script_type", "expected": "general|log"}), 400

        commands: list[str] = data.get("commands", [])
        if not isinstance(commands, list):
            return jsonify({"ok": False, "error": "commands_must_be_list"}), 400

        pre_commands: list[str] = data.get("pre_commands", [])
        if not isinstance(pre_commands, list):
            pre_commands = []
        post_commands: list[str] = data.get("post_commands", [])
        if not isinstance(post_commands, list):
            post_commands = []

        # v3.11: reasonable upper bound to prevent accidental DoS
        MAX_COMMANDS = 150
        if len(commands) > MAX_COMMANDS:
            return jsonify({"ok": False, "error": f"too_many_commands: max {MAX_COMMANDS}"}), 400
        if len(pre_commands) > 20:
            return jsonify({"ok": False, "error": "too_many_pre_commands: max 20"}), 400
        if len(post_commands) > 20:
            return jsonify({"ok": False, "error": "too_many_post_commands: max 20"}), 400

        # Validate: all inspection commands must be non-empty strings and read-only.
        # Enter is an explicit __ENTER__ action in pre/post, not an empty string.
        for cmd in commands:
            if not isinstance(cmd, str) or not cmd.strip():
                return jsonify({"ok": False, "error": "commands_must_be_non_empty_strings"}), 400
        for cmd in commands:
            if not is_read_only_command(cmd):
                return jsonify({"ok": False, "error": f"blocked_write_command: {cmd[:80]}"}), 400
        for cmd in pre_commands + post_commands:
            if not isinstance(cmd, str) or not cmd.strip():
                return jsonify({"ok": False, "error": "pre_post_commands_must_be_non_empty_strings"}), 400
        # pre/post commands can include explicit __ENTER__ actions and otherwise must be read-only.
        for cmd in pre_commands + post_commands:
            if not is_read_only_command(cmd):
                return jsonify({"ok": False, "error": f"blocked_write_command: {cmd[:80]}"}), 400

        success = save_vendor_commands(
            ws_id, vkey, commands, script_type=script_type,
            pre_commands=pre_commands, post_commands=post_commands,
        )
        return jsonify({"ok": success, "vendor": vkey,
                        "command_count": len(commands),
                        "pre_command_count": len(pre_commands),
                        "post_command_count": len(post_commands)})

    @app.route("/api/inspection/scripts/<vendor>/upload", methods=["POST"])
    def api_inspection_scripts_upload(vendor):
        """Upload a raw .txt script file for a vendor."""
        # Accept workspace_id from JSON body, form data, or query string
        ws_id_raw = ""
        if request.is_json:
            ws_id_raw = (request.get_json(silent=True) or {}).get("workspace_id", "")
        if not ws_id_raw:
            ws_id_raw = request.form.get("workspace_id", "") or request.args.get("workspace_id", "")
        ws_id_v, err = _validated_ws_id(ws_id_raw)
        if err:
            return err

        vkey = (vendor or "").strip().lower().replace(" ", "_")
        builtin = VENDOR_COMMAND_PROFILES.get(vkey)
        if builtin is None:
            return jsonify({"ok": False, "error": "unknown_vendor",
                            "available": sorted(VENDOR_COMMAND_PROFILES.keys())}), 404

        # script_type from body, form, or query
        script_type = ""
        if request.is_json:
            script_type = (request.get_json(silent=True) or {}).get("script_type", "")
        if not script_type:
            script_type = request.form.get("script_type", "") or request.args.get("script_type", "")
        script_type = (script_type or "general").strip()
        if script_type not in ("general", "log"):
            return jsonify({"ok": False, "error": "invalid_script_type", "expected": "general|log"}), 400

        # Accept either a file upload or raw text body
        if "file" in request.files:
            f = request.files["file"]
            content = f.read().decode("utf-8", errors="replace")
        else:
            if request.is_json:
                content = (request.get_json(silent=True) or {}).get("content", "")
            else:
                content = (request.get_data(as_text=True) or "").strip()

        if not content:
            return jsonify({"ok": False, "error": "empty_content"}), 400

        # v3.11: cap upload size (50 KB ≈ 500+ commands)
        MAX_UPLOAD_CHARS = 50_000
        if len(content) > MAX_UPLOAD_CHARS:
            return jsonify({"ok": False, "error": f"content_too_large: max {MAX_UPLOAD_CHARS} chars"}), 400

        # Parse lines from the content first so we can validate
        lines: list[str] = []
        for raw in str(content).splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            lines.append(line)
        if not lines:
            return jsonify({"ok": False, "error": "no_valid_commands"}), 400

        # Safety: every command must pass the read-only gate
        from agent.modules.inspection.profiles import is_read_only_command
        blocked: list[str] = []
        for cmd in lines:
            if not is_read_only_command(cmd):
                blocked.append(cmd[:80])
        if blocked:
            return jsonify({
                "ok": False,
                "error": f"blocked_write_commands: {len(blocked)} command(s) rejected",
                "blocked": blocked,
            }), 400

        success = upload_vendor_script_file(ws_id_v, vkey, content, script_type=script_type)
        if not success:
            return jsonify({"ok": False, "error": "save_failed"}), 500

        return jsonify({"ok": True, "vendor": vkey,
                        "note": "script uploaded; will take effect on next inspection"})

    @app.route("/api/inspection/scripts/<vendor>", methods=["DELETE"])
    def api_inspection_scripts_delete(vendor):
        """Reset vendor to built-in defaults."""
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        vkey = (vendor or "").strip().lower().replace(" ", "_")
        if vkey not in VENDOR_COMMAND_PROFILES:
            return jsonify({"ok": False, "error": "unknown_vendor"}), 404
        script_type = (request.args.get("script_type") or "general").strip()
        if script_type not in ("general", "log"):
            return jsonify({"ok": False, "error": "invalid_script_type", "expected": "general|log"}), 400
        success = delete_vendor_commands(ws_id, vkey, script_type=script_type)
        return jsonify({"ok": success, "vendor": vkey,
                        "note": "reset to defaults"})
