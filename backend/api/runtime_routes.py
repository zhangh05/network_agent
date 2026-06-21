# backend/api/runtime_routes.py
"""Runtime routes — diagnostics, selfcheck, retention, archive, tool invocation."""

import json
import os
import uuid
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from workspace.ids import validate_workspace_id


# ── In-memory state for execution history and approvals ──
_TOOL_HISTORY_MAX = 200
_tool_exec_history = OrderedDict()
_tool_approvals = OrderedDict()
_lock = threading.Lock()

_HISTORY_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'tool_history.json'
_APPROVALS_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'tool_approvals.json'


def _persist_history():
    # v5.0.0: write through workspace.atomic_io for crash-safe persistence
    # (was a non-atomic open(...).write(...), which could leave the JSON
    # half-written if the process was killed mid-flush).
    with _lock:
        snapshot = list(_tool_exec_history.values())
    try:
        from workspace.atomic_io import atomic_write_json
        atomic_write_json(_HISTORY_FILE, snapshot, indent=2)
    except Exception:
        pass


def _persist_approvals():
    with _lock:
        snapshot = list(_tool_approvals.values())
    try:
        from workspace.atomic_io import atomic_write_json
        atomic_write_json(_APPROVALS_FILE, snapshot, indent=2)
    except Exception:
        pass


def _load_persisted():
    from workspace.atomic_io import safe_read_json
    items = safe_read_json(_HISTORY_FILE, default=[]) or []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _tool_exec_history[item.get('invocation_id', '')] = item
    items = safe_read_json(_APPROVALS_FILE, default=[]) or []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                approval_id = item.get('approval_id', '')
                if approval_id:
                    _tool_approvals[approval_id] = item


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


def _requires_runtime_approval(spec) -> bool:
    return bool(spec and (spec.risk_level == "high" or spec.requires_approval))


def _validate_approved_tool_invocation(approval_id: str, tool_id: str, workspace_id: str) -> bool:
    """Return True only for an approved ID that matches tool and workspace."""
    if not approval_id:
        return False
    with _lock:
        approval = dict(_tool_approvals.get(approval_id, {}))
    return (
        approval.get("status") == "approved"
        and approval.get("tool_id") == tool_id
        and approval.get("workspace_id") == workspace_id
    )


