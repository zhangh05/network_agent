# agent/runtime/prompts.py
"""Runtime system prompt — minimal API surface.

v3.4: classify_intent and build_system_prompt removed.
Use prompting/profile.py (PromptProfile) and cognition/scene_decision.py
(classify_intent_profile, decide_scene) directly.
"""

from agent.runtime.prompting.blocks import CORE_PROMPT


def build_simple_chat_prompt() -> str:
    """Codex-style minimal prompt for simple chat."""
    return CORE_PROMPT
