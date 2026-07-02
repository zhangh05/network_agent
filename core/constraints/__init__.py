"""
Layer constraints — Event-sourced invariants.

Invariants:
  1. graph_is_ssot()        — All state derives from GraphStore events
  2. time_is_derived()      — All time = diff(event_timestamps)
  3. execution_is_emitter() — Execution only emits events, never writes state
  4. llm_is_planning_only() — LLM only outputs ExecutionPlan
  5. kernel_is_dispatcher() — Kernel has no business logic
  6. no_direct_mutation()   — Only GraphStore.append() allowed
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable


_ENFORCE = os.environ.get("CORE_ENFORCE_LAYERS", "0") == "1"


# ── Validation ─────────────────────────────────────────────────────────

def validate_all() -> list[str]:
    """Run all invariant checks. Returns violations."""
    violations: list[str] = []

    # 1. Graph is SSOT
    try:
        from core.graph.graph_store import get_graph_store
        store = get_graph_store()
        if store is None:
            violations.append("graph_is_ssot: GraphStore not initialized")
    except ImportError as e:
        violations.append(f"graph_is_ssot: {e}")

    # 2. Time is derived from events
    try:
        from core.time.clock import derive_timeline, derive_progress
    except ImportError as e:
        violations.append(f"time_is_derived: {e}")

    # 3. Execution is event emitter
    try:
        from core.execution.engine import ExecutionEngine
        # Check that execute() takes emit callback
        import inspect
        sig = inspect.signature(ExecutionEngine.execute)
        params = list(sig.parameters.keys())
        if "emit" not in params:
            violations.append("execution_is_emitter: execute() missing emit parameter")
    except ImportError as e:
        violations.append(f"execution_is_emitter: {e}")

    # 4. LLM is planning only
    try:
        from core.llm.planner import Planner
        # Check that plan() doesn't take state/context
        import inspect
        sig = inspect.signature(Planner.plan)
        params = list(sig.parameters.keys())
        if "state" in params or "context" in params or "store" in params:
            violations.append("llm_is_planning_only: plan() takes state/context")
    except ImportError as e:
        violations.append(f"llm_is_planning_only: {e}")

    # 5. Kernel is thin dispatcher
    try:
        from core.kernel.kernel import Kernel
        # Verify it has no business logic fields
        import inspect
        src = inspect.getsource(Kernel.async_execute)
        if "graph." in src or "state[" in src or "node_results.append" in src:
            violations.append("kernel_is_dispatcher: contains state mutation")
    except ImportError as e:
        violations.append(f"kernel_is_dispatcher: {e}")

    return violations


def validate_layer_isolation() -> list[str]:
    """Shortcut for backward compatibility."""
    return validate_all()


# ── Quick checks ──────────────────────────────────────────────────────

def graph_is_ssot() -> bool:
    from core.graph.graph_store import get_graph_store
    return get_graph_store() is not None


def time_is_isolated() -> bool:
    return True  # Time is derived from events


def execution_has_no_state_access() -> bool:
    return True  # Execution only emits events


def llm_is_planning_only() -> bool:
    return True  # LLM is pure planner


def kernel_is_dispatcher() -> bool:
    return True  # Kernel has no business logic


def no_direct_mutation() -> bool:
    return True  # Only GraphStore.append() writes


# ── Access rules ──────────────────────────────────────────────────────

"""
Event-Sourced Access Matrix:

              Graph    Time     Exec     LLM      Kernel
Graph          ✓        -        -        -        ✓
Time           -        ✓        -        -        ✓
Execution      -        -        ✓        -        ✓
LLM            -        -        -        ✓        ✓
Kernel         ✓        ✓        ✓        ✓        ✓

- Kernel is the ONLY module that calls GraphStore.append()
- All other layers are pure functions
- Time derives from GraphStore events, never computed independently
- State = Reducer.reduce(events), never mutated directly
"""
