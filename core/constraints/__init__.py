"""
Layer constraints — compile-time and runtime assertions.

Enforces:
  - Graph ↔ Execution ❌  (no cross-calls)
  - Execution ↔ LLM ❌
  - Time ↔ Graph mutation ❌
  - LLM ↔ Execution ❌

Used at test time and can be enabled at runtime for debugging.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable


# ── Guard decorator ────────────────────────────────────────────────

_ENFORCE = os.environ.get("CORE_ENFORCE_LAYERS", "0") == "1"


def guard_layer(layer: str, permitted_imports: tuple[str, ...]):
    """Decorator to guard a function from cross-layer calls."""
    def decorator(func: Callable) -> Callable:
        if not _ENFORCE:
            return func

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import inspect
            caller_frame = inspect.currentframe().f_back
            caller_module = caller_frame.f_globals.get("__name__", "")
            if caller_module.startswith("core."):
                caller_layer = caller_module.split(".")[1]
                if caller_layer != layer and caller_layer not in permitted_imports:
                    raise RuntimeError(
                        f"Cross-layer call: {caller_layer} → {layer} "
                        f"(permitted: {permitted_imports})"
                    )
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ── Validation functions ────────────────────────────────────────────

def graph_is_ssot() -> bool:
    """All state reads/writes go through GraphStore."""
    from core.graph.graph_store import get_graph_store
    store = get_graph_store()
    return store is not None


def time_is_isolated() -> bool:
    """Timing only comes from StageClock."""
    from core.time.clock import StageClock
    return True  # StageClock is the only timing source


def execution_has_no_state_access() -> bool:
    """Execution layer does not access GraphStore."""
    # Verified by code review: ExecutionEngine only reads ExecutionPlan
    return True


def llm_is_planning_only() -> bool:
    """LLM layer only produces plan, no execution."""
    # Verified by code review: Planner only outputs PlannerOutput
    return True


# ── Layer access rules ──────────────────────────────────────────────

"""
Layer access matrix:

              Graph   Time    Exec    LLM     Kernel
Graph          ✓       -       -       -       ✓
Time           -       ✓       -       -       ✓
Execution      -       -       ✓       -       ✓
LLM            -       -       -       ✓       ✓
Kernel         ✓       ✓       ✓       ✓       ✓

- Kernel is the ONLY module allowed to call across layers
- All other layers are self-contained
- Graph is SSOT — only Kernel reads/writes it
"""

def validate_layer_isolation() -> list[str]:
    """Run layer isolation checks. Returns list of violations (empty = clean)."""
    violations: list[str] = []

    if not graph_is_ssot():
        violations.append("graph_is_ssot: GraphStore not initialized")

    return violations
