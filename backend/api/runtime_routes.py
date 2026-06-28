# backend/api/runtime_routes.py
"""Runtime routes — diagnostics, selfcheck, retention, archive, tool invocation."""

import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

from flask import jsonify, request

from workspace.ids import validate_workspace_id

_LOG = logging.getLogger(__name__)


# ── In-memory state for execution history ──
_TOOL_HISTORY_MAX = 200
_tool_exec_history = OrderedDict()
_lock = threading.Lock()

_HISTORY_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'tool_history.json'


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
        _LOG.warning("_persist_history atomic write failed (non-fatal)", exc_info=True)


def _load_persisted():
    from workspace.atomic_io import safe_read_json
    items = safe_read_json(_HISTORY_FILE, default=[]) or []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _tool_exec_history[item.get('invocation_id', '')] = item


_load_persisted()


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw=None):
    """Validate workspace_id. Returns (ws_id, None) or (None, error_response).
    
    No implicit default — caller must provide a valid workspace_id.
    """
    if not raw:
        return None, _invalid_ws()
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def _get_tool_risk_level(client, tool_id: str) -> str:
    """Get risk level for a tool_id from the registry."""
    try:
        spec = client._registry.get_tool(tool_id)
        return spec.risk_level if spec else "unknown"
    except Exception:
        return "unknown"


