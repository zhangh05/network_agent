"""
Budget Controller for SSOT Runtime Engine.

Per-request execution budget enforced at every stage:
  - LLM call timeout
  - Tool execution timeout
  - Max tool calls and parallel width
  - Max LLM calls

Budget violations MUST fail fast — never allow the system to hang.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import ExecutionBudget, SSOTRuntimeConfig


@dataclass
class BudgetStatus:
    """Current budget consumption status."""
    ok: bool = True
    exceeded: str = ""
    elapsed_total_ms: float = 0.0
    llm_calls_used: int = 0


class BudgetController:
    """Enforces execution budget across all pipeline stages."""

    def __init__(self, config: SSOTRuntimeConfig | None = None):
        cfg = config or SSOTRuntimeConfig()
        self._budget = ExecutionBudget(
            max_total_seconds=cfg.max_total_seconds,
            max_planner_seconds=cfg.planner_timeout_ms // 1000,
            max_tool_seconds=cfg.max_tool_seconds,
            max_nodes=cfg.max_nodes,
            max_depth=cfg.max_depth,
            max_parallel_width=cfg.max_layer_concurrency,
            max_llm_calls=cfg.max_llm_calls,
        )
        self._start_time = time.monotonic()
        self._llm_calls = 0

    @property
    def budget(self) -> ExecutionBudget:
        return self._budget

    def check_planner(self) -> BudgetStatus:
        """Check budget before planner call."""
        elapsed = (time.monotonic() - self._start_time) * 1000
        limit_ms = self._budget.max_planner_seconds * 1000
        if elapsed > limit_ms:
            return BudgetStatus(ok=False, exceeded="PLANNER_TIMEOUT", elapsed_total_ms=elapsed)
        return BudgetStatus(ok=True, elapsed_total_ms=elapsed)

    def check_llm_call(self) -> BudgetStatus:
        """Check budget before an LLM call. Inspect limits first, only
        increment the counter when the call is permitted."""
        elapsed = (time.monotonic() - self._start_time) * 1000
        total_limit_ms = self._budget.max_total_seconds * 1000

        if elapsed > total_limit_ms:
            return BudgetStatus(
                ok=False, exceeded="TOTAL_TIME_EXCEEDED",
                elapsed_total_ms=elapsed, llm_calls_used=self._llm_calls,
            )

        if self._llm_calls >= self._budget.max_llm_calls:
            return BudgetStatus(
                ok=False, exceeded="LLM_CALLS_EXCEEDED",
                elapsed_total_ms=elapsed, llm_calls_used=self._llm_calls,
            )

        self._llm_calls += 1
        return BudgetStatus(ok=True, elapsed_total_ms=elapsed, llm_calls_used=self._llm_calls)

    def check_execution(self) -> BudgetStatus:
        """Check budget mid-execution."""
        elapsed = (time.monotonic() - self._start_time) * 1000
        total_limit_ms = self._budget.max_total_seconds * 1000
        tool_limit_ms = self._budget.max_tool_seconds * 1000

        if elapsed > total_limit_ms:
            return BudgetStatus(ok=False, exceeded="TOTAL_TIME_EXCEEDED", elapsed_total_ms=elapsed)
        if elapsed > tool_limit_ms:
            return BudgetStatus(ok=False, exceeded="TOOL_TIME_EXCEEDED", elapsed_total_ms=elapsed)

        return BudgetStatus(ok=True, elapsed_total_ms=elapsed)

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._start_time) * 1000

    @property
    def llm_calls(self) -> int:
        return self._llm_calls
