# memory/writer.py
"""Memory writer — high-level write interface with redaction and policy enforcement."""

from typing import Optional
from memory.schemas import MemoryRecord, SCOPES
from memory.redaction import redact_text, redact_dict, contains_secret, summarize_config_safely
from memory.policy import can_write_memory
from memory.store import get_store


def write_memory(
    title: str,
    content: str = "",
    scope: str = "short_term",
    memory_type: str = "knowledge_note",
    tags: list = None,
    project_id: str = "",
    source: str = "agent",
    confidence: str = "system_generated",
    summary: str = "",
    sensitivity: str = "internal",
    metadata: dict = None,
    user_confirmed: bool = False,
) -> str:
    """Write a memory record with redaction and policy enforcement.
    
    Returns memory_id on success, empty string on policy block.
    """
    # ═══ Step 1: Redaction ═══
    has_secret = contains_secret(content) or contains_secret(title)
    if has_secret:
        content = redact_text(content)
        title = redact_text(title)
        summary = redact_text(summary)
        redaction_applied = True
    else:
        redaction_applied = False

    # ═══ Step 2: Policy check ═══
    effective_confidence = "user_confirmed" if user_confirmed else confidence
    policy = can_write_memory(
        memory_type=memory_type,
        content=content,
        confidence=effective_confidence,
    )

    if not policy.allowed:
        # Blocked by policy — don't write
        return ""

    # ═══ Step 3: Conflict scan ═══
    meta = dict(metadata or {})
    try:
        from memory.conflicts import detect_memory_conflicts
        conflicts = detect_memory_conflicts(
            title=title,
            content=content,
            memory_type=memory_type,
            project_id=project_id,
            tags=tags or [],
        )
        if conflicts:
            meta["conflict_detected"] = True
            meta["conflicts"] = conflicts
    except Exception:
        pass

    # ═══ Step 3: Build record ═══
    record = MemoryRecord(
        scope=scope,
        memory_type=memory_type,
        title=title,
        summary=summary or (content[:200] if content else ""),
        content=content,
        tags=tags or [],
        project_id=project_id,
        source=source,
        confidence=effective_confidence,
        sensitivity=sensitivity,
        metadata=meta,
        redaction_applied=redaction_applied or policy.redaction_needed,
    )

    # ═══ Step 4: Persist ═══
    store = get_store()
    memory_id = store.put(record)

    # ═══ Step 5: RAG projection (best effort) ═══
    try:
        from memory.indexer import index_memory_record
        index_memory_record(record)
    except Exception:
        pass

    return memory_id


# ─── Convenience writers ───

def write_run_summary(
    intent: str,
    skill: str,
    module: str,
    counts: str = "",
    llm_metadata: dict = None,
    project_id: str = "default",
    artifact_refs: list = None,
) -> Optional[str]:
    """Write a run_summary record (always short_term, auto-redacted)."""
    content = f"intent={intent} skill={skill} module={module}{counts}"
    if llm_metadata and llm_metadata.get("used"):
        content += f" | llm:{llm_metadata.get('provider')} task:{llm_metadata.get('task')}"

    meta = {}
    if artifact_refs:
        safe = [r for r in artifact_refs if r.get("sensitivity") != "secret" and r.get("scope") != "temp"]
        if safe:
            content += f" | artifacts:{len(safe)}"
            meta["artifact_refs"] = safe

    return write_memory(
        title=f"Agent run: {intent}",
        content=content,
        scope="project",
        memory_type="run_summary",
        tags=["agent_run", intent or "unknown", module or "unknown"],
        project_id=project_id,
        source="agent",
        sensitivity="internal",
        metadata=meta,
    )


def write_user_confirmed_decision(
    title: str,
    content: str,
    tags: list = None,
    project_id: str = "",
) -> Optional[str]:
    """Write a user-confirmed decision (can be long_term)."""
    return write_memory(
        title=title,
        content=content,
        scope="long_term",
        memory_type="decision",
        tags=tags or [],
        project_id=project_id,
        source="user",
        confidence="user_confirmed",
        sensitivity="internal",
        user_confirmed=True,
    )


def write_translation_rule(
    title: str,
    content: str,
    tags: list = None,
    project_id: str = "",
) -> Optional[str]:
    """Write a translation rule (requires user_confirmed)."""
    return write_memory(
        title=title,
        content=content,
        scope="long_term",
        memory_type="translation_rule",
        tags=tags or ["translation_rule"],
        project_id=project_id,
        source="user",
        confidence="user_confirmed",
        sensitivity="internal",
        user_confirmed=True,
    )


def write_user_preference(
    title: str,
    content: str,
    tags: list = None,
    project_id: str = "",
) -> Optional[str]:
    """Write a user preference (long_term, auto-redacted)."""
    return write_memory(
        title=title,
        content=content,
        scope="long_term",
        memory_type="user_preference",
        tags=tags or [],
        project_id=project_id,
        source="user",
        confidence="user_confirmed",
        sensitivity="internal",
        user_confirmed=True,
    )


def write_job_summary(job_record) -> Optional[str]:
    """Write job summary to memory (sanitized, no full config/key/path)."""
    if not job_record:
        return None
    jd = job_record.as_dict() if hasattr(job_record, "as_dict") else job_record
    safe = {
        "job_id": jd.get("job_id", ""),
        "job_type": jd.get("job_type", ""),
        "title": jd.get("title", ""),
        "status": jd.get("status", ""),
        "progress": jd.get("progress", {}),
        "run_ids": jd.get("run_ids", []),
        "artifact_refs": jd.get("artifact_refs", []),
        "report_artifacts": jd.get("report_artifacts", []),
        "result_summary": jd.get("result_summary", {}),
        "warnings": jd.get("warnings", []),
        "error": str(jd.get("error", ""))[:200],
    }
    content = f"job_id={safe['job_id']} type={safe['job_type']} status={safe['status']}"
    return write_memory(
        title=f"Job: {safe['job_type']} ({safe['status']})",
        content=content,
        scope="project",
        memory_type="run_summary",
        tags=["job_summary", safe.get("job_type", ""), safe.get("status", "")],
        project_id=jd.get("workspace_id", "default"),
        source="agent",
        sensitivity="internal",
        metadata={"job_summary": safe},
    )
