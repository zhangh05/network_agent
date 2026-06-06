# backend/agent/state.py
"""Agent state definitions (placeholder for LangGraph integration)."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentState:
    intent: str = ""
    skill: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
