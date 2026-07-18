"""Network Assurance HTTP contracts."""

from __future__ import annotations

import logging

from flask import jsonify, request

from agent.modules.assurance import service
from workspace.ids import validate_workspace_id


_LOG = logging.getLogger(__name__)


def _workspace(raw: str):
    try:
        return validate_workspace_id(raw), None
    except (TypeError, ValueError):
        return None, (jsonify({"ok": False, "error": "invalid_workspace_id"}), 400)


def _data():
    if not request.is_json:
        return None, (jsonify({"ok": False, "error": "expected_application_json"}), 415)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, (jsonify({"ok": False, "error": "body_must_be_object"}), 400)
    return value, None


def _failure(exc: Exception):
    if isinstance(exc, (ValueError, TypeError)):
        message = str(exc) or "invalid_request"
        status = 404 if message.endswith("_not_found") else 409 if "not_ready" in message else 400
        return jsonify({"ok": False, "error": message}), status
    _LOG.exception("network assurance API failed")
    return jsonify({"ok": False, "error": "assurance_internal_error"}), 500


def _read(call, field: str):
    try:
        return jsonify({"ok": True, field: call()})
    except Exception as exc:
        return _failure(exc)


def _string_list(value, field: str):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field}_must_be_string_array")
    return value


def register_assurance_routes(app):
    @app.post("/api/assurance/records/clear")
    def assurance_records_clear():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        if data.get("confirm") is not True:
            return jsonify({
                "ok": False,
                "error": "confirm_required",
                "message": "Set confirm=true to clear assurance records.",
            }), 400
        try:
            result = service.clear_assurance_records(ws, confirm=True)
        except Exception as exc:
            return _failure(exc)
        return jsonify({"ok": True, **result})

    @app.get("/api/assurance/overview")
    def assurance_overview():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.get_overview(ws), "overview")

    @app.get("/api/assurance/snapshot")
    def assurance_snapshot():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.get_snapshot(ws), "snapshot")

    @app.get("/api/assurance/baselines")
    def assurance_baselines_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_baselines(ws), "items")

    @app.post("/api/assurance/baselines")
    def assurance_baselines_create():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try:
            operation = service.start_assurance_operation(
                ws, "baseline_capture", scope=data.get("scope"),
                baseline_name=str(data.get("name", "")),
            )
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "operation": operation}), 202

    @app.get("/api/assurance/drifts")
    def assurance_drifts():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_drifts(ws, request.args.get("baseline_id", "")), "items")

    @app.get("/api/assurance/topology")
    def assurance_topology():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.get_topology(ws), "topology")

    @app.post("/api/assurance/topology/build")
    def assurance_topology_build():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: operation = service.start_assurance_operation(ws, "topology_refresh")
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "operation": operation}), 202

    @app.post("/api/assurance/fault-propagation")
    def assurance_fault_propagation():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: operation = service.start_assurance_operation(
            ws, "fault_propagation", ref_id=str(data.get("drift_id", "")),
            asset_ids=_string_list(data.get("asset_ids", []), "asset_ids"),
            scope={"limit": int(data.get("limit", 200))},
            depth=int(data.get("depth", 2)),
            source_mode=str(data.get("source_mode", "hypothetical")),
        )
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "operation": operation}), 202

    @app.get("/api/assurance/operations")
    def assurance_operations_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_assurance_operations(ws, request.args.get("kind", "")), "items")

    @app.get("/api/assurance/operations/<operation_id>")
    def assurance_operation_get(operation_id: str):
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.get_assurance_operation(ws, operation_id), "operation")

    @app.get("/api/assurance/incidents")
    def assurance_incidents_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_incidents(ws), "items")

    @app.post("/api/assurance/incidents")
    def assurance_incidents_create():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.create_incident(ws, data.get("title", ""), data.get("symptom", ""), data.get("scope"), data.get("drift_id", ""))
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "incident": item}), 202

    @app.patch("/api/assurance/incidents/<incident_id>")
    def assurance_incidents_update(incident_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.pop("workspace_id", ""))
        if err: return err
        try: item = service.update_incident(ws, incident_id, data)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "incident": item})

    @app.get("/api/assurance/changes")
    def assurance_changes_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_change_plans(ws), "items")

    @app.post("/api/assurance/changes")
    def assurance_changes_create():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.create_change_plan(
            ws, data.get("title", ""), data.get("summary", ""),
            _string_list(data.get("asset_ids"), "asset_ids"),
            expected_changes=data.get("expected_changes"), invariants=data.get("invariants"),
        )
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "change": item}), 201

    @app.post("/api/assurance/changes/<change_id>/validate")
    def assurance_changes_validate(change_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.start_change_precheck(ws, change_id)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, **item}), 202

    @app.post("/api/assurance/changes/<change_id>/postcheck")
    def assurance_changes_postcheck(change_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.start_change_postcheck(ws, change_id)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, **item}), 202

    @app.patch("/api/assurance/changes/<change_id>")
    def assurance_changes_update(change_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.pop("workspace_id", ""))
        if err: return err
        try: item = service.update_change_plan(ws, change_id, data)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "change": item})

    @app.get("/api/assurance/schedules")
    def assurance_schedules_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_schedules(ws), "items")

    @app.get("/api/assurance/alarms")
    def assurance_alarms_list():
        ws, err = _workspace(request.args.get("workspace_id", ""))
        if err: return err
        return _read(lambda: service.list_alarms(ws, request.args.get("state", "")), "items")

    @app.post("/api/assurance/schedules")
    def assurance_schedules_create():
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.create_schedule(
            ws, data.get("name", ""), data.get("baseline_id", ""),
            int(data.get("interval_minutes", 60)), data.get("scope"),
            int(data.get("confirm_after", 2)), int(data.get("recover_after", 2)),
        )
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "schedule": item}), 201

    @app.patch("/api/assurance/schedules/<schedule_id>")
    def assurance_schedules_update(schedule_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.pop("workspace_id", ""))
        if err: return err
        try: item = service.update_schedule(ws, schedule_id, data)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "schedule": item})

    @app.post("/api/assurance/schedules/<schedule_id>/run")
    def assurance_schedules_run(schedule_id):
        data, err = _data()
        if err: return err
        ws, err = _workspace(data.get("workspace_id", ""))
        if err: return err
        try: item = service.run_schedule_now(ws, schedule_id)
        except Exception as exc: return _failure(exc)
        return jsonify({"ok": True, "schedule": item}), 202

    service.start_scheduler()
