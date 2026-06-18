"""Hook runner — run lifecycle hooks (pre/post turn, tool, model, approval, etc.).

Extracted from loop.py to centralize all hook execution logic.
"""

from agent.hooks import HookEvent


def build_hook_state(session, context=None):
    """Build a minimal state dict for hook integration."""
    return {
        "intent": "assistant_chat",
        "workspace_id": getattr(session, 'workspace_id', 'default') or 'default',
        "session_id": getattr(session, 'session_id', ''),
        "active_module": "",
        "context": {},
        "skill_results": {},
    }


def run_pre_turn_hooks(session, turn, context):
    """Run PRE_TURN hooks. Returns True if turn should be blocked (Phase 3 fix)."""
    try:
        from agent.hooks_integration import run_pre_turn_hooks, get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return False
        state = build_hook_state(session, context)
        outcome = registry.run_hooks(
            HookEvent.PRE_TURN,
            state,
            {"turn_number": getattr(turn, 'turn_number', 0), "intent": "assistant_chat"},
            target="assistant_chat",
        )
        if not outcome.is_allowed:
            turn.warnings.append(f"pre_turn_blocked: {outcome.reason}")
            return True
        return False
    except Exception as e:
        turn.warnings.append(f"pre_turn_hook_error: {e}")
        return False


def run_pre_tool_hook(session, tool_id: str, arguments: dict) -> tuple:
    """Run PRE_TOOL_USE hook. Returns (allowed, updated_input, reason)."""
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return True, None, ""
        state = build_hook_state(session)
        outcome = registry.run_hooks(
            HookEvent.PRE_TOOL_USE,
            state,
            {"tool_id": tool_id, "arguments": dict(arguments)},
            target=tool_id,
        )
        if outcome.is_denied:
            return False, None, outcome.reason
        return True, outcome.updated_input, ""
    except Exception:
        return True, None, ""


def run_post_tool_hook(session, tool_id: str, result, turn):
    """Run POST_TOOL_USE hook. Returns True if tool loop should stop (Phase 3 fix)."""
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return False
        state = build_hook_state(session)
        rd = result.to_dict() if hasattr(result, 'to_dict') else {"ok": result.ok, "summary": result.summary}
        outcome = registry.run_hooks(
            HookEvent.POST_TOOL_USE,
            state,
            {"tool_id": tool_id, "result": rd},
            target=tool_id,
        )
        if outcome.feedback:
            if not hasattr(result, 'warnings'):
                result.warnings = []
            if isinstance(result.warnings, list):
                result.warnings.append(f"hook_feedback: {outcome.feedback}")
        if outcome.should_stop:
            turn.warnings.append(f"post_tool_stop: {tool_id} stopped by hook: {outcome.reason}")
            return True
        return False
    except Exception:
        return False


def run_post_turn_hooks(session, turn, final_response: str):
    """Run POST_TURN hook."""
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return
        state = build_hook_state(session)
        registry.run_hooks(
            HookEvent.POST_TURN,
            state,
            {"turn_number": getattr(turn, 'turn_number', 0), "model_response": final_response},
            target="assistant_chat",
        )
    except Exception:
        pass


def run_stop_hooks(session):
    """Run STOP hooks at task completion."""
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return
        state = build_hook_state(session)
        registry.run_hooks(
            HookEvent.STOP,
            state,
            {"intent": "assistant_chat"},
            target="assistant_chat",
        )
    except Exception:
        pass


def run_pre_model_hook(session, messages, tools, context, step):
    """Run PRE_MODEL hook before each LLM call.

    Returns True if the LLM call should be blocked (hook denied).
    """
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return False
        state = build_hook_state(session, context)
        outcome = registry.run_hooks(
            HookEvent.PRE_MODEL,
            state,
            {"message_count": len(messages), "tool_count": len(tools), "step": step},
            target="assistant_chat",
        )
        if outcome.is_denied:
            return True
        return False
    except Exception:
        return False


def run_post_model_hook(session, resp, context, step):
    """Run POST_MODEL hook after each LLM response.

    Returns modified content string if hook modified the response, else None.
    """
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return None
        state = build_hook_state(session, context)
        outcome = registry.run_hooks(
            HookEvent.POST_MODEL,
            state,
            {
                "step": step,
                "has_content": bool(getattr(resp, 'content', '')),
                "has_tool_calls": resp.has_tool_calls() if hasattr(resp, 'has_tool_calls') else False,
                "finish_reason": getattr(resp, 'finish_reason', ''),
                "response": getattr(resp, 'content', ''),
            },
            target="assistant_chat",
        )
        if outcome.updated_input and isinstance(outcome.updated_input, str):
            return outcome.updated_input
        return None
    except Exception:
        return None


def run_error_hook(session, error_type: str, error_data: dict, context=None):
    """Run ON_ERROR hook when an error occurs."""
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return
        state = build_hook_state(session, context)
        registry.run_hooks(
            HookEvent.ON_ERROR,
            state,
            {"error_type": error_type, **error_data},
            target=error_type,
        )
    except Exception:
        pass


def run_approval_hook(session, stage: str, approval_id: str, tool_id: str, context=None):
    """Run ON_APPROVAL hook at approval stage transitions.

    Args:
        stage: One of "required", "allowed", "denied".
    """
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return
        state = build_hook_state(session, context)
        registry.run_hooks(
            HookEvent.ON_APPROVAL,
            state,
            {"stage": stage, "approval_id": approval_id, "tool_id": tool_id},
            target=tool_id,
        )
    except Exception:
        pass


def run_user_prompt_submit_hook(session, context) -> bool:
    """v3.0.0: Run UserPromptSubmit hook when user sends a message.

    Returns True if the prompt should be blocked (hook denied).
    """
    try:
        from agent.hooks_integration import get_hook_registry
        registry = get_hook_registry()
        if not registry._hooks:
            return False
        state = build_hook_state(session, context)
        user_input = getattr(context, "user_input", "") or ""
        outcome = registry.run_hooks(
            HookEvent.USER_PROMPT_SUBMIT,
            state,
            {"prompt": user_input, "user_input": user_input},
            target="user_input",
        )
        if outcome.is_denied:
            return True
        # Apply context injections from hooks
        if outcome.context_injections:
            if not hasattr(context, "metadata"):
                context.metadata = {}
            ctx_inj = context.metadata.setdefault("hook_context_injections", [])
            ctx_inj.extend(outcome.context_injections)
        return False
    except Exception:
        return False
