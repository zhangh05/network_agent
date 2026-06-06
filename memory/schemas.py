# memory/schemas.py
"""Memory record schema definitions."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MemoryRecord:
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    scope: str = "short_term"        # short_term | project | long_term
    memory_type: str = "knowledge_note"  # decision | user_preference | project_state | device_profile | translation_rule | troubleshooting_case | run_summary | knowledge_note
    title: str = ""
    summary: str = ""
    content: str = ""
    tags: list = field(default_factory=list)
    project_id: str = ""
    source: str = ""                 # agent | user | system
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def as_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "scope": self.scope,
            "memory_type": self.memory_type,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
            "project_id": self.project_id,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryRecord":
        return cls(
            memory_id=data.get("memory_id", ""),
            scope=data.get("scope", "short_term"),
            memory_type=data.get("memory_type", "knowledge_note"),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            project_id=data.get("project_id", ""),
            source=data.get("source", ""),
            confidence=data.get("confidence", 0.8),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