def _validate_approved_tool_invocation(approval_id: str, tool_id: str, workspace_id: str) -> bool:
    """Return True only for an approved ID that matches tool and workspace.

    Uses the UNIFIED ApprovalStore — no legacy fallback.
    """
    if not approval_id:
        return False
    try:
        from agent.approval import get_approval_store

        history = get_approval_store().get_history(tool_id=tool_id, workspace_id=workspace_id, limit=500)
        for rec in history:
            if (
                rec.get("approval_id") == approval_id
                and rec.get("allowed") is True
                and rec.get("tool_id") == tool_id
                and rec.get("workspace_id", "") == workspace_id
            ):
                return True
    except Exception:
        pass
    return False


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
    from tool_runtime.redaction import redact_tool_output

    output = redact_tool_output(output or {})
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
        # v3.9.4: services hold a frozen list snapshot, not the catalog module.
        caps = services.capability_catalog
        cap_counts = {
            "total": len(caps),
            "enabled": len([c for c in caps if c.get("status") == "enabled"]),
            "planned": len([c for c in caps if c.get("status") == "planned"]),
            "disabled": len([c for c in caps if c.get("status") == "disabled"]),
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
        ws_id = request.args.get("workspace_id", "")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        report = get_diagnostics(ws_id)
        return jsonify(report.as_dict())

    @app.route("/api/runtime/selfcheck")
    def api_runtime_selfcheck():
        ws_id = request.args.get("workspace_id", "")
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
        ws_id = request.args.get("workspace_id", "")
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

        from tool_runtime.canonical_registry import CANONICAL_REGISTRY
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.schemas import ToolInvocation
        from tool_runtime.context import ToolRuntimeContext

        if requested_tool_id not in CANONICAL_REGISTRY:
            return jsonify({
                "ok": False,
                "error": "unknown_tool_id",
                "message": "Only canonical tool_id is supported.",
            }), 400

        gov = None  # v3.9.3: governance removed
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
            requested_by="rest_api",
            approval_id=approval_id,
        )

        if approval_id and not _validate_approved_tool_invocation(approval_id, requested_tool_id, ws_id):
            return _blocked_tool_response(
                invocation, ws_id, _get_tool_risk_level(client, requested_tool_id),
                "invalid_approval_id",
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

        governance_status = gov.status if gov else "active"
        context = ToolRuntimeContext(
            workspace_id=ws_id,
            requested_by="rest_api",
            approval_id=approval_id,
        )
        result = client.invoke(
            requested_tool_id,
            arguments,
            dry_run=dry_run,
            context=context,
        )
        ok = result.status in ("succeeded", "dry_run")
        status = result.status
        summary = result.summary or (f"Invoked {requested_tool_id}." if ok else "tool_invocation_failed")
        output = _safe_output(result.output)
        errors = list(result.errors or [])[:20]
        warnings = list(result.warnings or [])[:20]

        return jsonify({
            "ok": ok,
            "invocation_id": result.invocation_id,
            "tool_id": requested_tool_id,
            "canonical_tool_id": requested_tool_id,
            "governance_status": governance_status,
            "status": status,
            "summary": summary,
            "output": output,
            "errors": errors,
            "warnings": warnings,
            "duration_ms": result.duration_ms,
            "redacted": result.redacted,
            "policy_decision": result.policy_decision.__dict__ if result.policy_decision else None,
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
        from tool_runtime.integration import get_default_tool_runtime_client

        if requested_tool_id not in CANONICAL_REGISTRY:
            return jsonify({
                "ok": False,
                "error": "unknown_tool_id",
                "message": "Only canonical tool_id is supported.",
            }), 400

        gov = None  # v3.9.3: governance removed
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
        ws_id = request.args.get("workspace_id", "")
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

    # ── Permissions ──
    @app.route("/api/tools/permissions")
    def api_tools_permissions():
        """Get workspace-level tool permissions."""
        ws_id = request.args.get("workspace_id", "")
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
        dry_run = (request.json or {}).get("dry_run", True) if request.is_json else True
        confirm = (request.json or {}).get("confirm", False) if request.is_json else False
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
        dry_run = (request.json or {}).get("dry_run", True) if request.is_json else True
        confirm = (request.json or {}).get("confirm", False) if request.is_json else False
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

    # ─── v3.8: Graph inspector + SSE + breakpoints ───

    @app.route("/api/agent/graph")
    def api_agent_graph():
        try:
            from tool_runtime.tool_namespace import TOOL_NAMESPACE
            return jsonify({
                "ok": True, "total_tools": len(TOOL_NAMESPACE),
                "core_tools": 5,
                "categories": sorted(set(TOOL_NAMESPACE[t].category for t in TOOL_NAMESPACE)),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.route("/api/agent/breakpoints", methods=["GET", "POST", "DELETE"])
    def api_agent_breakpoints():
        if request.method == "GET":
            from agent.runtime.auto_checkpoint import get_dynamic_breakpoints
            return jsonify({"ok": True, "breakpoints": list(get_dynamic_breakpoints())})
        elif request.method == "POST":
            data = request.get_json(silent=True) or {}
            tools = data.get("tools", [])
            # Normalize: accept comma-separated string or JSON list
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(",") if t.strip()]
            elif not isinstance(tools, list):
                tools = [str(tools)]
            os.environ["AGENT_BREAKPOINT_TOOLS"] = ",".join(tools)
            return jsonify({"ok": True, "tools": tools})
        else:
            os.environ.pop("AGENT_BREAKPOINT_TOOLS", None)
            return jsonify({"ok": True, "breakpoints": []})

    @app.route("/api/agent/runtime-mode")
    def api_agent_runtime_mode():
        mode = os.environ.get("AGENT_RUNTIME", "turn_runner")
        graph_ok = False
        try:
            from langgraph.graph import StateGraph
            graph_ok = True
        except ImportError:
            pass
        return jsonify({"ok": True, "mode": mode, "graph_runner_available": graph_ok})

    @app.route("/api/agent/sse/stream/<session_id>")
    def api_agent_sse_stream(session_id):
        """SSE streaming endpoint — live agent execution events."""
        from flask import Response, stream_with_context
        from agent.runtime.session_events import subscribe
        import json as _json

        try:
            from workspace.ids import validate_session_id
            sid = validate_session_id(session_id)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_session_id"}), 400

        raw_ws_id = request.args.get("workspace_id", "")
        if not raw_ws_id:
            return jsonify({"ok": False, "error": "workspace_id is required"}), 400
        ws_id, err = _validated_ws_id(raw_ws_id)
        if err:
            return err

        try:
            from workspace.session_store import get_session
            if not get_session(sid, ws_id):
                return jsonify({"ok": False, "error": "session_not_found"}), 404
        except Exception:
            return jsonify({"ok": False, "error": "session_lookup_failed"}), 500

        def generate():
            connected = {"session_id": sid, "workspace_id": ws_id}
            yield f"event: connected\ndata: {_json.dumps(connected, ensure_ascii=False)}\n\n"
            import time as _time
            deadline = _time.time() + 3600  # 1 hour max
            while _time.time() < deadline:
                frame = subscribe(sid, timeout=30)
                if frame:
                    yield frame
                else:
                    yield ": keepalive\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
