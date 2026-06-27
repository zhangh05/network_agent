# agent/runtime/prompting/compiler.py
"""PromptCompiler — assembles system prompt, safe_context, history and user input.

For non-simple-chat turns, system prompt assembly is delegated to the
capability-first prompt architecture. Simple chat keeps the minimal CORE_PROMPT.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.prompting.blocks import CORE_PROMPT, SUB_AGENT_PREAMBLE
from agent.runtime.prompting.safe_context_renderer import render_safe_context
from agent.runtime.prompting.history_renderer import build_user_content_with_images


class PromptCompiler:
    """Compile the initial message list for a turn."""

    def compile(self, context: Any, services: Any) -> list:
        """Build the initial message list.

        v3.10: Always injects runtime contract + TaskState summary when available.
        Even simple-chat turns get runtime context if a task is active.
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

        # v3.10: Check for active task state — don't skip runtime context if task is active
        has_active_task = _has_active_task(context)
        is_pure = is_pure_greeting(user_input)
        is_simple_chat = (
            not has_tool_scene
            and not has_context_data
            and not has_active_task  # v3.10: don't skip runtime if task is active
            and (not intent or intent in ('assistant_chat', 'capability_discovery'))
            and (not skill or skill in ('assistant_chat', 'capability_discovery'))
            and not looks_like_tool_query(user_input)
            and is_pure  # v3.10: only truly standalone pure greetings skip context, NOT 'ok/continue/next'
        )

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

        # ── Runtime contract (v3.10: injected for all non-trivial turns) ──
        if not is_simple_chat or has_active_task:
            contract = _build_runtime_contract(context)
            messages.append(RuntimeContextMessage(content=contract).to_llm_message())

        # ── TaskState summary (v3.10: visible context from durable runtime) ──
        if has_active_task:
            task_summary = _build_task_summary(context)
            if task_summary:
                messages.append(RuntimeContextMessage(content=task_summary).to_llm_message())

        # ── Safe context ──────────────────────────────────────────
        safe_context_text = render_safe_context(getattr(context, "safe_context", None))
        if safe_context_text and not is_simple_chat:
            from agent.protocol.message import RuntimeContextMessage
            messages.append(RuntimeContextMessage(content=safe_context_text).to_llm_message())

        # ── Capability contracts ────────────────────────────────────
        # Capability context is already in the system prompt via prompt_architecture.

        # ── History window ────────────────────────────────────────
        for h in context.history_window:
            if hasattr(h, 'to_llm_message'):
                messages.append(h.to_llm_message())
            elif isinstance(h, dict) and h.get("role") and h.get("content") is not None:
                from agent.llm.schemas import LLMMessage
                messages.append(LLMMessage(role=str(h.get("role")), content=str(h.get("content"))))

        # ── Current user input ────────────────────────────────────
        user_content = build_user_content_with_images(context, user_input)
        messages.append(UserMessage(content=user_content).to_llm_message())

        return messages


# ── v3.10: Runtime contract helpers ──

def _has_active_task(context: Any) -> bool:
    """Check if there's an active TaskState for this session."""
    try:
        ws_id = getattr(context, 'workspace_id', '') or ''
        sess_id = getattr(context, 'session_id', '') or ''
        if not ws_id or not sess_id:
            return False
        from agent.runtime.durable.store import list_tasks
        tasks = list_tasks(ws_id, session_id=sess_id, limit=1)
        if tasks:
            t = tasks[0]
            return t.status in ('running', 'waiting_approval', 'interrupted')
    except Exception:
        pass
    return False


def _build_runtime_contract(context: Any) -> str:
    """Build minimal runtime contract for LLM context."""
    ws_id = getattr(context, 'workspace_id', '') or ''
    parts = [
        "## Runtime Contract v3.10",
        f"- Workspace: {ws_id or 'unspecified'}",
        f"- Session: {getattr(context, 'session_id', '')[:12] or 'unspecified'}",
        "- Approval: high-risk tools require approval before execution",
        "- Verification: unverified tasks cannot be marked complete",
        "- Tool boundary: all tools execute through safety pipeline",
        "- Caller identity: enforced (missing caller → blocked)",
    ]
    return '\n'.join(parts)


def _build_task_summary(context: Any) -> str:
    """Build TaskState summary for LLM context."""
    try:
        ws_id = getattr(context, 'workspace_id', '') or ''
        sess_id = getattr(context, 'session_id', '') or ''
        from agent.runtime.durable.store import list_tasks
        tasks = list_tasks(ws_id, session_id=sess_id, limit=1)
        if not tasks:
            return ""
        t = tasks[0]
        parts = [
            "## Active Task",
            f"Task: {t.task_id[:12]}...",
            f"Status: {t.status}",
            f"Goal: {t.user_goal[:200]}" if t.user_goal else "",
            f"Steps: {len(t.steps or [])}",
        ]
        warnings = getattr(t, 'warnings', []) or []
        errors = getattr(t, 'errors', []) or []
        if warnings:
            parts.append(f"Warnings: {', '.join(warnings[:5])}")
        if errors:
            parts.append(f"Errors: {', '.join(errors[:5])}")
        if hasattr(t, 'delivery_mode') and t.delivery_mode:
            parts.append(f"Delivery mode: {t.delivery_mode}")
        return '\n'.join(p for p in parts if p)
    except Exception:
        return ""
