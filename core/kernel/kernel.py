"""
Kernel — Unified entry point for SPEG execution.

Orchestrates the four-layer pipeline:

  Kernel.execute(task)
    → LLM.plan(task)           # pure planning
    → ExecutionEngine.run()    # pure execution
    → GraphStore.update()      # SSOT state
    → StageClock.update()      # isolated timing

No cross-layer calls. No state in places it shouldn't be.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from core.graph.graph_store import get_graph_store, GraphStore
from core.time.clock import start_clock, remove_clock, StageClock
from core.time.clock import STAGE_DISPLAY
from core.execution.engine import (
    ExecutionEngine, ExecutionPlan, ToolResult as ExecToolResult,
)
from core.llm.planner import Planner, PlannerOutput


# ── Kernel result ─────────────────────────────────────────────────────

@dataclass
class KernelResult:
    """Unified result from Kernel.execute()."""
    run_id: str
    ok: bool
    final_response: str
    node_count: int            # real count, no padding
    tool_results: dict[str, ExecToolResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stage_timings: dict[str, int] = field(default_factory=dict)
    total_elapsed_ms: int = 0
    approval_required: bool = False
    approval_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "final_response": self.final_response,
            "node_count": self.node_count,
            "tool_results": {
                nid: tr.to_dict() for nid, tr in self.tool_results.items()
            },
            "errors": self.errors,
            "stage_timings": self.stage_timings,
            "total_elapsed_ms": self.total_elapsed_ms,
            "approval_required": self.approval_required,
            "approval_nodes": self.approval_nodes,
        }


# ── Kernel ────────────────────────────────────────────────────────────

class Kernel:
    """Unified SPEG execution kernel.

    Kernel.execute(task) → LLM → Execution → GraphStore → Clock
    """

    def __init__(
        self,
        llm_invoke: Callable[..., str],
        tool_handlers: dict[str, Callable] | None = None,
        risk_check: Callable | None = None,
        finalize_fn: Callable | None = None,
    ):
        self._planner = Planner(llm_invoke=llm_invoke)
        self._executor = ExecutionEngine(handlers=tool_handlers or {})
        self._risk_check = risk_check
        self._finalize = finalize_fn

    def register_tool(self, name: str, handler: Callable,
                      description: str = "", args: dict | None = None) -> None:
        """Register a tool with both the planner and executor."""
        self._planner.register_tool(name, description, args)
        self._executor.register(name, handler)

    def execute(
        self,
        task_input: str,
        workspace_id: str = "default",
        session_id: str = "",
        approved_risk: bool = False,
    ) -> KernelResult:
        """Execute a task through the full pipeline.

        Returns KernelResult synchronously (use async_execute for async).
        """
        return _run_async(self.async_execute(
            task_input, workspace_id, session_id, approved_risk,
        ))

    async def async_execute(
        self,
        task_input: str,
        workspace_id: str = "default",
        session_id: str = "",
        approved_risk: bool = False,
    ) -> KernelResult:
        """Async version of execute()."""
        store = get_graph_store()
        run_id = store.create_run(task_input, workspace_id, session_id)
        clock = start_clock(run_id)
        clock.begin_stage("entry")

        errors: list[str] = []

        # ── Stage 1: Planner (LLM) ─────────────────────────────
        clock.begin_next("planner")
        store.update_run(run_id, status="planning")
        store.append_event("stage", "planner_start", {
            "run_id": run_id, "input_len": len(task_input),
        })

        plan_output = self._planner.plan(task_input)

        clock.end_stage("planner")
        store.append_event("stage", "planner_end", {
            "node_count": len(plan_output.nodes),
        })

        # Direct response (no tools needed)
        if not plan_output.nodes:
            clock.begin_next("exit")
            clock.end_stage("exit")
            return KernelResult(
                run_id=run_id, ok=True,
                final_response=plan_output.final_response or "收到。",
                node_count=0,
                stage_timings={s: clock.elapsed(s) for s in clock.stages},
                total_elapsed_ms=clock.total_elapsed_ms(),
            )

        # ── Stage 2: Compile ──────────────────────────────────
        clock.begin_next("compile")
        store.update_run(run_id, plan_nodes=plan_output.nodes)
        plan = ExecutionPlan.from_plan_dicts(plan_output.nodes)
        clock.end_stage("compile")

        # ── Stage 3: Structural validation ────────────────────
        clock.begin_next("structural_validate")
        validation_errors = self._planner.validate(plan_output)
        clock.end_stage("structural_validate")

        if validation_errors:
            clock.begin_next("exit")
            clock.end_stage("exit")
            return KernelResult(
                run_id=run_id, ok=False,
                final_response="计划校验失败：" + "; ".join(validation_errors[:3]),
                node_count=len(plan_output.nodes),
                errors=validation_errors,
                stage_timings={s: clock.elapsed(s) for s in clock.stages},
                total_elapsed_ms=clock.total_elapsed_ms(),
            )

        # ── Stage 4: Risk policy ──────────────────────────────
        clock.begin_next("risk_policy")
        approval_required = False
        approval_nodes: list[str] = []

        if self._risk_check and not approved_risk:
            risk_result = self._risk_check(plan_output.nodes)
            if risk_result.get("hard_block"):
                errors.append(risk_result.get("reason", "操作被风险策略阻止"))
                clock.end_stage("risk_policy")
                clock.begin_next("exit")
                clock.end_stage("exit")
                return KernelResult(
                    run_id=run_id, ok=False,
                    final_response="操作被阻止：" + risk_result.get("reason", ""),
                    node_count=len(plan_output.nodes),
                    errors=errors,
                    stage_timings={s: clock.elapsed(s) for s in clock.stages},
                    total_elapsed_ms=clock.total_elapsed_ms(),
                )

            if risk_result.get("requires_approval"):
                approval_required = True
                approval_nodes = risk_result.get("approval_nodes", [])
                store.update_run(
                    run_id,
                    approval_required=True,
                    approval_nodes=approval_nodes,
                )

        clock.end_stage("risk_policy")

        # ── If approval required, return early ────────────────
        if approval_required:
            clock.begin_next("exit")
            clock.end_stage("exit")
            return KernelResult(
                run_id=run_id, ok=True,
                final_response="需要确认高危操作",
                node_count=len(plan_output.nodes),
                approval_required=True,
                approval_nodes=approval_nodes,
                stage_timings={s: clock.elapsed(s) for s in clock.stages},
                total_elapsed_ms=clock.total_elapsed_ms(),
            )

        # ── Stage 5: Execute ──────────────────────────────────
        clock.begin_next("execute")
        store.update_run(run_id, status="executing")

        tool_results = await self._executor.execute(
            plan,
            on_stage_begin=lambda s: store.append_event("stage", f"{s}_start", {}),
            on_stage_end=lambda s: store.append_event("stage", f"{s}_end", {}),
        )

        store.update_run(
            run_id,
            status="finalizing",
            node_results={
                nid: tr.to_dict() for nid, tr in tool_results.items()
            },
        )
        clock.end_stage("execute")

        # ── Stage 6: Finalizer ────────────────────────────────
        clock.begin_next("finalizer")
        final_response = ""
        if self._finalize:
            final_response = self._finalize(plan_output, tool_results)
        else:
            final_response = _build_default_final(tool_results)

        clock.end_stage("finalizer")

        # ── Done ──────────────────────────────────────────────
        clock.begin_next("exit")
        clock.end_stage("exit")

        ok = all(tr.success for tr in tool_results.values()) if tool_results else True

        result = KernelResult(
            run_id=run_id, ok=ok,
            final_response=final_response,
            node_count=len(plan_output.nodes),
            tool_results=tool_results,
            errors=errors,
            stage_timings={s: clock.elapsed(s) for s in clock.stages
                          if clock.stages[s].is_complete},
            total_elapsed_ms=clock.total_elapsed_ms(),
        )

        store.update_run(run_id, status="done", final_response=final_response)
        remove_clock(run_id)
        return result


# ── Helpers ───────────────────────────────────────────────────────────

def _build_default_final(
    tool_results: dict[str, ExecToolResult],
) -> str:
    """Build a default final response from tool results."""
    if not tool_results:
        return "收到。"

    ok_count = sum(1 for tr in tool_results.values() if tr.success)
    fail_count = len(tool_results) - ok_count

    lines = []
    for nid, tr in tool_results.items():
        status = "✓" if tr.success else "✗"
        summary = str(tr.data)[:200] if tr.data else (tr.error or "—")
        lines.append(f"  [{status}] {nid}: {summary}")

    header = f"工具执行完成：成功 {ok_count} 个，失败 {fail_count} 个。"
    return header + "\n" + "\n".join(lines)


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # We're already in an event loop — use run_until_complete on a new loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
