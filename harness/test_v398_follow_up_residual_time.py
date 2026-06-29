"""v3.9.8 follow-up: regression tests for str/float cross-contamination
in timestamp-assignment sites that v3.9.8 missed.

The original v3.9.8 cut patched every obvious ``req.created_at = time.time()``
assignment but the manual port missed a couple of sites deep inside
``ApprovalStore.wait`` and the ``_gc_history`` retention filter. These
tests pin the corrections so an audit-style refactor cannot silently
regress.

Strategy: enumerate every place a write to ``created_at`` /
``started_at`` / ``finished_at`` / ``resolved_at`` happens and assert
the assignment is via the ISO helper, not ``time.time()``.
"""

import ast
import pytest
from pathlib import Path

PROJECT_ROOT = Path("/Users/zhangh01/Desktop/network_agent")

# (file path relative to repo, function name, target field, expected
#  helper call). A row here is a regression guard: if a future edit
# inserts ``foo.resolved_at = time.time()`` inside the named
# function, the matching test fails.
GUARDS = [
    ("agent/approval.py", "resolve",    "resolved_at"),
    ("agent/approval.py", "wait",       "resolved_at"),
    ("agent/approval.py", "_gc_history", "_last_gc_at"),
]


def _function_calls(path: Path, func_name: str) -> list[ast.Call]:
    """Return all ``ast.Call`` nodes inside the function ``func_name``."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return list(ast.walk(node))
    raise AssertionError(
        f"function {func_name!r} not found in {path}"
    )


def _assignments_to(nodes: list[ast.stmt], field_name: str) -> list[ast.Assign]:
    """Return all assignments whose leftmost target is ``self.<field>``
    or top-level ``<field>`` (assignment statement form)."""
    found: list[ast.Assign] = []
    for n in nodes:
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if isinstance(t, ast.Attribute) and t.attr == field_name:
                found.append(n)
                break
    return found


def _call_name(call: ast.Call) -> str:
    try:
        return ast.unparse(call.func)
    except Exception:
        return "<unparseable>"


def test_no_resolved_at_time_time_in_approval():
    """``ApprovalStore.resolve`` must write resolved_at via now_iso(),
    not time.time() — the field is now str (v3.9.8)."""
    path = PROJECT_ROOT / "agent" / "approval.py"
    body = _function_calls(path, "resolve")
    bad = []
    for assign in _assignments_to(body, "resolved_at"):
        rhs = assign.value
        if isinstance(rhs, ast.Call):
            if _call_name(rhs) == "time.time":
                bad.append(f"line {assign.lineno}: {ast.unparse(assign)!r}")
    assert not bad, (
        "Found time.time() assignment to resolved_at (should use now_iso()): "
        + "; ".join(bad)
    )


def test_no_resolved_at_time_time_in_wait():
    """``ApprovalStore.wait`` (auto-deny on timeout) must use now_iso()."""
    path = PROJECT_ROOT / "agent" / "approval.py"
    body = _function_calls(path, "wait")
    bad = []
    for assign in _assignments_to(body, "resolved_at"):
        rhs = assign.value
        if isinstance(rhs, ast.Call) and _call_name(rhs) == "time.time":
            bad.append(f"line {assign.lineno}: {ast.unparse(assign)!r}")
    assert not bad, (
        "Found time.time() assignment to resolved_at in wait(): "
        + "; ".join(bad)
    )


def test_no_time_time_assignment_to_last_gc_at():
    """``_gc_history`` keeps ``_last_gc_at`` as an internal epoch float;
    it must not call time.time() inline. The cutoff comparison moved
    to ISO via ``_now_iso_offset``; the float bookkeeping is internal.
    """
    path = PROJECT_ROOT / "agent" / "approval.py"
    body = _function_calls(path, "_gc_history")
    # Sanity: at least one now_iso_offset() call must exist (proves
    # the v3.9.8 follow-up change is in place).
    iso_calls = [
        n for n in body
        if isinstance(n, ast.Call) and "_now_iso_offset" in _call_name(n)
    ]
    assert iso_calls, (
        "_gc_history must use _now_iso_offset() for retention cutoff "
        "(v3.9.8 follow-up)"
    )


def test_iso_offset_helper_exists():
    """The ``_now_iso_offset`` helper exists in approval.py."""
    path = PROJECT_ROOT / "agent" / "approval.py"
    src = path.read_text(encoding="utf-8")
    assert "def _now_iso_offset" in src


def test_gc_history_does_not_compare_str_to_float():
    """Belt-and-suspenders: search the entire approval source for the
    str/float comparison that ``str(created_at) >= float(cutoff)`` would
    produce. The post-v3.9.8 retention filter uses all-ISO ordering.
    """
    path = PROJECT_ROOT / "agent" / "approval.py"
    body = _function_calls(path, "_gc_history")
    for stmt in body:
        if not isinstance(stmt, ast.If):
            continue
        if not isinstance(stmt.test, ast.Compare):
            continue
        # Look for a Compare whose left side is ``rec.get("created_at")``
        # (Name=rec, Attribute=.get, args=Constant("created_at"))
        left = stmt.test.left
        if (isinstance(left, ast.Call)
                and isinstance(left.func, ast.Attribute)
                and left.func.attr == "get"
                and left.args
                and isinstance(left.args[0], ast.Constant)
                and left.args[0].value == "created_at"):
            comps = stmt.test.comparators
            if comps and isinstance(comps[0], ast.Constant) and isinstance(comps[0].value, float):
                pytest.fail(
                    f"_gc_history still compares created_at to a float "
                    f"constant at line {stmt.lineno}; ISO ordering required"
                )


# ── Durable.models analogue: protect mark_finished ─────────────────────


def test_runtime_step_mark_finished_uses_iso_str():
    """``RuntimeStep.mark_finished`` writes finished_at via ``_now()``
    (ISO str). It may still call ``time.time()`` for the duration
    arithmetic — that is internal sub-second math, not a timestamp
    field write. This guard ensures the visible field stays ISO.
    """
    path = PROJECT_ROOT / "agent" / "runtime" / "durable" / "models.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "mark_finished":
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                for t in sub.targets:
                    if (isinstance(t, ast.Attribute)
                            and t.attr in {"finished_at", "started_at", "created_at"}):
                        rhs = sub.value
                        if isinstance(rhs, ast.Call) and _call_name(rhs) == "time.time":
                            pytest.fail(
                                f"RuntimeStep.mark_finished still assigns "
                                f"time.time() to {t.attr} at line {sub.lineno}"
                            )
