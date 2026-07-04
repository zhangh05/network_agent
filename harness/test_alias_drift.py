"""
Alias drift tests — enforce the single-source-of-truth contract for
SSOT Runtime action alias normalization.

Background: the v3.10 alias pipeline has two tables:

  1. ``core.runtime_engine.action_alias.CANONICAL_ALIASES_BY_TOOL`` /
     ``CANONICAL_ALIASES_GLOBAL`` — the *single source of truth* for
     every stable alias. GraphCompiler and PreExecutionRepairEngine
     both call ``resolve_action_alias(tool_id, action)`` which reads
     this table.

  2. ``core.runtime_engine.pre_execution_repair.EXTENDED_RUNTIME_ALIAS_MAP``
     — runtime fallback ONLY. Holds transient aliases (drift we
     still see from one specific LLM but haven't promoted yet).

These tests enforce the discipline:

  * Stable aliases (declared in spec) must resolve through the
    canonical source with ``source == "canonical"``.
  * Any alias defined in the extended table is still recognized at
    runtime (so transient drift doesn't break production).
  * No alias may live in BOTH tables — that is the drift symptom we
    are trying to prevent. The canonical table always wins; if the
    same key is in the extended table, the runtime will quietly hit
    canonical first and the extended entry is dead code.
  * Every extended entry must surface ``source == "extended"`` in
    the emitted ``RepairEvent`` so audit can spot drift.
"""

from __future__ import annotations

import pytest


# ── Spec-required stable aliases ────────────────────────────────────────

SPEC_STABLE_ALIASES: list[tuple[str, str, str, str | None]] = [
    # (tool_id, alias, expected canonical, expected operation)
    ("system.manage", "get_session", "session_get", "get_history"),
    ("system.manage", "review_get", "review_list", "get"),
    ("system.manage", "audit_get", "audit_log", "get"),
    ("system.manage", "get", "tasks", "get"),
]


# ── Drift Test 1: spec-required aliases resolve through canonical ──────

def test_spec_stable_aliases_resolve_via_canonical():
    """Every alias the spec lists as 'must work' must hit the
    canonical table with source=canonical and the right operation."""
    from core.runtime_engine.action_alias import (
        resolve_action_alias,
        SOURCE_CANONICAL,
    )
    for tool_id, alias, canonical, op in SPEC_STABLE_ALIASES:
        res = resolve_action_alias(tool_id, alias)
        assert res.matched is True, f"{alias} not matched for {tool_id}"
        assert res.source == SOURCE_CANONICAL, (
            f"{alias} should resolve via canonical, got {res.source}"
        )
        assert res.canonical_action == canonical, (
            f"{alias} → expected canonical {canonical!r}, got {res.canonical_action!r}"
        )
        assert res.operation == op, (
            f"{alias} → expected op {op!r}, got {res.operation!r}"
        )


# ── Drift Test 2: every extended alias is recognized at runtime ───────

def test_every_extended_alias_is_recognized_at_runtime():
    """Whatever survives in the extended fallback table must
    actually fire at runtime — otherwise the entry is dead code
    and a drift smell on its own."""
    from core.runtime_engine.pre_execution_repair import EXTENDED_RUNTIME_ALIAS_MAP
    from core.runtime_engine.action_alias import (
        resolve_action_alias,
        SOURCE_CANONICAL,
    )

    # Build a list of (alias, canonical, op) from the extended table.
    extended_entries = list(EXTENDED_RUNTIME_ALIAS_MAP.items())
    assert extended_entries, "extended table is empty — promote everything to canonical"

    for alias, (canonical, op) in extended_entries:
        # The extended table is tool-agnostic. We probe it via
        # PreExecutionRepairEngine so the assertion matches the
        # runtime path the engine actually uses.
        from core.runtime_engine.pre_execution_repair import (
            PreExecutionRepairEngine, RepairEvent,
        )
        # Synthesize a minimal node object that has the attributes
        # the policy reads (tool + args).
        node = type("N", (), {
            "tool": "workspace.file",   # arbitrary; the extended
                                          # table is tool-agnostic
            "args": {"action": alias},
            "id": "t",
        })()
        engine = PreExecutionRepairEngine()
        ev = RepairEvent(node_id="t")
        ok = engine._repair_action_alias(node, ev)
        assert ok is True, (
            f"extended alias {alias!r} did not fire at runtime — "
            f"remove it from EXTENDED_RUNTIME_ALIAS_MAP"
        )
        assert ev.normalized_action == canonical, (
            f"extended alias {alias!r} normalized to {ev.normalized_action!r}, "
            f"expected {canonical!r}"
        )
        assert ev.source == "extended", (
            f"extended alias {alias!r} must surface source='extended', "
            f"got {ev.source!r}"
        )


# ── Drift Test 3: no alias may live in BOTH tables ─────────────────────

def test_no_alias_defined_in_both_canonical_and_extended():
    """If the same alias key is in both tables, the canonical
    resolver hits first and the extended entry is dead. That is
    the drift symptom we are explicitly preventing."""
    from core.runtime_engine.action_alias import all_canonical_alias_keys
    from core.runtime_engine.pre_execution_repair import EXTENDED_RUNTIME_ALIAS_MAP

    canonical_keys = all_canonical_alias_keys()
    extended_keys = set(EXTENDED_RUNTIME_ALIAS_MAP.keys())

    overlap = canonical_keys & extended_keys
    assert not overlap, (
        "Alias drift detected — these keys live in BOTH the "
        "canonical table and the extended runtime fallback. "
        "The canonical resolver hits first, so the extended entry "
        "is dead code. Pick one:\n"
        "  - If the alias is stable: keep canonical, remove extended.\n"
        "  - If the alias is transient: remove canonical, keep extended "
        "(but then it isn't truly 'transient').\n"
        f"  Overlapping keys: {sorted(overlap)}"
    )


