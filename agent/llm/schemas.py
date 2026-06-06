# agent/llm/schemas.py
"""LLM request/response schemas — skeleton."""

from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class LLMMessage:
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMRequest:
    model: str
    messages: List[LLMMessage] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class LLMResponse:
    content: str = ""
    model: str = ""
    usage: Optional[dict] = None
    error: Optional[str] = None
