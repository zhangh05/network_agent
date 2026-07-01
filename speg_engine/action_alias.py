"""
Canonical action alias normalization for SPEG.

LLM planners occasionally emit aliases for canonical action names
(e.g. ``session_get`` for the canonical ``session``, ``get_session``
or ``history_get``). They cannot be folded into the tool contract's
enum without distorting the canonical surface, so we normalize them
at the GraphCompiler — strictly BEFORE semantic validation runs.

Canonical surface stays exactly as declared in ``tool_contract``
(enums in ``contracts.py``); this module only maps known aliases to
that surface so:

  1. ``contracts.py`` enum stays canonical (no junk entries)
  2. ``semantic_validator._validate_args`` continues to enforce
     the canonical enum strictly (post-normalization)
  3. ``risk_policy`` / ``audit`` / ``trace`` surface the
     ``action_original`` / ``action_normalized`` pair so the
     downstream stack can audit the planner's terminology drift
     without mis-attributing it.

Adding a new alias = single line in ``ACTION_ALIASES``. No contract
mutation, no validator regression risk.
"""

from __future__ import annotations

from typing import Final


# Canonical aliases — extended as the planner produces new ones.
# Keys: legacy / colloquial names emitted by LLMs.
# Values: canonical token matched by ToolContract.input_schema["action"]["enum"].
ACTION_ALIASES: Final[dict[str, str]] = {
    # system.manage — session
    "session_get": "session",
    "get_session": "session",
    "session_history": "session",
    "history_get": "session",
    "session_list": "session",
    "list_sessions": "session",
    # workspace.file — list/read variants
    "ls": "list",
    "cat": "read",
    # knowledge.manage — read variants
    "knowledge_get": "read",
    "knowledge_search": "search",
    # device.manage — get/list variants
    "device_get": "get",
    "device_list": "list",
    # agent.manage
    "agent_spawn": "spawn",
    "agent_list": "role_list",
}


def normalize_action_alias(action: str | None) -> tuple[str | None, str | None]:
    """Return ``(canonical_or_None, original_or_None)``.

    * If ``action`` is a known alias, returns the canonical token and
      the original string (so downstream layers can record
      ``action_original=...``/``action_normalized=...``).
    * If ``action`` is already canonical (one of the canonical
      tokens), returns ``(action, None)`` — caller treats the
      second slot as "no normalization happened".
    * If ``action`` is unknown / None, returns ``(None, action)`` —
      the caller leaves the value alone and lets the semantic
      validator reject it via the canonical-enum check.

    The function never raises — it is hot-path on every node of
    every DAG.
    """
    if not action:
        return None, action
    key = str(action).strip()
    canonical = ACTION_ALIASES.get(key)
    if canonical is not None:
        return canonical, key
    # Already canonical? Caller decides; we return (action, None).
    return key, None


def is_known_action(action: str | None) -> bool:
    """Cheap predicate: alias OR canonical would pass through."""
    if not action:
        return False
    return action in ACTION_ALIASES or _is_canonical_known(action)


# Canonical enum sets per tool — mirrors the ToolContract enums
# declared in ``contracts.py``. We hand-keep this map because
# reading enums out of JSON schema at import time would require
# jsonschema and slow down the hot path.
_CANONICAL_ACTIONS: Final[dict[str, frozenset[str]]] = {
    "system.manage": frozenset({
        "diagnostics", "health", "selfcheck", "tasks",
        "audit", "run", "session", "review",
    }),
    "workspace.file": frozenset({
        "list", "read", "read_image", "edit", "patch",
        "write_artifact", "glob", "delete_file",
    }),
    "knowledge.manage": frozenset({
        "search", "read", "import", "source_manage",
        "source_reindex", "source_list", "chunk_list",
        "not_found_explain",
    }),
    "device.manage": frozenset({
        "list", "get", "add", "delete", "update", "export",
    }),
    "agent.manage": frozenset({
        "role_list", "spawn", "team_run", "result_get",
    }),
    "git.manage": frozenset({
        "status", "diff", "log", "commit", "push", "branch", "checkout",
    }),
    "browser.manage": frozenset({
        "navigate", "extract", "screenshot", "click", "fill",
    }),
    "web.manage": frozenset({"search", "weather", "page"}),
    "data.manage": frozenset({
        "csv", "table", "validate", "filter", "deduplicate",
    }),
    "report.manage": frozenset({
        "markdown", "artifact", "summary", "mermaid", "html", "diff",
    }),
    "text.analyze": frozenset({
        "redact", "diff", "keywords", "classify",
        "extract_entities", "regex",
    }),
    "memory.manage": frozenset({
        "search", "create", "update", "confirm", "delete",
        "profile_get", "profile_set",
    }),
    "session.manage": frozenset({
        "parse", "session", "filter", "align",
    }),
}


def _is_canonical_known(action: str) -> bool:
    for actions in _CANONICAL_ACTIONS.values():
        if action in actions:
            return True
    return False


def canonical_actions_for_tool(tool_id: str) -> frozenset[str]:
    """Return canonical action set for a tool (empty if unknown)."""
    return _CANONICAL_ACTIONS.get(tool_id, frozenset())
