# backend/api/runtime_routes.py
"""Runtime routes — diagnostics, selfcheck, retention, archive, tool invocation."""

import json
import os
import uuid
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from flask import jsonify, request

from workspace.ids import validate_workspace_id


# ── In-memory state for execution history and approvals ──
_TOOL_HISTORY_MAX = 200
_tool_exec_history = OrderedDict()
_tool_pending_approvals = OrderedDict()
_lock = threading.Lock()

_HISTORY_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tool_history.json')
_APPROVALS_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tool_approvals.json')


def _persist_history():
    with _lock:
        snapshot = list(_tool_exec_history.values())
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _persist_approvals():
    with _lock:
        snapshot = list(_tool_pending_approvals.values())
    try:
        os.makedirs(os.path.dirname(_APPROVALS_FILE), exist_ok=True)
        with open(_APPROVALS_FILE, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _load_persisted():
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE) as f:
                items = json.load(f) or []
            for item in items:
                _tool_exec_history[item.get('invocation_id', '')] = item
    except Exception:
        pass
    try:
        if os.path.exists(_APPROVALS_FILE):
            with open(_APPROVALS_FILE) as f:
                items = json.load(f) or []
            for item in items:
                if item.get('status') == 'pending':
                    _tool_pending_approvals[item.get('approval_id', '')] = item
    except Exception:
        pass


_load_persisted()


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def _get_tool_risk_level(client, tool_id: str) -> str:
    """Get risk level for a tool_id from the registry."""
    try:
        spec = client._registry.get_tool(tool_id)
        return spec.risk_level if spec else "unknown"
    except Exception:
        return "unknown"


def _safe_output(output: dict) -> dict:
    """Return a sanitized version of tool output for API responses."""
    if not output:
        return {}
    safe = {}
    for k, v in output.items():
        if isinstance(v, str) and len(v) > 2000:
            safe[k] = v[:2000] + "... [truncated]"
        elif isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False)
            if len(s) > 2000:
                safe[k] = s[:2000] + '..." [truncated]'
            else:
                safe[k] = v
        else:
            safe[k] = v
    return safe


