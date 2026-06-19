# agent/runtime/actions/planner.py
"""ActionPlanner — converts raw tool_call to ActionPlan."""

from __future__ import annotations

import re
from typing import Any, Optional

from agent.runtime.actions.models import ActionRequest, ActionPlan


# ── Action class patterns (matched against tool_id) ─────────────────────

_CLASS_PATTERNS = [
    (re.compile(r"(shell|powershell|python|exec)", re.I), "execute"),
    (re.compile(r"(delete|remove|drop|destroy|purge)", re.I), "mutate"),
    (re.compile(r"(write|save|create|add|insert|update|modify|edit|patch|set|put|upload|push|append)", re.I), "write"),
    (re.compile(r"(read|list|search|get|fetch|query|find|show|view|describe|cat|head|tail|ls|dir|stat|download|pull)", re.I), "read"),
    (re.compile(r"(http|api|webhook|external|remote|curl|wget|request)", re.I), "external"),
]


def _classify_action(tool_id: str) -> str:
    """Classify action based on tool_id patterns."""
    for pattern, cls in _CLASS_PATTERNS:
        if pattern.search(tool_id):
            return cls
    return "unknown"


def _detect_argument_sources(arguments: dict, tool_id: str) -> dict:
    """Identify source of each argument (literal / user_input / context / generated)."""
    sources = {}
    for key, val in arguments.items():
        if isinstance(val, str) and len(val) > 200:
            sources[key] = "generated"
        elif isinstance(val, str):
            sources[key] = "literal"
        else:
            sources[key] = "literal"
    return sources


class ActionPlanner:
    """Convert a raw tool_call dict into an ActionPlan."""

    def plan(self, tool_call_id: str, tool_name: str, tool_id: str,
             arguments: dict, turn_id: str = "", raw_call: Any = None,
             context: Any = None) -> ActionPlan:
        """Build an ActionPlan from a tool call."""
        action_class = _classify_action(tool_id)
        argument_sources = _detect_argument_sources(arguments, tool_id)

        plan = ActionPlan(
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_id=tool_id,
            arguments=dict(arguments),
            action_class=action_class,
            argument_sources=argument_sources,
        )
        return plan
