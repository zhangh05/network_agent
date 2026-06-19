# agent/runtime/memory/models.py
"""Memory data models — MemoryItem, MemoryQueryPlan, MemoryWritePlan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryItem:
    """A single memory entry retrieved or to be written."""

    memory_id: str = ""
    memory_type: str = ""          # "profile", "fact", "preference", "event"
    scope: str = "workspace"       # "session", "workspace", "global"
    content: str = ""
    summary: str = ""
    confidence: float = 1.0
    confirmation_status: str = "unconfirmed"  # "confirmed", "unconfirmed", "rejected"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryQueryPlan:
    """Describes whether and how to search memory."""

    should_search: bool = False
    query_text: str = ""
    top_k: int = 5
    scope: str = ""                # empty = all scopes
    memory_types: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class MemoryWritePlan:
    """Describes whether and how to write a memory entry."""

    should_write: bool = False
    memory_type: str = ""
    scope: str = "workspace"
    content: str = ""
    requires_confirmation: bool = True
    reason: str = ""
