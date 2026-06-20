# agent/runtime/prompting/profile.py
"""Legacy PromptProfile adapter.

Non-simple-chat turns no longer use PromptProfile. They are compiled by
agent.runtime.prompt_architecture.compiler.compile_runtime_prompt().
This module remains only for backwards-compatible imports and tests that still
inspect legacy prompt fragments.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.runtime.prompting.blocks import (
    CORE_PROMPT,
    ANTI_HALLUCINATION,
    RUNTIME_CONTRACT,
    TOOL_CATEGORY_GUIDE,
    APPROVAL_NOTE,
    NETWORK_ENGINEERING_RULES,
    SAFE_CONTEXT_PREAMBLE,
)


@dataclass
class PromptProfile:
    intent: str = "chat"
    has_tools: bool = False
    has_high_risk_tools: bool = False
    has_knowledge: bool = False
    is_network_task: bool = False
    is_factual_query: bool = False

    def fragments(self) -> list[str]:
        frags = [CORE_PROMPT]

        if self.is_factual_query or self.has_knowledge:
            frags.append(ANTI_HALLUCINATION)

        if self.has_tools or self.is_network_task:
            frags.append(RUNTIME_CONTRACT)
            frags.append(TOOL_CATEGORY_GUIDE)

        if self.has_high_risk_tools:
            frags.append(APPROVAL_NOTE)

        if self.is_network_task:
            frags.append(NETWORK_ENGINEERING_RULES)

        if self.has_knowledge:
            frags.append(SAFE_CONTEXT_PREAMBLE)

        return frags

    def build(self) -> str:
        return "".join(self.fragments())

    @classmethod
    def from_scene_decision(cls, scene) -> "PromptProfile":
        """Build a PromptProfile from a SceneDecision."""
        return cls(
            intent=scene.intent,
            has_tools=scene.needs_tool,
            has_high_risk_tools=scene.needs_local_ops,
            has_knowledge=scene.needs_knowledge or scene.needs_context,
            is_network_task=scene.is_network_task,
            is_factual_query=scene.is_factual_query,
        )

    @classmethod
    def from_classify_intent(cls, intent: str = "", user_input: str = "") -> "PromptProfile":
        """Build a PromptProfile from classify_intent-style profile dict."""
        from agent.runtime.cognition.scene_decision import classify_intent_profile
        profile = classify_intent_profile(intent, user_input)
        return cls(
            intent=profile.get("intent", "chat"),
            has_tools=profile.get("has_tools", False),
            has_high_risk_tools=profile.get("has_high_risk_tools", False),
            has_knowledge=profile.get("has_knowledge", False),
            is_network_task=profile.get("is_network_task", False),
            is_factual_query=profile.get("is_factual_query", False),
        )
