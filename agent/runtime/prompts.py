# agent/runtime/prompts.py
"""Runtime system prompt — minimal API surface."""

from agent.runtime.prompting.blocks import CORE_PROMPT


def build_simple_chat_prompt() -> str:
    """Codex-style minimal prompt for simple chat."""
    return CORE_PROMPT
