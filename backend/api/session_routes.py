"""Session API routes — conversation management endpoints.

All endpoints follow the pattern:
  /api/sessions          — global list / create
  /api/sessions/<id>     — get / update / delete a session
  /api/sessions/<id>/... — archive, restore, messages
"""

from flask import request, jsonify

from workspace.ids import validate_workspace_id, validate_session_id
from workspace.session_store import (
    create_session,
    get_session,
    list_sessions,
    update_session,
    archive_session,
    soft_delete_session,
    delete_session_permanently,
    get_session_messages,
    get_or_create_default_session,
    auto_title_from_input,
    get_session_count,
)


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _invalid_sid():
    return jsonify({"ok": False, "error": "invalid_session_id"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def _validated_session_id(sid):
    try:
        return validate_session_id(sid), None
    except ValueError:
        return None, _invalid_sid()


# ─── Routes ───


def handle_session_create():
    """POST /api/sessions — Create a new session."""
    data = request.get_json(silent=True) or {}
    ws_id = data.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    title = (data.get("title") or "").strip()
    metadata = data.get("metadata") or {}

    session = create_session(ws_id=ws_id, title=title, metadata=metadata)
    return jsonify({"ok": True, "session": session})


def handle_session_list():
    """GET /api/sessions — List sessions for a workspace."""
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    status = request.args.get("status")
    if status == "":
        status = None
    limit = request.args.get("limit", "50")
    try:
        limit = int(limit)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))

    sessions = list_sessions(ws_id, status=status, limit=limit)
    counts = get_session_count(ws_id)
    return jsonify({
        "ok": True,
        "sessions": sessions,
        "counts": counts,
        "workspace_id": ws_id,
    })


def handle_session_detail(session_id):
    """GET /api/sessions/<session_id> — Get session + messages."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    session = get_session(session_id, ws_id)
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    # Optionally include messages
    include_messages = request.args.get("include_messages", "1") == "1"
    result = {"ok": True, "session": session}
    if include_messages:
        result["messages"] = get_session_messages(session_id, ws_id)

    return jsonify(result)


def handle_session_update(session_id):
    """PUT /api/sessions/<session_id> — Update session metadata."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = data.get("title")
    status = data.get("status")
    metadata = data.get("metadata")

    session = update_session(
        session_id, ws_id,
        title=title,
        status=status,
        metadata=metadata,
    )
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    return jsonify({"ok": True, "session": session})


def _complete_session_job(ws_id, session_id, status="succeeded", hard_delete=False):
    """Mark the session-level agent_run job as completed/cancelled, or hard-delete it."""
    try:
        from jobs.store import get_job, update_job, list_jobs, delete_job
        from jobs.manager import mark_succeeded, mark_failed, cancel_job
        for j in list_jobs(ws_id=ws_id, limit=100):
            p = j.get("payload", {}) or {}
            if p.get("session_id") == session_id and j.get("status") in ("created", "queued", "running", "succeeded", "failed", "cancelled"):
                job_id = j.get("job_id", "")
                if hard_delete:
                    delete_job(ws_id, job_id, soft=False)
                elif status == "succeeded":
                    mark_succeeded(ws_id, job_id)
                elif status == "cancelled":
                    cancel_job(ws_id, job_id)
                break
    except Exception:
        pass


def handle_session_archive(session_id):
    """POST /api/sessions/<session_id>/archive — Archive a session."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    session = archive_session(session_id, ws_id)
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    _complete_session_job(ws_id, session_id, "succeeded")

    return jsonify({"ok": True, "session": session})


def handle_session_restore(session_id):
    """POST /api/sessions/<session_id>/restore — Restore an archived/deleted session."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    session = update_session(session_id, ws_id, status="active")
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    # Re-activate the job if it was completed/cancelled
    try:
        from jobs.store import get_job, update_job, list_jobs
        for j in list_jobs(ws_id=ws_id, limit=100):
            p = j.get("payload", {}) or {}
            if p.get("session_id") == session_id and j.get("status") in ("succeeded", "failed", "cancelled"):
                job_id = j.get("job_id", "")
                update_job(ws_id, job_id, {"status": "running", "finished_at": ""})
                break
    except Exception:
        pass

    return jsonify({"ok": True, "session": session})


def handle_session_soft_delete(session_id):
    """POST /api/sessions/<session_id>/soft-delete — Soft delete a session."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    session = soft_delete_session(session_id, ws_id)
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    _complete_session_job(ws_id, session_id, "cancelled")

    return jsonify({"ok": True, "session": session})


def handle_session_delete_permanently(session_id):
    """DELETE /api/sessions/<session_id> — Permanently delete session metadata.

    Requires ?confirm=true. Run records are NOT deleted.
    """
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    confirm = request.args.get("confirm", "") == "true"
    if not confirm:
        return jsonify({
            "ok": False,
            "error": "confirm_required",
            "message": "Set ?confirm=true to permanently delete this session. Run records will be preserved.",
        }), 400

    ok = delete_session_permanently(session_id, ws_id, confirm=True)
    if not ok:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    _complete_session_job(ws_id, session_id, hard_delete=True)

    return jsonify({
        "ok": True,
        "message": "Session metadata deleted. Run records and artifacts remain intact.",
    })


def handle_session_messages(session_id):
    """GET /api/sessions/<session_id>/messages — Get chat messages for a session."""
    session_id, err = _validated_session_id(session_id)
    if err:
        return err
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    messages = get_session_messages(session_id, ws_id)
    return jsonify({"ok": True, "messages": messages, "count": len(messages)})


def handle_session_default():
    """GET /api/sessions/default — Get or create the default active session."""
    ws_id = request.args.get("workspace_id", "default")
    ws_id, err = _validated_ws_id(ws_id)
    if err:
        return err

    session = get_or_create_default_session(ws_id)
    return jsonify({"ok": True, "session": session})