def register_runtime_routes(app):
    """Register all runtime API routes on the Flask app."""

    @app.route("/api/runtime/health")
    def api_runtime_health():
        from runtime.diagnostics import get_diagnostics
        from workspace.ids import validate_workspace_id
        ws_id = request.args.get("workspace_id", "default")
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            ws_id = "default"
        report = get_diagnostics(ws_id)
        return jsonify(report.as_dict())

    @app.route("/api/runtime/selfcheck")
    def api_runtime_selfcheck():
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.selfcheck import run_selfcheck
        result = run_selfcheck(ws_id)
        return jsonify(result.as_dict())

    @app.route("/api/tools/catalog")
    def api_tools_catalog():
        """Return read-only tool catalog — metadata only, no invoke capability."""
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()
        return jsonify({"tools": tools, "count": len(tools),
                        "note": "Read-only catalog. High-risk tools require approval."})

    # ── Tool Invocation ──
    @app.route("/api/tools/invoke", methods=["POST"])
    def api_tools_invoke():
        """Invoke a tool through the full safety pipeline."""
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err

        body = request.get_json(silent=True) or {}
        tool_id = body.get("tool_id", "")
        arguments = body.get("arguments", {})
        dry_run = body.get("dry_run", False)
        approval_id = body.get("approval_id", None)

        if not tool_id:
            return jsonify({"ok": False, "error": "tool_id is required"}), 400

        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.schemas import ToolInvocation

        client = get_default_tool_runtime_client()

        # Build invocation with approval_id
        invocation = ToolInvocation(
            tool_id=tool_id,
            arguments=arguments,
            workspace_id=ws_id,
            dry_run=dry_run,
            requested_by="ui:tool_catalog",
            approval_id=approval_id,
        )

        # Run through executor directly (policy check included)
        result = client._executor.execute(invocation)

        # Record history
        hist_entry = result.as_dict()
        hist_entry["workspace_id"] = ws_id
        hist_entry["dry_run"] = dry_run
        hist_entry["risk_level"] = _get_tool_risk_level(client, tool_id)

        with _lock:
            _tool_exec_history[result.invocation_id] = hist_entry
            while len(_tool_exec_history) > _TOOL_HISTORY_MAX:
                _tool_exec_history.popitem(last=False)
        _persist_history()

        return jsonify({
            "ok": result.status in ("succeeded", "dry_run"),
            "invocation_id": result.invocation_id,
            "tool_id": result.tool_id,
            "status": result.status,
            "summary": result.summary[:500],
            "output": _safe_output(result.output),
            "duration_ms": result.duration_ms,
            "redacted": result.redacted,
            "policy_decision": result.policy_decision.__dict__ if result.policy_decision else None,
            "errors": result.errors[:20],
            "warnings": result.warnings[:20],
        })

    @app.route("/api/tools/dry-run", methods=["POST"])
    def api_tools_dry_run():
        """Preview a tool invocation without executing it."""
        body = request.get_json(silent=True) or {}
        tool_id = body.get("tool_id", "")
        arguments = body.get("arguments", {})

        if not tool_id:
            return jsonify({"ok": False, "error": "tool_id is required"}), 400

        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        spec = client._registry.get_tool(tool_id)
        if not spec:
            return jsonify({"ok": False, "error": "tool not found"}), 404

        if not spec.dry_run_supported:
            return jsonify({"ok": False, "error": "dry_run not supported for this tool"}), 400

        return jsonify({
            "ok": True,
            "dry_run": True,
            "tool_id": tool_id,
            "risk_level": spec.risk_level,
            "requires_approval": spec.requires_approval,
            "params": list(arguments.keys()),
            "would_do": f"Would invoke {tool_id} with {len(arguments)} argument(s)",
            "note": "This is a preview. The tool will NOT be executed.",
        })

    # ── Execution History ──
    @app.route("/api/tools/history")
    def api_tools_history():
        """Return execution history for the current workspace."""
        ws_id = request.args.get("workspace_id", "default")
        status_filter = request.args.get("status", None)
        limit = int(request.args.get("limit", 50))

        with _lock:
            all_records = list(_tool_exec_history.values())

        # Filter by workspace
        records = [r for r in all_records if r.get("workspace_id", "") == ws_id]
        if status_filter:
            records = [r for r in records if r.get("status", "") == status_filter]
        # Latest first
        records = list(reversed(records))[:limit]

        return jsonify({
            "records": records,
            "count": len(records),
            "workspace_id": ws_id,
        })

    # ── Approvals ──
    @app.route("/api/tools/approvals")
    def api_tools_approvals():
        """Return pending approval requests."""
        ws_id = request.args.get("workspace_id", "default")

        with _lock:
            all_pending = list(_tool_pending_approvals.values())

        records = [r for r in all_pending if r.get("workspace_id", "") == ws_id]
        return jsonify({
            "approvals": records,
            "count": len(records),
            "workspace_id": ws_id,
        })

    @app.route("/api/tools/approvals/<approval_id>/approve", methods=["PUT"])
    def api_tools_approve(approval_id):
        """Approve a pending tool approval."""
        with _lock:
            approval = _tool_pending_approvals.get(approval_id)
            if not approval:
                return jsonify({"ok": False, "error": "approval not found"}), 404
            approval["status"] = "approved"
            approval["resolved_at"] = datetime.now(timezone.utc).isoformat()
            del _tool_pending_approvals[approval_id]
        _persist_approvals()

        return jsonify({"ok": True, "approval_id": approval_id, "status": "approved",
                        "note": "Approved. The tool can now be invoked with this approval_id."})

    @app.route("/api/tools/approvals/<approval_id>/reject", methods=["PUT"])
    def api_tools_reject(approval_id):
        """Reject a pending tool approval."""
        with _lock:
            approval = _tool_pending_approvals.get(approval_id)
            if not approval:
                return jsonify({"ok": False, "error": "approval not found"}), 404
            approval["status"] = "rejected"
            approval["resolved_at"] = datetime.now(timezone.utc).isoformat()
            del _tool_pending_approvals[approval_id]
        _persist_approvals()

        return jsonify({"ok": True, "approval_id": approval_id, "status": "rejected"})

    @app.route("/api/tools/approvals", methods=["POST"])
    def api_tools_request_approval():
        """Request approval for a high-risk tool."""
        body = request.get_json(silent=True) or {}
        tool_id = body.get("tool_id", "")
        reason = body.get("reason", "")
        ws_id = body.get("workspace_id", "default")
        user = body.get("user", "ui_user")

        if not tool_id or not reason:
            return jsonify({"ok": False, "error": "tool_id and reason are required"}), 400

        approval_id = "APR-" + uuid.uuid4().hex[:8].upper()
        entry = {
            "approval_id": approval_id,
            "tool_id": tool_id,
            "reason": reason,
            "workspace_id": ws_id,
            "user": user,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with _lock:
            _tool_pending_approvals[approval_id] = entry
        _persist_approvals()

        return jsonify({"ok": True, "approval_id": approval_id, "status": "pending",
                        "note": "Approval request submitted. Waiting for admin confirmation."})

    # ── Permissions ──
    @app.route("/api/tools/permissions")
    def api_tools_permissions():
        """Get workspace-level tool permissions."""
        ws_id = request.args.get("workspace_id", "default")
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400

        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()

        permissions = {
            "workspace_id": ws_id,
            "tools": [],
            "forbidden_count": 0,
            "high_risk_count": 0,
            "approval_required_count": 0,
        }
        for t in tools:
            perm = {
                "tool_id": t["tool_id"],
                "enabled": t.get("enabled", True),
                "risk_level": t.get("risk_level", "low"),
                "requires_approval": t.get("requires_approval", False),
            }
            permissions["tools"].append(perm)
            if t.get("risk_level") == "forbidden":
                permissions["forbidden_count"] += 1
            if t.get("risk_level") == "high":
                permissions["high_risk_count"] += 1
            if t.get("requires_approval"):
                permissions["approval_required_count"] += 1

        return jsonify(permissions)

    @app.route("/api/workspaces/<ws_id>/selfcheck")
    def api_workspace_selfcheck(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.selfcheck import run_selfcheck
        result = run_selfcheck(ws_id)
        return jsonify(result.as_dict())

    # ── Retention ──
    @app.route("/api/workspaces/<ws_id>/retention/preview")
    def api_workspace_retention_preview(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.retention import preview_retention, default_retention_policy
        preview = preview_retention(ws_id, default_retention_policy())
        return jsonify(preview.as_dict())

    @app.route("/api/workspaces/<ws_id>/retention/apply", methods=["POST"])
    def api_workspace_retention_apply(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        dry_run = request.json.get("dry_run", True) if request.is_json else True
        confirm = request.json.get("confirm", False) if request.is_json else False
        from runtime.retention import apply_retention, default_retention_policy
        preview = apply_retention(ws_id, default_retention_policy(),
                                  dry_run=dry_run, confirm=confirm)
        return jsonify(preview.as_dict())

    @app.route("/api/workspaces/<ws_id>/retention/audits")
    def api_workspace_retention_audits(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.retention import get_audits
        audits = get_audits(ws_id)
        return jsonify({"audits": audits})

    @app.route("/api/workspaces/<ws_id>/retention/audits/<audit_id>")
    def api_workspace_retention_audit(ws_id, audit_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.retention import get_audit
        audit = get_audit(ws_id, audit_id)
        if not audit:
            return jsonify({"ok": False, "error": "audit not found"}), 404
        return jsonify(audit)

    # ── Archive ──
    @app.route("/api/workspaces/<ws_id>/archive/preview")
    def api_archive_preview(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.archive import preview_archive_candidates, default_archive_policy
        preview = preview_archive_candidates(ws_id, default_archive_policy())
        return jsonify(preview.as_dict())

    @app.route("/api/workspaces/<ws_id>/archive/apply", methods=["POST"])
    def api_archive_apply(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        dry_run = request.json.get("dry_run", True) if request.is_json else True
        confirm = request.json.get("confirm", False) if request.is_json else False
        from runtime.archive import apply_archive, default_archive_policy
        result = apply_archive(ws_id, default_archive_policy(),
                               dry_run=dry_run, confirm=confirm)
        return jsonify(result.as_dict())

    @app.route("/api/workspaces/<ws_id>/archive/audits")
    def api_archive_audits(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.archive import get_archive_audits
        audits = get_archive_audits(ws_id)
        return jsonify({"audits": audits})

    @app.route("/api/workspaces/<ws_id>/archive/audits/<audit_id>")
    def api_archive_audit(ws_id, audit_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from runtime.archive import get_archive_audit
        audit = get_archive_audit(ws_id, audit_id)
        if not audit:
            return jsonify({"ok": False, "error": "audit not found"}), 404
        return jsonify(audit)
