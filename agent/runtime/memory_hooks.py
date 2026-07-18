"""Runtime integrations for storage.memory_governance hooks."""

from __future__ import annotations

import uuid

from storage.memory_governance import MemoryRecord, configure_memory_hooks


def install_memory_governance_hooks() -> None:
    configure_memory_hooks(
        projection=_project_memory_record,
        delete_projection=_delete_memory_projection,
        rank=_rank_memory_records,
        llm_gate=_llm_gate_record,
        event=_emit_memory_event,
    )


def _project_memory_record(record: MemoryRecord) -> None:
    from core.context.context_store import get_context_store
    from storage.memory_governance import MemoryStore

    store = get_context_store(record.workspace_id)
    item_id = f"mh_{record.memory_id}"
    if record.is_retrievable():
        store.put(MemoryStore().projection_item(record))
    elif store.get(item_id) is not None:
        store.delete(item_id)


def _delete_memory_projection(ws_id: str, memory_id: str) -> None:
    from core.context.context_store import get_context_store

    get_context_store(ws_id).purge({f"mh_{memory_id}"})


def _rank_memory_records(query: str, records: list[dict], limit: int) -> list[dict]:
    from core.context.unified_retriever import rank_documents

    return rank_documents(query, records, top_k=limit)


def _llm_gate_record(record: MemoryRecord) -> tuple[bool | None, list[dict]]:
    from agent.runtime.memory_write.llm_gate import MemoryLLMGate
    from agent.runtime.memory_write.models import MemoryCandidate

    candidate = MemoryCandidate(
        candidate_id=record.memory_id,
        memory_type=record.memory_type,
        content=record.content,
        source=record.source,
        task_id=record.task_id,
        confidence=record.confidence,
    )
    accepted, skipped = MemoryLLMGate().gate([candidate])
    if accepted:
        meta = accepted[0].metadata or {}
        summary = meta.get("summary") or meta.get("llm_summary")
        if summary:
            record.summary = str(summary)[:200]
        record.metadata.update(meta)
        return True, skipped
    if any(item.get("reason") == "llm_gate_unavailable" for item in skipped):
        return None, skipped
    return False, skipped


def _emit_memory_event(ws_id: str, record: MemoryRecord, event_type: str) -> None:
    if not record.task_id:
        from storage.events import publish

        publish(ws_id, "memory", event_type, record.memory_id)
        return
    from agent.runtime.durable import RuntimeEvent
    from agent.runtime.durable.store import append_event

    append_event(RuntimeEvent(
        event_id=f"evt-mem-{uuid.uuid4().hex[:8]}",
        task_id=record.task_id,
        workspace_id=ws_id,
        session_id=record.session_id,
        run_id="",
        type=event_type,
        status="ok",
        title=f"Memory {record.memory_id[:8]}: {event_type}",
        summary=record.summary[:200],
        payload_redacted={
            "memory_id": record.memory_id,
            "memory_type": record.memory_type,
        },
    ))
