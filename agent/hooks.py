# agent/hooks.py
"""Hook system — composable pre/post processing pipeline.

Inspired by Codex's Hook pipeline with disjunctive result folding.
Hooks are lightweight callables registered against events with optional
matchers. They execute in priority order and their results fold with
clear semantics:

Result folding rules (Codex pattern):
  - PreToolUse: any Deny wins immediately; last Allow's updated_input wins
  - PostToolUse: any stop=true wins; feedback concatenated
  - PreTurn: any block=true wins; context_injections merged
  - PostTurn: any block=true wins (force continue); outputs collected
  - SessionStart: any stop=true wins; contexts merged
  - Stop: block (force continue) overrides stop

Thin Python adaption — no subprocess exec, direct callable invocation.
"""

from __future__ import annotations

import enum
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════
# Event types
# ═══════════════════════════

class HookEvent(str, enum.Enum):
    """Hook event names — mirrors Codex's 7 core events."""
    PRE_TOOL_USE = "PreToolUse"          # before tool execution: can block or rewrite input
    POST_TOOL_USE = "PostToolUse"        # after tool execution: can stop or give feedback
    PRE_TURN = "PreTurn"                # before LLM turn: can block or inject context
    POST_TURN = "PostTurn"              # after LLM turn: can validate or force continue
    SESSION_START = "SessionStart"       # session initialization: can inject context or stop
    STOP = "Stop"                       # task completion: can block (force continue) or allow
    PRE_COMPACT = "PreCompact"          # before compaction: can stop compaction
    POST_COMPACT = "PostCompact"        # after compaction: can stop


# ═══════════════════════════
# Hook result types
# ═══════════════════════════

class HookDecision(enum.Enum):
    """Outcome of a single hook execution."""
    ALLOW = "allow"          # proceed normally
    DENY = "deny"            # block the action
    STOP = "stop"            # stop current task/turn
    BLOCK = "block"          # block completion (force continue — Stop event only)


