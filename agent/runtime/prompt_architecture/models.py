# agent/runtime/prompt_architecture/models.py
"""Prompt architecture data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptBlock:
    """A single prompt section with priority ordering and token budget."""

    block_id: str
    title: str
    content: str
    priority: int = 50
    token_budget: int = 800
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptAssembly:
    """Complete assembled prompt with metadata for observability."""

    system_contract: str
    blocks: tuple[PromptBlock, ...]
    final_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)