# ── Drift Test 4: source field is set correctly in every path ─────────

def test_source_field_semantics():
    """The ``source`` field on AliasResolution is part of the
    public contract — drift tests must lock it down."""
    from core.runtime_engine.action_alias import (
        resolve_action_alias,
        SOURCE_CANONICAL,
        SOURCE_NONE,
    )
    # matched canonical alias
    res = resolve_action_alias("system.manage", "get_session")
    assert res.source == SOURCE_CANONICAL
    assert res.matched is True

    # already canonical → matched=False but source=canonical
    res = resolve_action_alias("system.manage", "session_get")
    assert res.source == SOURCE_CANONICAL
    assert res.matched is False
    assert res.canonical_action == "session_get"

    # unknown action → source=none
    res = resolve_action_alias("system.manage", "delete_system")
    assert res.source == SOURCE_NONE
    assert res.matched is False

    # empty / None action → source=none
    for empty in ("", None):
        res = resolve_action_alias("system.manage", empty)
        assert res.source == SOURCE_NONE
        assert res.matched is False


# ── Drift Test 5: GraphCompiler and PreExecutionRepair share the same
#                       resolve_action_alias entry point. ────────────────

def test_graph_compiler_and_repair_use_same_resolver():
    """Both modules import ``resolve_action_alias`` from the
    canonical source. Direct alias table access in either module
    is forbidden — this test catches a regression where someone
    re-introduces a private alias dict."""
    import core.runtime_engine.graph_compiler as gc
    import core.runtime_engine.pre_execution_repair as per

    # The graph compiler module should not define its own alias
    # table — it should only import from action_alias.
    src_gc = open(gc.__file__).read()
    assert "ACTION_ALIASES_BY_TOOL" not in src_gc, (
        "GraphCompiler must not declare its own alias table; "
        "use action_alias.resolve_action_alias()"
    )
    assert "CANONICAL_ALIASES_BY_TOOL" not in src_gc
    assert "EXTENDED_RUNTIME_ALIAS_MAP" not in src_gc

    # The repair module must call the shared resolver.
    src_per = open(per.__file__).read()
    assert "resolve_action_alias" in src_per, (
        "PreExecutionRepairEngine must consult "
        "action_alias.resolve_action_alias() before its own "
        "EXTENDED_RUNTIME_ALIAS_MAP"
    )
    # And it must still have the extended table (renamed).
    assert "EXTENDED_RUNTIME_ALIAS_MAP" in src_per


# ── Drift Test 6: extended map entries are marked transient ───────────

def test_extended_map_has_transient_only_audit():
    """The extended table is for transient aliases. A drift audit
    failure here means someone added a stable alias to the
    extended table instead of promoting it to canonical."""
    from core.runtime_engine.pre_execution_repair import EXTENDED_RUNTIME_ALIAS_MAP

    # The stable aliases the spec calls out must NOT be in the
    # extended table — they live in canonical only.
    spec_aliases = {a for _t, a, _c, _o in SPEC_STABLE_ALIASES}
    leaked = spec_aliases & set(EXTENDED_RUNTIME_ALIAS_MAP.keys())
    assert not leaked, (
        f"Spec-required stable aliases must live in canonical only; "
        f"found in extended: {sorted(leaked)}"
    )


# ── Drift Test 7: end-to-end — extended alias actually fires in engine ─

def test_extended_alias_fires_in_engine_pipeline():
    """Full engine.run on a workspace.file with the transient
    alias ``file_read`` must succeed and the repair event must
    surface source='extended'.

    We use ``asyncio.run()`` here instead of ``@pytest.mark.asyncio``
    because harness/conftest.py does not install the async hook
    (only core.runtime_engine/conftest.py does).
    """
    import asyncio
    import json
    from core.runtime_engine.engine import SSOTRuntimeEngine
    from core.runtime_engine.models import SSOTRuntimeConfig

    plan_json = json.dumps({"nodes": [
        {"id": "n1", "tool": "workspace.file",
         "args": {"action": "file_read", "path": "/tmp/x"}, "deps": []}
    ]})

    registry = {"workspace.file": {"description": "", "args_schema": {
        "required": ["action", "path"],
        "properties": {
            "action": {"type": "string", "enum": [
                "list", "read", "read_image", "edit", "patch",
                "write_artifact", "glob", "delete_file",
            ]},
            "path": {"type": "string"},
        },
    }}}

    async def handler(args):
        return f"read {args.get('path', '?')}"

    engine = SSOTRuntimeEngine(
        config=SSOTRuntimeConfig(enable_finalizer=False),
        llm_invoke=lambda **kw: plan_json,
        tool_registry=registry,
    )
    engine.register_tool("workspace.file", handler)

    result = asyncio.run(engine.run("read"))
    assert result.success, f"expected success, errors: {result.errors}"
    assert result.node_success_count == 1
    # file_read is in the extended table, NOT canonical → repair
    # engine must have fired.
    assert result.metadata.get("pre_exec_repair_applied") is True
    events = result.metadata.get("pre_exec_repair_events") or []
    assert events, "expected a pre_exec_repair_event for file_read"
    e0 = events[0]
    assert e0["original_action"] == "file_read"
    assert e0["normalized_action"] == "read"
    assert e0["source"] == "extended"
