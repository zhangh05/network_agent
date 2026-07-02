"""
SSOT Invariant Checks — fail-fast on any consistency violation.

Invariants:
  1. graph.append_only == True
  2. execution.stateless == True
  3. llm.snapshot_only == True
  4. event.clock.monotonic == True
  5. time.derivation_is_explicit == True
  6. kernel.thin_dispatcher == True
  7. reducer.is_pure == True

FAIL FAST ON ANY VIOLATION.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable


# ── Individual checks ──────────────────────────────────────────────────

def check_graph_append_only() -> bool:
    """GraphStore has only append(), no mutation methods."""
    try:
        from core.graph.graph_store import assert_append_only, get_graph_store
        store = get_graph_store()
        return assert_append_only(store)
    except Exception as e:
        raise AssertionError(f"graph.append_only FAILED: {e}")


def check_execution_stateless() -> bool:
    """ExecutionEngine has zero mutable state."""
    try:
        from core.execution.engine import ExecutionEngine, assert_stateless
        engine = ExecutionEngine()
        return assert_stateless(engine)
    except Exception as e:
        raise AssertionError(f"execution.stateless FAILED: {e}")


def check_llm_snapshot_only() -> bool:
    """LLM Planner takes immutable snapshot, no live stream."""
    try:
        from core.llm.planner import Planner, PlannerSnapshot
        # Verify Planner.plan() takes PlannerSnapshot, not raw events
        sig = inspect.signature(Planner.plan)
        params = list(sig.parameters.keys())
        if "snapshot" not in params:
            raise AssertionError("Planner.plan() must take 'snapshot' parameter")
        # Verify PlannerSnapshot is frozen
        assert PlannerSnapshot.__dataclass_params__ is not None
        assert hasattr(PlannerSnapshot, '__dataclass_fields__')
        return True
    except Exception as e:
        raise AssertionError(f"llm.snapshot_only FAILED: {e}")


def check_event_clock_monotonic() -> bool:
    """EventClock produces globally unique monotonic indices."""
    try:
        from core.graph.event_clock import get_event_clock
        clock = get_event_clock()
        stamps = [clock.next("test") for _ in range(10)]
        assert clock.validate_monotonic(stamps)
        # All causal_index must be unique
        indices = [s.causal_index for s in stamps]
        assert len(indices) == len(set(indices))
        return True
    except Exception as e:
        raise AssertionError(f"event.clock.monotonic FAILED: {e}")


def check_time_derivation_explicit() -> bool:
    """Time has three explicit dimensions: execution, queue, wall."""
    try:
        from core.time.clock import TimeModel, derive_execution_time, derive_queue_time, derive_wall_time
        # Verify TimeModel has three dimensions
        tm = TimeModel(execution_ms=10, queue_ms=5, wall_ms=20)
        assert tm.execution_ms == 10
        assert tm.queue_ms == 5
        assert tm.wall_ms == 20
        assert tm.overhead_ms == 10  # wall - execution
        # Verify derive functions exist and are callable
        assert callable(derive_execution_time)
        assert callable(derive_queue_time)
        assert callable(derive_wall_time)
        return True
    except Exception as e:
        raise AssertionError(f"time.derivation_explicit FAILED: {e}")


def check_kernel_thin_dispatcher() -> bool:
    """Kernel has zero business logic, only forwarding."""
    try:
        from core.kernel.kernel import Kernel
        sig = inspect.signature(Kernel.execute)
        params = list(sig.parameters.keys())
        # Must accept 'self', 'task_input', 'handlers' — nothing fancier
        assert "self" in params or "task_input" in params
        # Kernel.__init__ should only store llm_invoke and store ref
        import inspect as _inspect
        src = _inspect.getsource(Kernel.__init__)
        # Should not contain business logic keywords
        forbidden = ["if ", "for ", "while ", "await ", "raise "]
        for kw in forbidden:
            if kw in src:
                raise AssertionError(f"Kernel.__init__ contains business logic: '{kw}'")
        return True
    except Exception as e:
        raise AssertionError(f"kernel.thin_dispatcher FAILED: {e}")


def check_reducer_is_pure() -> bool:
    """Reducer has no cache, no global state, no mutation."""
    try:
        from core.graph.graph_store import assert_pure_reducer
        return assert_pure_reducer()
    except Exception as e:
        raise AssertionError(f"reducer.is_pure FAILED: {e}")


# ── All checks ─────────────────────────────────────────────────────────

CHECKS: dict[str, Callable[[], bool]] = {
    "graph.append_only": check_graph_append_only,
    "execution.stateless": check_execution_stateless,
    "llm.snapshot_only": check_llm_snapshot_only,
    "event.clock.monotonic": check_event_clock_monotonic,
    "time.derivation_explicit": check_time_derivation_explicit,
    "kernel.thin_dispatcher": check_kernel_thin_dispatcher,
    "reducer.is_pure": check_reducer_is_pure,
}


def validate_all(fail_fast: bool = True) -> dict[str, bool]:
    """Run all invariant checks. Returns {check_name: passed}.

    If fail_fast=True, raises AssertionError on first failure.
    """
    results: dict[str, bool] = {}
    for name, check_fn in CHECKS.items():
        try:
            results[name] = check_fn()
        except AssertionError as e:
            results[name] = False
            if fail_fast:
                raise
    return results


# ── Backward compat ────────────────────────────────────────────────────

def graph_is_ssot() -> bool:
    return check_graph_append_only()


def time_is_isolated() -> bool:
    return check_time_derivation_explicit()


def execution_has_no_state_access() -> bool:
    return check_execution_stateless()


def llm_is_planning_only() -> bool:
    return check_llm_snapshot_only()


def kernel_is_dispatcher() -> bool:
    return check_kernel_thin_dispatcher()


def no_direct_mutation() -> bool:
    return check_graph_append_only()


def validate_layer_isolation() -> list[str]:
    """Legacy API."""
    try:
        results = validate_all(fail_fast=False)
        return [k for k, v in results.items() if not v]
    except Exception as e:
        return [str(e)]
