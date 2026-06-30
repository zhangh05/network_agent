"""Review-fix contract for runtime command, trace, trajectory, and tool metadata.

Pins down current runtime contracts:

  1. ``TrajectoryRecord`` exposes a warnings list for degraded evaluations.
  2. Trace timestamps are timezone-aware ISO-8601 strings from ``now_iso()``.
  3. Slash-command reset/export uses module-level session-store functions.
  4. Tool embedding cache metadata is ISO-only; invalid cache files rebuild.

These tests walk a curated module set so they stay fast (we do NOT run
the full harness here).
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # portable: resolve from this test file


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _ast_parse(path: str) -> ast.AST:
    return ast.parse(_read(path))


def test_trajectory_warnings_field_exists():
    """TrajectoryRecord must carry a ``warnings`` list field — the
    build_trajectory() flow appends duration-calc / parsing failure
    messages there. Without the field, AttributeError breaks the
    trajectory evaluator.
    """
    tree = _ast_parse("agent/runtime/durable/trajectory.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TrajectoryRecord":
            for stmt in node.body:
                is_warnings = False
                type_is_list = False
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == "warnings":
                        is_warnings = True
                        if stmt.annotation and "list" in ast.unparse(stmt.annotation).lower():
                            type_is_list = True
                if is_warnings:
                    assert type_is_list, (
                        "TrajectoryRecord.warnings must be a list, not bare str/int"
                    )
                    return
            # fall-through: not found
            raise AssertionError(
                "TrajectoryRecord is missing a ``warnings: list[...]`` field; "
                "build_trajectory() will AttributeError"
            )
    raise AssertionError("TrajectoryRecord class not found")


def test_trace_finalize_uses_now_iso():
    """observability/trace.py:38 must call now_iso() for finished_at —
    every other writer in the runtime writes ISO strings.
    """
    src = _read("observability/trace.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # only catch ``time.strftime(...)`` called from real code, not
        # docstrings or comments
        if isinstance(node, ast.Call):
            fn = ast.unparse(node.func)
            if "time.strftime" in fn:
                raise AssertionError(
                    f"trace.py still calls time.strftime(...) at line "
                    f"{node.lineno}; use now_iso() instead"
                )
    assert "now_iso()" in src, "trace.py must use now_iso for finished_at"


def test_command_system_uses_module_level_session_functions():
    """agent/runtime/command_system.py must NOT execute the dead
    AgentSessionStore class import path. The slash reset / export
    bodies must use the module-level archive_session / get_session.
    """
    src = _read("agent/runtime/command_system.py")
    tree = ast.parse(src)
    bad: list[str] = []
    for node in ast.walk(tree):
        # Walk import-from statements; flag any ``from workspace.session_store
        # import AgentSessionStore``.
        if isinstance(node, ast.ImportFrom) and node.module == "workspace.session_store":
            for alias in node.names:
                if alias.name == "AgentSessionStore":
                    bad.append(f"L{node.lineno}: still imports AgentSessionStore")
    assert not bad, "command_system.py dead imports:\n  " + "\n  ".join(bad)
    # We expect the new helpers to actually be used.
    assert "from workspace.session_store import" in src
    assert "archive_session" in src
    assert "get_session" in src
    assert "workspace_id', 'default'" not in src
    assert 'workspace_id", "default"' not in src


def test_embeddings_built_at_is_iso():
    """tool_planning/embeddings.py must build _built_at via now_iso()
    and the cache load/age math must accept only ISO strings.
    """
    src = _read("agent/runtime/tool_planning/embeddings.py")
    assert "from agent.runtime.utils import now_iso, from_iso" in src, (
        "embeddings.py must import the unified timestamp helpers"
    )
    tree = ast.parse(src)
    # All places that assign to self._built_at must use now_iso() or
    # pass through a string-typed load() helper, never time.time().
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == "_built_at":
                    rhs = node.value
                    if isinstance(rhs, ast.Call):
                        fn = ast.unparse(rhs.func)
                        if "time.time" in fn:
                            raise AssertionError(
                                f"embeddings._built_at is still assigned via "
                                f"{fn}; use now_iso()"
                            )
    assert "float(built_at" not in src
    assert "float(self._built_at" not in src


def test_all_21_tools_have_not_for():
    """Every canonical tool's metadata must carry a non-empty
    ``not_for`` field so the LLM gets a real anti-pattern hint,
    not a default ``"Use X when specifically needed."`` fallback.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tool_runtime.tool_namespace import metadata_for_tool, TOOL_NAMESPACE
    empty = []
    for tid in sorted(TOOL_NAMESPACE):
        meta = metadata_for_tool(tid)
        n = (meta.get("not_for") or "").strip()
        if not n:
            empty.append(tid)
    assert not empty, (
        f"these canonical tools have empty not_for (LLM fallback): {empty}"
    )
