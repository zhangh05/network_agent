# agent/runtime/prompting/compiler.py
"""PromptCompiler — orchestrates profile + blocks + safe_context + history into messages.

Called by MessageStage instead of build_initial_messages doing everything inline.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.prompting.profile import PromptProfile
from agent.runtime.prompting.blocks import CORE_PROMPT, SUB_AGENT_PREAMBLE
from agent.runtime.prompting.safe_context_renderer import render_safe_context
from agent.runtime.prompting.history_renderer import build_user_content_with_images


class PromptCompiler:
    """Compile the initial message list for a turn."""

    def compile(self, context: Any, services: Any) -> list:
        """Build the initial message list.

        Delegates to PromptProfile for system prompt assembly, render_safe_context
        for context injection, and build_user_content_with_images for vision.
        """
        from agent.protocol.message import UserMessage, SystemMessage, RuntimeContextMessage
        from agent.context.snapshot import RuntimeSnapshot

        messages = []
        user_input = getattr(context, 'user_input', '') or ''
        safe_context = getattr(context, 'safe_context', None) or {}

        # ── Simple chat detection ─────────────────────────────────
        tool_scene = safe_context.get('tool_scene')
        tool_plan = safe_context.get('tool_plan') or safe_context.get('candidate_tools')
        has_tool_scene = bool(
            (tool_scene and isinstance(tool_scene, dict) and tool_scene.get('candidate_tools'))
            or (tool_plan and tool_plan)
        )
        has_context_data = bool(
            safe_context.get('knowledge_hits')
            or safe_context.get('artifact_refs')
            or safe_context.get('memory_hits')
            or safe_context.get('workspace_state')
        )
        intent = getattr(context, 'metadata', {}).get('intent', '') if hasattr(context, 'metadata') else ''
        selected_skills = getattr(context, 'runtime_snapshot', {}).get('selected_skills', [None]) if hasattr(context, 'runtime_snapshot') else []
        skill = selected_skills[0] if selected_skills else None

        from agent.runtime.cognition.scene_decision import is_pure_greeting, looks_like_tool_query

        is_simple_chat = (
            not has_tool_scene
            and not has_context_data
            and (not intent or intent in ('assistant_chat', 'capability_discovery'))
            and (not skill or skill in ('assistant_chat', 'capability_discovery'))
            and not looks_like_tool_query(user_input)
        ) or is_pure_greeting(user_input)

        # ── System prompt ─────────────────────────────────────────
        if is_simple_chat:
            messages.append(SystemMessage(content=CORE_PROMPT).to_llm_message())
        else:
            from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt
            assembly = compile_runtime_prompt(context)
            prompt = assembly.final_prompt
            if getattr(context, "metadata", {}).get('is_sub_agent'):
                prompt = SUB_AGENT_PREAMBLE + "\n" + prompt
            messages.append(SystemMessage(content=prompt).to_llm_message())
            context.metadata["prompt_assembly"] = assembly.metadata

        # ── Runtime snapshot ──────────────────────────────────────
        if not is_simple_chat:
            snapshot_fields = set(RuntimeSnapshot.__dataclass_fields__.keys())
            snap = RuntimeSnapshot(**{
                k: v for k, v in (context.runtime_snapshot or {}).items()
                if k in snapshot_fields
            })
            snap.workspace_id = context.workspace_id
            snap.session_id = context.session_id
            snap.model = context.model_config.get("model", "")
            messages.append(RuntimeContextMessage(content=snap.to_prompt_text()).to_llm_message())

        # ── Safe context ──────────────────────────────────────────
        safe_context_text = render_safe_context(getattr(context, "safe_context", None))
        if safe_context_text and not is_simple_chat:
            from agent.protocol.message import RuntimeContextMessage
            messages.append(RuntimeContextMessage(content=safe_context_text).to_llm_message())

        # ── Skill injections (capability contracts, no prompt injection) ──
        # Capability context is already in the system prompt via prompt_architecture.
        # Skip legacy skill prompt injection.

        # ── History window ────────────────────────────────────────
        for h in context.history_window:
            if hasattr(h, 'to_llm_message'):
                messages.append(h.to_llm_message())

        # ── Current user input ────────────────────────────────────
        user_content = build_user_content_with_images(context, user_input)
        messages.append(UserMessage(content=user_content).to_llm_message())

        return messages
