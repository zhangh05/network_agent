# knowledge/indexer.py
"""Knowledge Indexer — orchestrates the indexing pipeline.

Flow:
  Artifact → check policy → create source → read content → chunk → save
"""

import json
import time
from pathlib import Path
from typing import Optional

from workspace.ids import validate_workspace_id
from knowledge.schemas import KnowledgeSource, SafeChunk
from knowledge.store import (
    save_source, get_source_by_artifact, save_chunks, delete_source,
)
from knowledge.policy import can_index, contains_secret_pattern
from knowledge.chunker import create_safe_chunks


ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def index_artifact(workspace_id: str, artifact_id: str,
                   force: bool = False) -> Optional[KnowledgeSource]:
    """Index an artifact as a knowledge source.

    Pipeline:
    1. Validate workspace_id and artifact
    2. Check index policy (type, lifecycle, sensitivity)
    3. Read artifact content
    4. Create/update KnowledgeSource
    5. Chunk content safely
    6. Save chunks to store
    7. Mark source as indexed
    """
    validate_workspace_id(workspace_id)

    # Get artifact record
    from artifacts.store import get_artifact, read_artifact_content
    artifact = get_artifact(workspace_id, artifact_id)
    if not artifact:
        return None

    # Check if already indexed
    existing = get_source_by_artifact(workspace_id, artifact_id)
    if existing and not force:
        src = KnowledgeSource(**{k: existing.get(k, "") for k in KnowledgeSource.__dataclass_fields__})
        return src

    # Policy gate
    allowed, reason = can_index(artifact.as_dict() if hasattr(artifact, 'as_dict') else artifact.__dict__)
    if not allowed:
        # Reject but don't save a failed source for lifecycle/type blocks
        if "blocked_sensitivity" in reason:
            # Create metadata-only source for sensitive items
            pass
        else:
            return None

    # Read content
    content = read_artifact_content(workspace_id, artifact_id,
                                    allow_sensitive=artifact.sensitivity != "secret")
    if content is None:
        return None

    # Determine if content is text
    mime = getattr(artifact, "mime_type", "") or ""
    if not _is_text_content(mime, content):
        return None

    # Create/update source
    source = KnowledgeSource(
        artifact_id=artifact_id,
        workspace_id=workspace_id,
        title=getattr(artifact, "title", artifact_id),
        artifact_type=getattr(artifact, "artifact_type", ""),
        sensitivity=getattr(artifact, "sensitivity", "internal"),
        lifecycle=getattr(artifact, "lifecycle", "active"),
        status="indexing",
        summary=_build_summary(content),
        tags=getattr(artifact, "tags", []) or [],
        total_size_bytes=len(content.encode("utf-8")),
    )
    save_source(source)

    # Chunk
    chunks = create_safe_chunks(
        text=content,
        source_id=source.source_id,
        artifact_id=artifact_id,
        workspace_id=workspace_id,
        title=source.title,
        artifact_type=source.artifact_type,
        sensitivity=source.sensitivity,
        tags=source.tags,
    )

    if chunks:
        save_chunks(chunks)
        source.chunk_ids = [c.chunk_id for c in chunks]
        source.chunk_count = len(chunks)
        source.status = "indexed"
    else:
        source.chunk_count = 0
        source.status = "indexed"
        source.summary = source.summary or "(no text content)"

    source.indexed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    source.updated_at = source.indexed_at
    save_source(source)

    return source


def reindex_source(workspace_id: str, source_id: str) -> Optional[KnowledgeSource]:
    """Re-index a knowledge source — delete old chunks and re-create."""
    validate_workspace_id(workspace_id)

    from knowledge.store import get_source
    src_rec = get_source(workspace_id, source_id)
    if not src_rec:
        return None

    # Delete old chunks for this source
    delete_source(workspace_id, source_id)

    # Re-index from artifact
    artifact_id = src_rec.get("artifact_id", "")
    return index_artifact(workspace_id, artifact_id, force=True)


def _is_text_content(mime: str, content: str) -> bool:
    """Check if content is indexable text."""
    text_mimes = {"text/plain", "text/markdown", "text/csv", "text/yaml",
                  "application/json", "text/html", ""}
    if any(t in mime for t in ["text/", "json", "yaml", "xml"]):
        return True
    # Try to detect if content looks like text
    if content and len(content) > 0:
        # Check if it contains mostly printable chars
        printable = sum(1 for c in content[:500] if c.isprintable() or c in "\n\r\t")
        if printable / max(len(content[:500]), 1) > 0.8:
            return True
    return False


def _build_summary(content: str, max_len: int = 120) -> str:
    """Build a brief summary from content."""
    if not content:
        return ""
    first_line = content.strip().split("\n")[0][:max_len].strip()
    if len(content.strip().split("\n")[0]) > max_len:
        first_line += "..."
    return first_line
