# backend/agent/router.py
"""Intent router — maps user intent to skill (placeholder for LangGraph)."""

from typing import Optional


_SUPPORTED_INTENTS = {
    "translate_config": "config_translate",
}


def route_intent(intent: str) -> Optional[str]:
    """Return skill_name for the given intent, or None if unsupported."""
    return _SUPPORTED_INTENTS.get(intent)
