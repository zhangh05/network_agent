# agent/hooks_integration.py
"""Integration points — wires the Hook system into the agent pipeline.

Provides convenience functions that run hooks at the right pipeline stages
without cluttering the core node code.
"""

from __future__ import annotations

import logging
from agent.hooks import HookRegistry, HookEvent, HookOutcome, HookDefinition
from agent.state import NetworkAgentState

logger = logging.getLogger(__name__)

# Singleton hook registry
_DEFAULT_REGISTRY: HookRegistry | None = None


def get_hook_registry() -> HookRegistry:
    """Get or create the default hook registry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = HookRegistry()
    return _DEFAULT_REGISTRY


def register_hook(hook: HookDefinition) -> None:
    """Register a hook into the default registry."""
    get_hook_registry().register(hook)


# ── Pipeline integration helpers ──

def run_pre_tool_hooks(state, tool_id: str, arguments: dict) -> tuple[bool, dict | None, str]:
    """Run PreToolUse hooks. Returns (allowed, updated_input, denial_reason)."""
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.PRE_TOOL_USE,
        state,
        {"tool_id": tool_id, "arguments": dict(arguments)},
        target=tool_id,
    )
    if outcome.is_denied:
        logger.info("PreToolUse denied for %s: %s", tool_id, outcome.reason)
        return False, None, outcome.reason
    return True, outcome.updated_input, ""


def run_post_tool_hooks(state, tool_id: str, result: dict) -> tuple[bool, str]:
    """Run PostToolUse hooks. Returns (should_continue, feedback)."""
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.POST_TOOL_USE,
        state,
        {"tool_id": tool_id, "result": result},
        target=tool_id,
    )
    if outcome.should_stop:
        logger.info("PostToolUse stop for %s: %s", tool_id, outcome.reason)
        return False, outcome.feedback
    return True, outcome.feedback


def run_stop_hooks(state) -> tuple[bool, str]:
    """Run Stop hooks at task completion. Returns (should_stop, block_reason).
    
    True = task should stop (complete). False = task should continue (blocked by hook).
    """
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.STOP,
        state,
        {"intent": state.intent},
        target=state.intent or "",
    )
    if outcome.should_block:
        logger.info("Stop blocked: %s", outcome.reason)
        return False, outcome.reason
    return True, ""


def run_session_start_hooks(state) -> tuple[bool, list[str], str]:
    """Run SessionStart hooks. Returns (should_continue, context_injections, stop_reason)."""
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.SESSION_START,
        state,
        {"workspace_id": state.workspace_id},
        target=state.workspace_id or "",
    )
    if outcome.should_stop:
        return False, outcome.context_injections, outcome.reason
    return True, outcome.context_injections, ""


def run_pre_turn_hooks(state, turn_number: int) -> tuple[bool, list[str], str]:
    """Run PreTurn hooks. Returns (should_continue, context_injections, block_reason)."""
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.PRE_TURN,
        state,
        {"turn_number": turn_number, "intent": state.intent},
        target=state.intent or "",
    )
    if not outcome.is_allowed:
        return False, outcome.context_injections, outcome.reason
    return True, outcome.context_injections, ""


def run_post_turn_hooks(state, turn_number: int, model_response: str) -> tuple[bool, list[str]]:
    """Run PostTurn hooks. Returns (should_continue, context_injections).
    
    If should_continue is True even though the turn is "done", it means
    a hook is forcing continuation (analogous to Codex's Stop.block).
    """
    registry = get_hook_registry()
    outcome = registry.run_hooks(
        HookEvent.POST_TURN,
        state,
        {"turn_number": turn_number, "model_response": model_response},
        target=state.intent or "",
    )
    if outcome.should_block:
        logger.info("PostTurn block: forcing continuation")
        return True, outcome.context_injections  # force continue
    return False, outcome.context_injections  # normal stop
