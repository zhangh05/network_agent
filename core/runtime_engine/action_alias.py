"""
Canonical action alias normalization for SSOT Runtime — single source of truth.

Both the GraphCompiler (compile-time) and the PreExecutionRepairEngine
(runtime fallback) resolve planner-side action aliases through the
single ``resolve_action_alias()`` entry point defined here. Adding a
new alias = one entry in ``CANONICAL_ALIASES_BY_TOOL`` (or in
``EXTENDED_RUNTIME_ALIAS_MAP`` in ``pre_execution_repair.py`` ONLY when
the alias is genuinely transient — see "Drift discipline" below).

The resolution contract:

  resolve_action_alias(tool_id, action) -> AliasResolution
    .matched             — True if action was rewritten from a known alias
    .original_action     — the action string the caller passed in
    .canonical_action    — the rewritten token (== original when no rewrite)
    .operation           — secondary "operation" hint, e.g. "get_history" for
                            ``session_get``. Always None when the alias is
                            a pure synonym.
    .source              — "canonical" | "extended" | "none"
                            "canonical" — resolved through this module
                            "extended"  — resolved through the runtime
                                           fallback in
                                           pre_execution_repair.EXTENDED_*
                            "none"      — no rewrite; original is left alone

Drift discipline:

  * All *stable* aliases (LLM terminology we have observed in
    production and want to keep supporting for the foreseeable
    future) MUST live in ``CANONICAL_ALIASES_BY_TOOL`` /
    ``CANONICAL_ALIASES_GLOBAL``.
  * Aliases that should only exist for a short window (transient
    LLM drift, hotfix for one specific operator output) belong in
    ``pre_execution_repair.EXTENDED_RUNTIME_ALIAS_MAP`` and should
    be promoted to the canonical table once the LLM side stabilizes.
  * ``test_alias_drift`` enforces that no alias lives in BOTH
    tables — the canonical table always wins.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Final


# ── Resolution result ──────────────────────────────────────────────────

# Allowed values for ``AliasResolution.source``.
SOURCE_CANONICAL: Final[str] = "canonical"
SOURCE_EXTENDED: Final[str] = "extended"
SOURCE_NONE: Final[str] = "none"

VALID_SOURCES: Final[frozenset[str]] = frozenset(
    {SOURCE_CANONICAL, SOURCE_EXTENDED, SOURCE_NONE}
)


@dataclass
class AliasResolution:
    """The single result type returned by ``resolve_action_alias()``."""

    matched: bool = False
    original_action: str = ""
    canonical_action: str = ""
    operation: str | None = None
    source: str = SOURCE_NONE
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── Canonical alias tables ─────────────────────────────────────────────
# Single source of truth. ``GraphCompiler`` consults this on every node
# during Phase 1 (alias rewrite BEFORE semantic validation runs).
# ``PreExecutionRepairEngine`` consults this first, and only falls
# back to its own ``EXTENDED_RUNTIME_ALIAS_MAP`` when no entry here
# matches.

# Per-tool alias map. Values are ``(canonical_action, operation)`` —
# ``operation`` is propagated into ``node.args["operation"]`` when
# present so the downstream tool receives the intent hint.
CANONICAL_ALIASES_BY_TOOL: Final[dict[str, dict[str, tuple[str, str | None]]]] = {
    # system.manage — keep the alias surface flat so the planner can
    # emit the colloquial form without us mutating the canonical enum
    # declared in ``contracts.py``.
    "system.manage": {
        # session — current canonical action is session_get. Keep
        # colloquial aliases pointing at that token; do not rewrite
        # canonical session_get back to the removed "session" action.
        "get_session": ("session_get", "get_history"),
        "session_history": ("session_get", "get_history"),
        "history_get": ("session_get", "get_history"),
        "session_list": ("session_get", "list"),
        "list_sessions": ("session_get", "list"),

        # review / audit / tasks
        "review_get": ("review_list", "get"),
        "audit_get": ("audit_log", "get"),
        "task_get": ("tasks", "get"),
        "tasks_get": ("tasks", "get"),

        # run history
        "get_run": ("run_get", "get"),
        "run_list": ("run_get", "list"),
        "list_runs": ("run_get", "list"),

        # diagnostics / health / selfcheck (no operation hint — pure
        # synonyms)
        "self_check": ("selfcheck", None),
        "check_health": ("health", None),
        "do_diagnostics": ("diagnostics", None),
        "diag": ("diagnostics", None),
        "local_ip": ("local_info", None),
        "local_info": ("local_info", None),
        "host_info": ("local_info", None),
        "system_info": ("local_info", None),
    },

    "workspace.file": {
        "ls": ("list", None),
        "cat": ("read", None),
    },

    "knowledge.manage": {
        "knowledge_get": ("read", None),
        "knowledge_search": ("search", None),
        "knowledge_read": ("read", None),
        "read_knowledge": ("read", None),
        "knowledge_import": ("import", None),
        "import_knowledge": ("import", None),
        "find_knowledge": ("search", None),
        "search_knowledge": ("search", None),
    },

    "device.manage": {
        "device_get": ("get", None),
        "device_list": ("list", None),
        "list_devices": ("list", None),
        "get_device": ("get", None),
    },

    "agent.manage": {
        "agent_spawn": ("spawn", None),
        "agent_list": ("role_list", None),
    },

    "memory.manage": {
        "memory_search": ("search", None),
        "search_memory": ("search", None),
        "memory_create": ("create", None),
        "create_memory": ("create", None),
        "memory_delete": ("delete", None),
        "delete_memory": ("delete", None),
    },

    "web.manage": {
        "search_web": ("search", None),
        "web_search": ("search", None),
        "fetch_page": ("page", None),
    },

    "report.manage": {
        "render_report": ("markdown", None),
        "generate_report": ("markdown", None),
    },

    "inspection.manage": {
        "start_inspection": ("run", None),
        "run_inspection": ("run", None),
        "inspection_status": ("task_get", None),
        "inspection_result": ("wait", None),
        "wait_inspection": ("wait", None),
        "follow_inspection": ("wait", None),
        "inspection_report": ("report", None),
        "cancel_inspection": ("task_cancel", None),
    },
}

# Tool-agnostic aliases — apply regardless of which tool the planner
# was emitting. Use sparingly: a per-tool entry is almost always
# preferable.
CANONICAL_ALIASES_GLOBAL: Final[dict[str, tuple[str, str | None]]] = {}


# Canonical enum sets per tool — mirrors the ToolContract enums
# declared in ``contracts.py``. We hand-keep this map because
# reading enums out of JSON schema at import time would require
# jsonschema and slow down the hot path.
_CANONICAL_ACTIONS: Final[dict[str, frozenset[str]]] = {
    "system.manage": frozenset({
        "diagnostics", "health", "selfcheck", "local_info", "tasks", "audit_log",
        "run_get", "session_get", "session_checkpoint", "session_rewind",
        "session_export", "session_snapshot", "review_list", "review_update",
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
        "csv_summarize", "table_extract", "table_render", "validate", "filter", "deduplicate",
    }),
    "report.manage": frozenset({
        "markdown_render", "artifact_save", "safe_summary_render", "mermaid_render", "html_render", "diff_report",
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
    "inspection.manage": frozenset({
        "run", "task_list", "task_get", "wait", "task_cancel", "report",
    }),
}


# ── Unified resolution entry point ─────────────────────────────────────

def resolve_action_alias(
    tool_id: str, action: str | None
) -> AliasResolution:
    """Resolve ``action`` for ``tool_id`` against the canonical table.

    Behavior contract:

      * unknown / empty action → ``matched=False, source="none"``
      * action is an alias in either per-tool or global table
        → ``matched=True, source="canonical"`` with
        ``canonical_action`` rewritten and ``operation`` propagated
      * action is already a member of the tool's canonical enum
        → ``matched=False, source="canonical"`` (the caller treats
        this as "no rewrite needed")

    This function never raises. It is the single entry point used by
    BOTH ``GraphCompiler`` (compile-time) and
    ``PreExecutionRepairEngine`` (runtime fallback) — no other code
    path is allowed to implement its own alias lookup.
    """
    original = (action or "").strip() if isinstance(action, str) else ""
    if not original:
        return AliasResolution(
            matched=False,
            original_action=original,
            canonical_action="",
            operation=None,
            source=SOURCE_NONE,
        )

    # 1. Already canonical — no rewrite needed. This check intentionally
    # runs before alias lookup because a token can be both a historical alias
    # and the current canonical action after a hard-cut rename.
    if original in _CANONICAL_ACTIONS.get(tool_id, frozenset()):
        return AliasResolution(
            matched=False,
            original_action=original,
            canonical_action=original,
            operation=None,
            source=SOURCE_CANONICAL,
        )

    # 2. Per-tool table.
    by_tool = CANONICAL_ALIASES_BY_TOOL.get(tool_id) or {}
    if original in by_tool:
        canonical, op = by_tool[original]
        return AliasResolution(
            matched=True,
            original_action=original,
            canonical_action=canonical,
            operation=op,
            source=SOURCE_CANONICAL,
        )

    # 3. Tool-agnostic table.
    if original in CANONICAL_ALIASES_GLOBAL:
        canonical, op = CANONICAL_ALIASES_GLOBAL[original]
        return AliasResolution(
            matched=True,
            original_action=original,
            canonical_action=canonical,
            operation=op,
            source=SOURCE_CANONICAL,
        )

    # 4. Not found anywhere — let the semantic validator reject it.
    return AliasResolution(
        matched=False,
        original_action=original,
        canonical_action=original,
        operation=None,
        source=SOURCE_NONE,
    )


# ── Backward-compatible helpers ────────────────────────────────────────

def normalize_action_alias(action: str | None) -> tuple[str | None, str | None]:
    """Legacy 2-tuple return — kept for callers that only need the
    ``(canonical_or_None, original_or_None)`` pair.

    Looks up ``action`` against BOTH the global table and every
    per-tool table (the tool-agnostic legacy callers don't know
    which tool emitted the action).

    Convention (matches the pre-v3.10 callers):
      * alias hit      → ``(canonical, original)``
      * already canonical OR unknown → ``(key, None)``
        The caller treats ``original is None`` as "no rewrite needed";
        the semantic validator still rejects truly unknown actions
        via the canonical-enum check.

    Use the new ``resolve_action_alias(tool_id, action)`` form when
    you need per-tool resolution or the ``source`` field.
    """
    if not action:
        return None, action
    key = str(action).strip()
    if not key:
        return None, action
    # Global first.
    if key in CANONICAL_ALIASES_GLOBAL:
        canonical, _op = CANONICAL_ALIASES_GLOBAL[key]
        return canonical, key
    # Then per-tool — first match wins.
    for table in CANONICAL_ALIASES_BY_TOOL.values():
        if key in table:
            canonical, _op = table[key]
            return canonical, key
    # Not in any alias table — return as-is. Callers distinguish
    # "already canonical" from "unknown" via subsequent checks
    # (canonical_actions_for_tool / is_known_action).
    return key, None


def is_known_action(action: str | None) -> bool:
    """Cheap predicate: alias OR canonical (any tool) would pass."""
    if not action:
        return False
    if action in CANONICAL_ALIASES_GLOBAL:
        return True
    for by_tool in CANONICAL_ALIASES_BY_TOOL.values():
        if action in by_tool:
            return True
    for actions in _CANONICAL_ACTIONS.values():
        if action in actions:
            return True
    return False


def canonical_actions_for_tool(tool_id: str) -> frozenset[str]:
    """Return canonical action set for a tool (empty if unknown)."""
    return _CANONICAL_ACTIONS.get(tool_id, frozenset())


# ── Helpers for the drift test ─────────────────────────────────────────

def iter_canonical_aliases() -> list[tuple[str, str, str, str | None]]:
    """Yield ``(tool_id, alias, canonical, operation)`` tuples from
    the canonical tables (per-tool + global). The global entries
    come back with ``tool_id == "*"``."""
    out: list[tuple[str, str, str, str | None]] = []
    for tool_id, table in CANONICAL_ALIASES_BY_TOOL.items():
        for alias, (canonical, op) in table.items():
            out.append((tool_id, alias, canonical, op))
    for alias, (canonical, op) in CANONICAL_ALIASES_GLOBAL.items():
        out.append(("*", alias, canonical, op))
    return out


def all_canonical_alias_keys() -> set[str]:
    """Flat set of every alias key (regardless of tool) — used by the
    drift test to compare with the extended table."""
    keys: set[str] = set()
    for table in CANONICAL_ALIASES_BY_TOOL.values():
        keys.update(table.keys())
    keys.update(CANONICAL_ALIASES_GLOBAL.keys())
    return keys


# ── Backward-compat flat alias map ──────────────────────────────────────

def _build_flat_aliases() -> dict[str, str]:
    """Flatten per-tool + global alias tables into a single
    ``alias -> canonical`` dict. Kept around for legacy callers
    (semantic_validator, harness tests) that still read the
    original ``ACTION_ALIASES`` symbol. New code should call
    ``resolve_action_alias(tool_id, action)`` instead.
    """
    out: dict[str, str] = {}
    for table in CANONICAL_ALIASES_BY_TOOL.values():
        for alias, (canonical, _op) in table.items():
            out[alias] = canonical
    for alias, (canonical, _op) in CANONICAL_ALIASES_GLOBAL.items():
        out[alias] = canonical
    return out


# Frozen at import time — the canonical tables are declared
# ``Final`` so this is stable for the lifetime of the process.
ACTION_ALIASES: Final[dict[str, str]] = _build_flat_aliases()