class HookResult:
    """Structured result from a single hook."""
    __slots__ = ("decision", "reason", "updated_input", "context_injections",
                 "feedback", "metadata")

    def __init__(
        self,
        decision: HookDecision = HookDecision.ALLOW,
        reason: str = "",
        updated_input: dict | None = None,
        context_injections: list[str] | None = None,
        feedback: str = "",
        metadata: dict | None = None,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.updated_input = updated_input
        self.context_injections = context_injections or []
        self.feedback = feedback
        self.metadata = metadata or {}

    @staticmethod
    def allow(
        context_injections: list[str] | None = None,
        feedback: str = "",
        updated_input: dict | None = None,
    ) -> "HookResult":
        return HookResult(
            decision=HookDecision.ALLOW,
            context_injections=context_injections or [],
            feedback=feedback,
            updated_input=updated_input,
        )

    @staticmethod
    def deny(reason: str) -> "HookResult":
        return HookResult(decision=HookDecision.DENY, reason=reason)

    @staticmethod
    def stop(reason: str = "") -> "HookResult":
        return HookResult(decision=HookDecision.STOP, reason=reason)

    @staticmethod
    def block(reason: str = "") -> "HookResult":
        return HookResult(decision=HookDecision.BLOCK, reason=reason)


# ═══════════════════════════
# Hook handler definition
# ═══════════════════════════

HookHandler = Callable[..., HookResult]
"""A hook handler is a callable that receives (state, event_data) and returns HookResult."""


class HookDefinition:
    """A registered hook with event binding and optional matcher."""

    __slots__ = ("event", "handler", "matcher", "priority", "hook_id")

    def __init__(
        self,
        event: HookEvent,
        handler: HookHandler,
        matcher: str | None = None,
        priority: int = 50,
        hook_id: str = "",
    ) -> None:
        self.event = event
        self.handler = handler
        self.matcher = matcher          # regex pattern for tool name / intent matching
        self.priority = priority        # lower = runs first
        self.hook_id = hook_id or f"{event.value}_{id(self)}"

    def matches(self, target: str = "") -> bool:
        """Check if this hook matches a target string (tool name, intent, etc.)."""
        if not self.matcher:
            return True
        try:
            return bool(re.search(self.matcher, target))
        except re.error:
            return False


# ═══════════════════════════
# Hook registry
# ═══════════════════════════

class HookRegistry:
    """Registry of hooks with event-based dispatch and result folding.

    Usage:
        registry = HookRegistry()
        registry.register(HookDefinition(
            HookEvent.PRE_TOOL_USE,
            my_pre_tool_handler,
            matcher="shell.*",
            priority=10,
        ))
        outcome = registry.run_hooks(HookEvent.PRE_TOOL_USE, state, {"tool_id": "shell.exec"})
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookDefinition]] = {e.value: [] for e in HookEvent}

    def register(self, hook: HookDefinition) -> None:
        """Register a hook definition."""
        self._hooks[hook.event.value].append(hook)
        self._hooks[hook.event.value].sort(key=lambda h: h.priority)

    def clear(self) -> None:
        """Remove all hooks."""
        for k in self._hooks:
            self._hooks[k].clear()

    def get_hooks(self, event: HookEvent) -> list[HookDefinition]:
        """Get all hooks registered for an event (sorted by priority)."""
        return self._hooks.get(event.value, [])

    def preview(self, event: HookEvent, target: str = "") -> list[str]:
        """Show which hooks will run for an event+target (for UI/debug)."""
        return [
            h.hook_id
            for h in self.get_hooks(event)
            if h.matches(target)
        ]

    def run_hooks(
        self,
        event: HookEvent,
        state,
        event_data: dict | None = None,
        target: str = "",
    ) -> "HookOutcome":
        """Run all matching hooks for an event and fold results.

        Returns a HookOutcome with the combined decision.
        """
        hooks = [h for h in self.get_hooks(event) if h.matches(target)]
        if not hooks:
            return HookOutcome.no_hooks()

        results: list[tuple[HookDefinition, HookResult]] = []
        for hook in hooks:
            try:
                result = hook.handler(state, event_data or {})
                if not isinstance(result, HookResult):
                    result = HookResult(decision=HookDecision.ALLOW)
                results.append((hook, result))
            except Exception as e:
                logger.warning("Hook %s raised exception: %s", hook.hook_id, e)
                results.append((hook, HookResult.deny(f"hook error: {e}")))

        return _fold_results(event, results)


# ═══════════════════════════
# Result folding (Codex's disjunctive pattern)
# ═══════════════════════════

class HookOutcome:
    """Combined outcome from all hooks for one event."""

    __slots__ = ("decision", "reason", "updated_input", "context_injections",
                 "feedback", "should_stop", "should_block", "run_count",
                 "deny_count", "stop_requests", "block_requests")

    def __init__(
        self,
        decision: HookDecision,
        reason: str = "",
        updated_input: dict | None = None,
        context_injections: list[str] | None = None,
        feedback: str = "",
        should_stop: bool = False,
        should_block: bool = False,
        run_count: int = 0,
        deny_count: int = 0,
        stop_requests: list[str] | None = None,
        block_requests: list[str] | None = None,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.updated_input = updated_input
        self.context_injections = context_injections or []
        self.feedback = feedback
        self.should_stop = should_stop
        self.should_block = should_block
        self.run_count = run_count
        self.deny_count = deny_count
        self.stop_requests = stop_requests or []
        self.block_requests = block_requests or []

    @staticmethod
    def no_hooks() -> "HookOutcome":
        return HookOutcome(decision=HookDecision.ALLOW, reason="no hooks registered")

    @property
    def is_allowed(self) -> bool:
        return self.decision == HookDecision.ALLOW

    @property
    def is_denied(self) -> bool:
        return self.decision == HookDecision.DENY


def _fold_results(
    event: HookEvent,
    results: list[tuple[HookDefinition, HookResult]],
) -> HookOutcome:
    """Fold individual hook results into a combined outcome.

    Codex semantics:
    - PreToolUse: any Deny wins immediately; last Allow's updated_input wins (completion order)
    - PostToolUse: any stop=true wins; feedback concatenated
    - PreTurn: any block=true wins; context_injections merged
    - PostTurn: any block=true wins; outputs collected
    - SessionStart: any stop=true wins; contexts merged
    - Stop: block overrides stop (force continue)
    """
    deny_count = 0
    deny_reasons: list[str] = []
    stop_requests: list[str] = []
    block_requests: list[str] = []
    context_injections: list[str] = []
    feedback_parts: list[str] = []
    last_updated_input: dict | None = None
    last_allow_idx: int = -1

    for i, (hook, result) in enumerate(results):
        if result.decision == HookDecision.DENY:
            deny_count += 1
            deny_reasons.append(f"{hook.hook_id}: {result.reason}")
            if event == HookEvent.PRE_TOOL_USE:
                # Any Deny wins immediately for PreToolUse
                return HookOutcome(
                    decision=HookDecision.DENY,
                    reason="; ".join(deny_reasons),
                    run_count=len(results),
                    deny_count=deny_count,
                    stop_requests=stop_requests,
                    block_requests=block_requests,
                )

        elif result.decision == HookDecision.STOP:
            stop_requests.append(f"{hook.hook_id}: {result.reason}")

        elif result.decision == HookDecision.BLOCK:
            block_requests.append(f"{hook.hook_id}: {result.reason}")

        elif result.decision == HookDecision.ALLOW:
            # Track last Allow for updated_input (completion order)
            if result.updated_input is not None:
                last_updated_input = result.updated_input
                last_allow_idx = i
            context_injections.extend(result.context_injections)
            if result.feedback:
                feedback_parts.append(result.feedback)

    # ── Fold semantics per event ──

    # PreToolUse: any Deny already returned early; remaining = Allow with last updated_input
    if event == HookEvent.PRE_TOOL_USE:
        return HookOutcome(
            decision=HookDecision.ALLOW,
            updated_input=last_updated_input,
            run_count=len(results),
            deny_count=deny_count,
            stop_requests=stop_requests,
        )

    # PostToolUse: any stop wins; feedback concatenated
    if event == HookEvent.POST_TOOL_USE:
        if stop_requests:
            return HookOutcome(
                decision=HookDecision.STOP,
                reason="; ".join(stop_requests),
                feedback="\n".join(feedback_parts),
                run_count=len(results),
                stop_requests=stop_requests,
                should_stop=True,
            )
        return HookOutcome(
            decision=HookDecision.ALLOW,
            feedback="\n".join(feedback_parts),
            run_count=len(results),
        )

    # PreTurn: any deny/block wins; context merged
    if event == HookEvent.PRE_TURN:
        if deny_count > 0:
            return HookOutcome(
                decision=HookDecision.DENY,
                reason="; ".join(deny_reasons),
                run_count=len(results),
                deny_count=deny_count,
            )
        if block_requests:
            return HookOutcome(
                decision=HookDecision.BLOCK,
                reason="; ".join(block_requests),
                context_injections=context_injections,
                run_count=len(results),
                block_requests=block_requests,
            )
        return HookOutcome(
            decision=HookDecision.ALLOW,
            context_injections=context_injections,
            run_count=len(results),
        )

    # PostTurn: any block wins (force continue); context merged
    if event == HookEvent.POST_TURN:
        if block_requests:
            return HookOutcome(
                decision=HookDecision.BLOCK,
                reason="; ".join(block_requests),
                context_injections=context_injections,
                run_count=len(results),
                block_requests=block_requests,
            )
        return HookOutcome(
            decision=HookDecision.ALLOW,
            context_injections=context_injections,
            run_count=len(results),
        )

    # SessionStart: any stop wins; context merged
    if event == HookEvent.SESSION_START:
        if stop_requests:
            return HookOutcome(
                decision=HookDecision.STOP,
                reason="; ".join(stop_requests),
                context_injections=context_injections,
                run_count=len(results),
                stop_requests=stop_requests,
                should_stop=True,
            )
        return HookOutcome(
            decision=HookDecision.ALLOW,
            context_injections=context_injections,
            run_count=len(results),
        )

    # Stop: block overrides stop
    if event == HookEvent.STOP:
        if block_requests:
            return HookOutcome(
                decision=HookDecision.BLOCK,
                reason="; ".join(block_requests),
                run_count=len(results),
                block_requests=block_requests,
                should_block=True,
            )
        if stop_requests:
            return HookOutcome(
                decision=HookDecision.STOP,
                reason="; ".join(stop_requests),
                run_count=len(results),
                stop_requests=stop_requests,
                should_stop=True,
            )
        return HookOutcome(
            decision=HookDecision.ALLOW,
            run_count=len(results),
        )

    # PreCompact / PostCompact: any stop wins
    if stop_requests:
        return HookOutcome(
            decision=HookDecision.STOP,
            reason="; ".join(stop_requests),
            run_count=len(results),
            stop_requests=stop_requests,
            should_stop=True,
        )
    return HookOutcome(
        decision=HookDecision.ALLOW,
        run_count=len(results),
    )
