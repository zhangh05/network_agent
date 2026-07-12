# agent/runtime/actions/planner.py
"""ActionPlanner — converts raw tool_call to ActionPlan."""

from __future__ import annotations

import re
from typing import Any

from agent.runtime.actions.models import ActionRequest, ActionPlan


# ── Action class patterns (matched against tool_id) ─────────────────────

_CLASS_PATTERNS = [
    (re.compile(r"(shell|powershell|python|exec|spawn|run|slash)", re.I), "execute"),
    (re.compile(r"(delete|remove|drop|destroy|purge|rewind|checkpoint)", re.I), "mutate"),
    (re.compile(r"(write|save|create|add|insert|update|modify|edit|patch|set|put|upload|push|append|commit|render|tag|export|reindex|import|redirect|confirm)", re.I), "write"),
    (re.compile(r"(read|list|search|get|fetch|query|find|show|view|describe|cat|head|tail|ls|dir|stat|download|pull|status|diff|log|check|navigate|screenshot|click|extract|validate|summarize|weather|classify|keywords|explain|redact|profile|inspect|load|catalog|role|results?|checkpoints?|snapshots?)", re.I), "read"),
    (re.compile(r"(http|api|webhook|external|remote|curl|wget|request)", re.I), "external"),
]


def _classify_action(tool_id: str, arguments: dict | None = None) -> str:
    """Classify action based on tool_id + (for merged tools) arguments.action.

    Merged tools like ``device.manage`` / ``agent.manage`` use a single
    canonical id and dispatch by ``arguments.action``. To classify them
    correctly we build a pseudo tool_id that concatenates the action
    name so the regex patterns above can match. For non-merged tools
    the action suffix is empty and behaviour matches the original
    tool_id-only classification.
    """
    args = arguments or {}
    action = str(args.get("action", "")).lower().strip()

    # For merged tools (those with an action param), check the capability
    # manifest first.  The manifest's ``action_class`` is the canonical
    # declaration and must take precedence over heuristic regex matching.
    # This prevents false classification — e.g. ``inspection.manage run``
    # contains the substring "run" but the manifest correctly declares
    # ``action_class="read"`` (all inspection commands are read-only).
    if action:
        try:
            from core.tools.manifest_registry import get_manifest  # noqa: F811
            manifest = get_manifest(tool_id)
            if manifest and isinstance(getattr(manifest, "action_class", ""), str) and manifest.action_class:
                return manifest.action_class
        except Exception:
            pass

    pseudo = f"{tool_id} {action}".strip()
    for pattern, cls in _CLASS_PATTERNS:
        if pattern.search(pseudo):
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
        action_class = _classify_action(tool_id, arguments)
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
