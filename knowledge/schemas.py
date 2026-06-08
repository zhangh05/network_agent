# knowledge/schemas.py
"""Knowledge Index Runtime — data schemas."""

from dataclasses import dataclass, field
from typing import Optional, List
import time
import uuid


@dataclass
class KnowledgeSource:
    """A knowledge source backed by an artifact."""
    source_id: str = ""
    artifact_id: str = ""
    workspace_id: str = ""
    title: str = ""
    artifact_type: str = ""
    sensitivity: str = "internal"
    lifecycle: str = "active"
    status: str = "pending"
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    chunk_ids: List[str] = field(default_factory=list)
    chunk_count: int = 0
    total_size_bytes: int = 0
    error_message: str = ""
    created_at: str = ""
    indexed_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.source_id:
            self.source_id = f"ks_{uuid.uuid4().hex[:16]}"
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class SafeChunk:
    """Safe excerpt chunk — no full config, secrets, or absolute paths."""
    chunk_id: str = ""
    source_id: str = ""
    artifact_id: str = ""
    workspace_id: str = ""
    title: str = ""
    summary: str = ""
    safe_excerpt: str = ""
    sensitivity: str = "internal"
    artifact_type: str = ""
    tags: List[str] = field(default_factory=list)
    chunk_index: int = 0
    char_start: int = 0
    char_end: int = 0
    redacted: bool = False
    llm_safe: bool = True
    created_at: str = ""

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = f"kc_{uuid.uuid4().hex[:16]}"
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class SearchResult:
    """Safe search result — no full content, config, or secrets."""
    chunk_id: str = ""
    source_id: str = ""
    artifact_id: str = ""
    title: str = ""
    summary: str = ""
    safe_excerpt: str = ""
    artifact_type: str = ""
    sensitivity: str = ""
    tags: List[str] = field(default_factory=list)
    score: float = 0.0
    source_ref: str = ""
    llm_safe: bool = True  # Whether this chunk passed Safe RAG filter

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "source_id": self.source_id,
            "artifact_id": self.artifact_id, "title": self.title,
            "artifact_name": self.title,  # alias for frontend compatibility
            "summary": self.summary, "safe_excerpt": self.safe_excerpt,
            "artifact_type": self.artifact_type, "sensitivity": self.sensitivity,
            "tags": self.tags, "score": round(self.score, 3),
            "source_ref": self.source_ref,
            "llm_safe": self.llm_safe,
        }


# ═══════════════════ Constants ═══════════════════

INDEXABLE_TYPES = {
    "knowledge_doc", "report", "inspection_log",
    "input_config", "output_config", "topology_json",
    "topology_image", "export",
}

FORBIDDEN_SECRET_PATTERNS = [
    "password", "passwd", "secret", "token", "api_key",
    "private_key", "community", "snmp", "enable secret",
]