def _blocked_tool_response(invocation, ws_id: str, risk_level: str, reason: str):
    """Return and persist a blocked tool invocation without reaching a handler."""
    hist_entry = {
        "invocation_id": invocation.invocation_id,
        "tool_id": invocation.tool_id,
        "status": "blocked",
        "summary": reason,
        "artifact_ids": [],
        "warnings": [],
        "errors": [reason],
        "duration_ms": 0,
        "redacted": True,
        "policy_decision": {
            "allowed": False,
            "reason": reason,
            "risk_level": risk_level,
            "blocked_rules": ["approval_state"],
            "requires_approval": True,
        },
        "created_at": invocation.created_at,
        "workspace_id": ws_id,
        "dry_run": invocation.dry_run,
        "risk_level": risk_level,
    }
    with _lock:
        _tool_exec_history[invocation.invocation_id] = hist_entry
        while len(_tool_exec_history) > _TOOL_HISTORY_MAX:
            _tool_exec_history.popitem(last=False)
    _persist_history()

    return jsonify({
        "ok": False,
        "invocation_id": invocation.invocation_id,
        "tool_id": invocation.tool_id,
        "status": "blocked",
        "summary": reason,
        "output": {},
        "duration_ms": 0,
        "redacted": True,
        "policy_decision": hist_entry["policy_decision"],
        "errors": [reason],
        "warnings": [],
    })


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

    @app.route("/api/runtime/summary")
    def api_runtime_summary():
        """Return safe runtime counts used by the workbench status UI."""
        from agent.runtime.services import default_runtime_services

        services = default_runtime_services()
        caps = services.capability_registry.list_all()
        cap_counts = {
            "total": len(caps),
            "enabled": len([c for c in caps if c.status == "enabled"]),
            "planned": len([c for c in caps if c.status == "planned"]),
            "disabled": len([c for c in caps if c.status == "disabled"]),
        }

        registry = services.tool_service.registry
        all_tools = registry.list_all()
        visible_tools = registry.list_model_visible()
        hidden_or_non_llm = [
            t.tool_id
            for t in all_tools
            if (not t.enabled) or t.forbidden or (not t.callable_by_llm)
        ]

        return jsonify({
            "capabilities": cap_counts,
            "tools": {
                "registered": len(all_tools),
                "model_visible": len(visible_tools),
                "hidden_or_non_llm": hidden_or_non_llm,
            },
        })

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
        """Return read-only tool catalog — canonical IDs only."""
        from tool_runtime.catalog_snapshot import build_catalog_snapshot
        return jsonify(build_catalog_snapshot())

    # ── Tool Invocation ──
    @app.route("/api/tools/invoke", methods=["POST"])
    def api_tools_invoke():
        """Invoke a tool through the full safety pipeline. canonical ID only.

        v3.0 contract: the response is canonical-only. Only the
        following fields are emitted at the envelope level:
          ok, invocation_id, tool_id, canonical_tool_id,
          governance_status, status, summary, output, errors, warnings

        `status` is a normalized dispatch outcome:
          "succeeded" if the handler returned, "failed" if the
          dispatch raised.
        `output` echoes the raw handler payload verbatim; on
        failure it is `{}` and the error string lives in
        `errors[0]`.
        """
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err

        body = request.get_json(silent=True) or {}
        requested_tool_id = body.get("tool_id", "")
        arguments = body.get("arguments", {})
        dry_run = body.get("dry_run", False)
        approval_id = body.get("approval_id", None)

        if not requested_tool_id:
            return jsonify({"ok": False, "error": "tool_id is required"}), 400

        from tool_runtime.canonical_registry import (
            CANONICAL_REGISTRY, dispatch,
        )
        from tool_runtime.tool_governance import TOOL_GOVERNANCE
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.schemas import ToolInvocation

        if requested_tool_id not in CANONICAL_REGISTRY:
            return jsonify({
                "ok": False,
                "error": "unknown_tool_id",
                "message": "Only canonical tool_id is supported.",
            }), 400

        gov = TOOL_GOVERNANCE.get(requested_tool_id)
        if gov and gov.status == "forbidden":
            return jsonify({
                "ok": False,
                "error": "forbidden_tool_id",
                "message": gov.reason,
            }), 403

        client = get_default_tool_runtime_client()
        spec = None
        try:
            spec = client._registry.get_tool(requested_tool_id)
        except Exception:
            spec = None

        invocation = ToolInvocation(
            tool_id=requested_tool_id,
            arguments=arguments,
            workspace_id=ws_id,
            dry_run=dry_run,
            requested_by="ui:tool_catalog",
            approval_id=approval_id,
        )

        if _requires_runtime_approval(spec) and not _validate_approved_tool_invocation(approval_id, requested_tool_id, ws_id):
            return _blocked_tool_response(
                invocation, ws_id, _get_tool_risk_level(client, requested_tool_id),
                "invalid_or_unapproved_approval_id",
            )

        # v3.2.1: Enforce ToolPolicy.check() before dispatch. Without this
        # guard, _check_argument_safety (rm -rf, /etc/passwd, |, >, etc.)
        # and risk-level gating are bypassed.
        policy_decision = None
        try:
            policy_decision = client._policy.check(spec, invocation)
        except Exception as policy_exc:
            app.logger.warning(
                "policy_check_failed tool_id=%s err=%s",
                requested_tool_id, policy_exc,
            )
        if policy_decision is not None and not policy_decision.allowed:
            return _blocked_tool_response(
                invocation, ws_id,
                policy_decision.risk_level or _get_tool_risk_level(client, requested_tool_id),
                policy_decision.reason or "policy_blocked",
            )

        # Dispatch via canonical registry. `dispatch` returns the raw
        # handler dict. We only consume it as the new variables:
        # requested_tool_id, gov, result_payload, ok, error.
        try:
            result_payload = dispatch(requested_tool_id, **arguments)
            if not isinstance(result_payload, dict):
                result_payload = {"value": result_payload}
            ok = True
            error = ""
        except Exception as exc:
            result_payload = {}
            ok = False
            error = str(exc)[:200]

        governance_status = gov.status if gov else "active"
        if ok:
            status = "succeeded"
            summary = (result_payload.get("summary") or "").strip()[:500]
            if not summary:
                summary = f"Invoked {requested_tool_id}."
            output = _safe_output(result_payload)
            errors = []
            warnings = list(result_payload.get("warnings") or [])[:20]
        else:
            status = "failed"
            summary = error
            output = {}
            errors = [error] if error else ["tool_invocation_failed"]
            warnings = []

        return jsonify({
            "ok": ok,
            "invocation_id": invocation.invocation_id,
            "tool_id": requested_tool_id,
            "canonical_tool_id": requested_tool_id,
            "governance_status": governance_status,
            "status": status,
            "summary": summary,
            "output": output,
            "errors": errors,
            "warnings": warnings,
        })

    @app.route("/api/tools/dry-run", methods=["POST"])
    def api_tools_dry_run():
        """Preview a tool invocation without executing it. canonical ID only.

        v3.0 contract: only canonical tool_ids are accepted. The
        response envelope is canonical-only:
          ok, dry_run, tool_id, canonical_tool_id, governance_status,
          risk_level, requires_approval, params, would_do, note

        Unknown tool_ids return:
          ok=false, error="unknown_tool_id",
          message="Only canonical tool_id is supported."
        """
        body = request.get_json(silent=True) or {}
        requested_tool_id = body.get("tool_id", "")
        arguments = body.get("arguments", {})

        if not requested_tool_id:
            return jsonify({"ok": False, "error": "tool_id is required"}), 400

        from tool_runtime.canonical_registry import CANONICAL_REGISTRY
        from tool_runtime.tool_governance import TOOL_GOVERNANCE
        from tool_runtime.integration import get_default_tool_runtime_client

        if requested_tool_id not in CANONICAL_REGISTRY:
            return jsonify({
                "ok": False,
                "error": "unknown_tool_id",
                "message": "Only canonical tool_id is supported.",
            }), 400

        gov = TOOL_GOVERNANCE.get(requested_tool_id)
        if gov and gov.status == "forbidden":
            return jsonify({
                "ok": False,
                "error": "forbidden_tool_id",
                "message": gov.reason,
            }), 403

        client = get_default_tool_runtime_client()
        spec = client._registry.get_tool(requested_tool_id)
        if not spec:
            return jsonify({"ok": False, "error": "tool not found"}), 404

        if not spec.dry_run_supported:
            return jsonify({"ok": False, "error": "dry_run not supported for this tool"}), 400

        return jsonify({
            "ok": True,
            "dry_run": True,
            "tool_id": requested_tool_id,
            "canonical_tool_id": requested_tool_id,
            "governance_status": gov.status if gov else "active",
            "risk_level": spec.risk_level,
            "requires_approval": spec.requires_approval,
            "params": list(arguments.keys()),
            "would_do": f"Would invoke {requested_tool_id} with {len(arguments)} argument(s)",
            "note": "This is a preview. The tool will NOT be executed.",
        })

    # ── Execution History ──
    @app.route("/api/tools/history")
    def api_tools_history():
        """Return execution history for the current workspace."""
        ws_id = request.args.get("workspace_id", "default")
        status_filter = request.args.get("status", None)
        try:
            limit = int(request.args.get("limit", 50))
        except (ValueError, TypeError):
            limit = 50

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
            all_approvals = list(_tool_approvals.values())

        records = [
            r for r in all_approvals
            if r.get("workspace_id", "") == ws_id and r.get("status") == "pending"
        ]
        return jsonify({
            "approvals": records,
            "count": len(records),
            "workspace_id": ws_id,
        })

    def _require_admin():
        """Check if request has admin privileges for approval operations.

        Admin authentication methods (in order of priority):
        1. X-Admin-Token header matching NETWORK_AGENT_ADMIN_TOKEN env var
        2. localhost access (127.0.0.1 or ::1) if no admin token is configured

        Returns:
            True if admin, False otherwise
        """
        # Check Admin Token header
        admin_token = request.headers.get("X-Admin-Token", "")
        expected_token = os.environ.get("NETWORK_AGENT_ADMIN_TOKEN", "")
        if expected_token:
            # If admin token is configured, it MUST be provided
            if admin_token == expected_token:
                return True
            return False
        else:
            # If no admin token configured, allow localhost access only
            client_ip = request.remote_addr
            if client_ip in ("127.0.0.1", "::1"):
                return True
            return False

    @app.route("/api/tools/approvals/<approval_id>/approve", methods=["PUT"])
    def api_tools_approve(approval_id):
        """Approve a pending tool approval."""
        # Admin authentication required
        if not _require_admin():
            return jsonify({"ok": False, "error": "admin_access_required"}), 403

        with _lock:
            approval = _tool_approvals.get(approval_id)
            if not approval or approval.get("status") != "pending":
                return jsonify({"ok": False, "error": "approval not found"}), 404
            approval["status"] = "approved"
            approval["resolved_at"] = datetime.now(timezone.utc).isoformat()
        _persist_approvals()

        return jsonify({"ok": True, "approval_id": approval_id, "status": "approved",
                        "note": "Approved. The tool can now be invoked with this approval_id."})

    @app.route("/api/tools/approvals/<approval_id>/reject", methods=["PUT"])
    def api_tools_reject(approval_id):
        """Reject a pending tool approval."""
        # Admin authentication required
        if not _require_admin():
            return jsonify({"ok": False, "error": "admin_access_required"}), 403

        with _lock:
            approval = _tool_approvals.get(approval_id)
            if not approval or approval.get("status") != "pending":
                return jsonify({"ok": False, "error": "approval not found"}), 404
            approval["status"] = "rejected"
            approval["resolved_at"] = datetime.now(timezone.utc).isoformat()
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
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err

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
            _tool_approvals[approval_id] = entry
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
