# knowledge/search.py
"""Knowledge search — keyword + metadata filter.

Returns SearchResult objects. Never returns full content, config, or secrets.
"""

import re
from typing import List, Optional
from knowledge.schemas import SearchResult
from knowledge.store import _read_jsonl, _chunks_path
from knowledge.policy import detect_secrets, contains_secret_pattern
from workspace.ids import validate_workspace_id


def search(
    workspace_id: str,
    query: str = "",
    artifact_type: str = None,
    sensitivity: str = None,
    source_id: str = None,
    artifact_id: str = None,
    llm_safe_only: bool = True,
    limit: int = 20,
) -> List[SearchResult]:
    """Search knowledge index by keyword + metadata filters.

    Scoring: simple keyword match count + position bonus.
    Never returns full file content, full config, or secrets.
    """
    validate_workspace_id(workspace_id)
    cpath = _chunks_path(workspace_id)

    if not cpath.exists():
        return []

    # Read all chunks
    all_chunks = _read_jsonl(cpath)

    # Filter by metadata
    if llm_safe_only:
        all_chunks = [c for c in all_chunks if c.get("llm_safe", True)]
    if artifact_type:
        all_chunks = [c for c in all_chunks if c.get("artifact_type") == artifact_type]
    if sensitivity:
        all_chunks = [c for c in all_chunks if c.get("sensitivity") == sensitivity]
    if source_id:
        all_chunks = [c for c in all_chunks if c.get("source_id") == source_id]
    if artifact_id:
        all_chunks = [c for c in all_chunks if c.get("artifact_id") == artifact_id]

    # Score and rank
    results = []
    query_lower = query.lower().strip() if query else ""

    for chunk in all_chunks:
        score = 0.0
        matched = False

        if query_lower:
            # Search across multiple fields
            fields = [
                chunk.get("safe_excerpt", ""),
                chunk.get("summary", ""),
                chunk.get("tags", []),
                chunk.get("title", ""),
            ]

            for field in fields:
                field_text = " ".join(field) if isinstance(field, list) else field
                field_lower = field_text.lower()

                # Exact keyword matches
                for keyword in query_lower.split():
                    if keyword in field_lower:
                        score += 1.0
                        matched = True

                    # Partial match bonus
                    if len(keyword) >= 3 and keyword[:3] in field_lower:
                        score += 0.3
                        matched = True

            # Title match bonus
            title_lower = (chunk.get("title", "")).lower()
            if query_lower in title_lower:
                score += 2.0
                matched = True
        else:
            # No query → return all matching with score 0
            matched = True
            score = 0.1

        if matched and score >= 0.1:
            # Double-check: never expose secrets in results
            safe_excerpt = chunk.get("safe_excerpt", "")
            if contains_secret_pattern(safe_excerpt):
                # Re-redact just in case
                safe_excerpt = _redact_final(safe_excerpt)

            result = SearchResult(
                chunk_id=chunk.get("chunk_id", ""),
                source_id=chunk.get("source_id", ""),
                artifact_id=chunk.get("artifact_id", ""),
                title=chunk.get("title", ""),
                summary=chunk.get("summary", ""),
                safe_excerpt=safe_excerpt,
                artifact_type=chunk.get("artifact_type", ""),
                sensitivity=chunk.get("sensitivity", ""),
                tags=chunk.get("tags", []),
                score=score,
                source_ref=f"artifact:{chunk.get('artifact_id', '')}",
                llm_safe=chunk.get("llm_safe", True),
            )
            results.append(result)

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _redact_final(text: str) -> str:
    """Final safety redaction — called on search results as a last line of defense."""
    secret_kw = ["password", "passwd", "secret", "token", "api_key",
                  "community", "private_key", "enable secret"]
    for kw in secret_kw:
        pattern = re.compile(r'(' + re.escape(kw) + r'\s*[:=]\s*\S+)', re.I)
        text = pattern.sub("[REDACTED]", text)
    return text
