# agent/runtime/capability_routing/models.py
"""Data contracts for capability-first business execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModuleServiceManifest:
    """A domain service used behind tools.

    Modules own business implementation. They are not directly visible to the
    LLM and are not selected by the planner.
    """

    module_id: str
    package: str
    service_path: str
    operations: tuple[str, ...] = ()
    owns_business_logic: bool = True


@dataclass(frozen=True)
class CapabilityPackage:
    """Business capability package selected before tool planning.

    A capability package is the current replacement for tool-first routing. It
    declares when it applies, which module services it depends on, and which
    small set of tools may become visible for this turn.
    """

    capability_id: str
    display_name: str
    description: str
    intent_keywords: tuple[str, ...]
    module_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    prompt_hints: tuple[str, ...] = ()
    output_kinds: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    priority: int = 50

    def matches(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(keyword.lower() in lower for keyword in self.intent_keywords)


@dataclass(frozen=True)
class ToolBundle:
    """Small tool set exposed to the planner for one turn."""

    core_tools: tuple[str, ...]
    capability_tools: tuple[str, ...]
    capability_ids: tuple[str, ...]
    module_ids: tuple[str, ...]
    tool_limit: int = 12
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def visible_tools(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for tool_id in [*self.core_tools, *self.capability_tools]:
            if tool_id and tool_id not in seen:
                seen.add(tool_id)
                out.append(tool_id)
            if len(out) >= self.tool_limit:
                break
        return out
