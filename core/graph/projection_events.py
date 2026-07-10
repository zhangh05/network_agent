"""GraphStore projection event helpers.

Projection stores may still write optimized read models (run JSON, message
files, artifact indexes, memory records). They must first append a GraphStore
event so the append-only event log remains the state authority. Projection
writes must fail closed if the graph event cannot be appended.
"""

from __future__ import annotations

from typing import Any

from core.graph.graph_store import EventType, get_graph_store


def append_projection_event(
    event_type: str,
    *,
    run_id: str = "",
    workspace_id: str = "",
    session_id: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """Append a projection event and return its event id.

    Strict SSOT rule: the projection writer may continue only after this event
    is durably accepted by GraphStore. Exceptions intentionally propagate.
    """
    rid = run_id or session_id or workspace_id or "projection"
    data = dict(payload or {})
    data.setdefault("workspace_id", workspace_id)
    data.setdefault("session_id", session_id)
    evt = get_graph_store().append(event_type, rid, data)
    return evt.event_id


def append_run_record_written(*, workspace_id: str, session_id: str, run_id: str, record: dict[str, Any]) -> str:
    return append_projection_event(
        EventType.RUN_RECORD_WRITTEN,
        run_id=run_id,
        workspace_id=workspace_id,
        session_id=session_id,
        payload={
            "run_id": run_id,
            "status": record.get("status", ""),
            "trace_id": record.get("trace_id", ""),
            "created_at": record.get("created_at", ""),
        },
    )


def append_message_written(
    *,
    workspace_id: str,
    session_id: str,
    run_id: str,
    message_id: str,
    role: str,
    artifact_ref: dict[str, Any] | None = None,
) -> str:
    return append_projection_event(
        EventType.MESSAGE_WRITTEN,
        run_id=run_id,
        workspace_id=workspace_id,
        session_id=session_id,
        payload={
            "run_id": run_id,
            "message_id": message_id,
            "role": role,
            "artifact_ref": artifact_ref or {},
        },
    )


def append_artifact_written(*, workspace_id: str, artifact_id: str, run_id: str, session_id: str, record: dict[str, Any]) -> str:
    return append_projection_event(
        EventType.ARTIFACT_WRITTEN,
        run_id=run_id or artifact_id,
        workspace_id=workspace_id,
        session_id=session_id,
        payload={
            "artifact_id": artifact_id,
            "run_id": run_id,
            "artifact_type": record.get("artifact_type", ""),
            "title": record.get("title", ""),
            "file_id": record.get("file_id", ""),
            "sha256": record.get("sha256", ""),
            "sensitivity": record.get("sensitivity", ""),
        },
    )


def append_memory_written(*, workspace_id: str, memory_id: str, record: dict[str, Any]) -> str:
    return append_projection_event(
        EventType.MEMORY_WRITTEN,
        run_id=record.get("task_id") or memory_id,
        workspace_id=workspace_id,
        session_id=record.get("session_id", ""),
        payload={
            "memory_id": memory_id,
            "status": record.get("status", ""),
            "scope": record.get("scope", ""),
            "memory_type": record.get("memory_type", ""),
            "source": record.get("source", ""),
        },
    )


def append_memory_deleted(*, workspace_id: str, memory_id: str, record: dict[str, Any]) -> str:
    return append_projection_event(
        EventType.MEMORY_DELETED,
        run_id=record.get("task_id") or memory_id,
        workspace_id=workspace_id,
        session_id=record.get("session_id", ""),
        payload={
            "memory_id": memory_id,
            "status": "deleted",
            "scope": record.get("scope", ""),
            "memory_type": record.get("memory_type", ""),
            "source": record.get("source", ""),
        },
    )


def append_trace_written(*, workspace_id: str, run_id: str, trace_id: str, event_count: int) -> str:
    return append_projection_event(
        EventType.TRACE_WRITTEN,
        run_id=run_id,
        workspace_id=workspace_id,
        payload={
            "run_id": run_id,
            "trace_id": trace_id,
            "event_count": event_count,
        },
    )
