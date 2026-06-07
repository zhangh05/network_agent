# knowledge/chunker.py
"""Safe text chunking for knowledge indexing.

- Splits text by paragraphs/characters
- Detects and redacts secrets
- Generates SafeChunk objects
- Marks sensitive chunks as llm_safe=False
"""

import re
from typing import List
from knowledge.schemas import SafeChunk
from knowledge.policy import (
    detect_secrets, redact_secrets, contains_secret_pattern,
    extract_safe_excerpt, can_generate_llm_chunks,
)

DEFAULT_CHUNK_SIZE = 800       # characters
DEFAULT_OVERLAP = 150          # characters
MAX_EXCERPT_CHARS = 200


def split_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_OVERLAP) -> List[str]:
    """Split text into overlapping chunks by paragraph/character boundaries."""
    if not text or not text.strip():
        return []

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Try paragraph-based splitting first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) <= chunk_size:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                chunks.append(current)
            # If single paragraph exceeds chunk_size, split by characters
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    sub = para[i:i + chunk_size]
                    if sub.strip():
                        chunks.append(sub)
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def create_safe_chunks(
    text: str,
    source_id: str,
    artifact_id: str,
    workspace_id: str,
    title: str = "",
    artifact_type: str = "",
    sensitivity: str = "internal",
    tags: list = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> List[SafeChunk]:
    """Create SafeChunk objects from text, applying security policies.

    Rules:
    - Sensitive/confidential → llm_safe=False, metadata only
    - Secret patterns → redacted
    - Absolute paths → detected, excerpt truncated
    - Non-text artifacts → empty list
    """
    if not text or not text.strip():
        return []

    # Determine LLM-safety based on sensitivity
    llm_safe = can_generate_llm_chunks(sensitivity)

    # Split into raw chunks
    raw_chunks = split_text(text, chunk_size=chunk_size, overlap=overlap)
    if not raw_chunks:
        return []

    results: List[SafeChunk] = []
    char_pos = 0

    for idx, raw in enumerate(raw_chunks):
        if not raw.strip():
            char_pos += len(raw)
            continue

        # Detect and redact secrets
        has_secrets = contains_secret_pattern(raw)
        safe_text = redact_secrets(raw) if has_secrets else raw

        # Extract safe excerpt
        excerpt = extract_safe_excerpt(safe_text, MAX_EXCERPT_CHARS)

        # Summary — first line or first 80 chars
        first_line = safe_text.strip().split("\n")[0][:80]
        summary = first_line if len(first_line) < 80 else first_line[:77] + "..."

        chunk = SafeChunk(
            source_id=source_id,
            artifact_id=artifact_id,
            workspace_id=workspace_id,
            title=title,
            summary=summary,
            safe_excerpt=excerpt,
            sensitivity=sensitivity,
            artifact_type=artifact_type,
            tags=tags or [],
            chunk_index=idx,
            char_start=char_pos,
            char_end=char_pos + len(raw),
            redacted=has_secrets,
            llm_safe=llm_safe and not has_secrets,
        )
        results.append(chunk)
        char_pos += len(raw)

    return results
