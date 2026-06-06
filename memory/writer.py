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
        metadata=metadata or {},
        redaction_applied=redaction_applied or policy.redaction_needed,
    )

    # ═══ Step 4: Persist ═══
    store = get_store()
    return store.put(record)


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
