# agent/runtime/prompts.py
"""Runtime system prompt — slimmed delegation layer.

v3.3: Constants moved to prompting/blocks.py, PromptProfile to prompting/profile.py,
classify_intent to cognition/scene_decision.py. This file retains the build_* API
that internal callers use, delegating to the new canonical modules.
"""

from agent.runtime.prompting.blocks import CORE_PROMPT, SUB_AGENT_PREAMBLE
from agent.runtime.prompting.profile import PromptProfile
from agent.runtime.cognition.scene_decision import classify_intent_profile


def classify_intent(intent: str = "", user_input: str = "") -> dict:
    """Delegate to cognition.scene_decision.classify_intent_profile."""
    return classify_intent_profile(intent, user_input)


def build_system_prompt(intent: str = "", user_input: str = "",
                        has_high_risk_tools: bool = False) -> str:
    profile = classify_intent(intent, user_input)
    if has_high_risk_tools:
        profile["has_high_risk_tools"] = True

    return PromptProfile(
        intent=profile.get("intent", "chat"),
        has_tools=profile.get("has_tools", False),
        has_high_risk_tools=profile.get("has_high_risk_tools", False),
        has_knowledge=profile.get("has_knowledge", False),
        is_network_task=profile.get("is_network_task", False),
        is_factual_query=profile.get("is_factual_query", False),
    ).build()


def build_simple_chat_prompt() -> str:
    """Codex-style minimal prompt for simple chat."""
    return CORE_PROMPT
