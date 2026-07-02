"""
Kernel — Thin dispatcher.

Rules:
  - No business logic
  - No state manipulation
  - No timing computation
  - ONLY routing: LLM → Execution → Graph

  Kernel.execute(task):
    → LLM.plan(task)           # pure event
    → ExecutionEngine.run()    # pure events
    → Graph.apply(events)      # SSOT store
    → return project()         # derived state

All state = GraphStore.project(run_id)
All time  = derive_timeline(events)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from core.graph.graph_store import (
    get_graph_store, GraphStore, EventType, Reducer,
)
from core.time.clock import derive_timeline, derive_node_timings, derive_progress
from core.execution.engine import (
    ExecutionEngine, ExecutionPlan, ToolResult,
)
from core.llm.planner import Planner, PlannerOutput


# ── Kernel result (pure projection) ────────────────────────────────────

@dataclass
class KernelResult:
    """Derived from events, not stored directly."""
    run_id: str
    ok: bool
    final_response: str
    node_count: int
    tool_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stage_timings: dict[str, int] = field(default_factory=dict)
    total_elapsed_ms: int = 0
    approval_required: bool = False
    approval_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "ok": self.ok,
            "final_response": self.final_response,
            "node_count": self.node_count,
            "tool_results": self.tool_results,
            "errors": self.errors,
            "stage_timings": self.stage_timings,
            "total_elapsed_ms": self.total_elapsed_ms,
            "approval_required": self.approval_required,
            "approval_nodes": self.approval_nodes,
        }


# ── Kernel ─────────────────────────────────────────────────────────────

class Kernel:
    """Thin dispatcher. No business logic.

    LLM → Execution → Graph → Projection
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
        self._store = get_graph_store()

    def register_tool(self, name: str, handler: Callable,
                      description: str = "", args: dict | None = None) -> None:
        self._planner.register_tool(name, description, args)
        self._executor.register(name, handler)

    # ── Entry point ──────────────────────────────────────────────

    def execute(
        self,
        task_input: str,
        workspace_id: str = "default",
        session_id: str = "",
        approved_risk: bool = False,
    ) -> KernelResult:
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
        """Execute task through pure event pipeline."""
        store = self._store
        run_id = f"run_{task_input[:20].replace(' ', '_')}"

        # ── Emit helper (the ONE write path) ────────────────────
        def emit(et: str, rid: str, payload: dict | None = None) -> None:
            store.append(et, rid, payload)

        # ── 1. RUN_STARTED ──────────────────────────────────────
        emit(EventType.RUN_CREATED, run_id, {
            "input": task_input, "workspace_id": workspace_id,
        })
        emit(EventType.RUN_STARTED, run_id, {})

        # ── 2. Planner (LLM) ────────────────────────────────────
        emit(EventType.STAGE_STARTED, run_id, {"stage": "planner"})

        plan_output = self._planner.plan(task_input)

        if not plan_output.nodes:
            emit(EventType.STAGE_ENDED, run_id, {"stage": "planner"})
            emit(EventType.FINAL_RESPONSE, run_id, {
                "text": plan_output.final_response or "收到。",
            })
            emit(EventType.RUN_COMPLETED, run_id, {})
            return _project_result(run_id, store)

        # Plan generated
        emit(EventType.PLAN_GENERATED, run_id, {
            "nodes": plan_output.nodes,
            "node_count": len(plan_output.nodes),
        })
        emit(EventType.STAGE_ENDED, run_id, {"stage": "planner"})

        # ── 3. Compile ──────────────────────────────────────────
        emit(EventType.STAGE_STARTED, run_id, {"stage": "compile"})
        plan = ExecutionPlan.from_plan_dicts(plan_output.nodes)
        emit(EventType.STAGE_ENDED, run_id, {"stage": "compile"})

        # ── 4. Validate ─────────────────────────────────────────
        emit(EventType.STAGE_STARTED, run_id, {"stage": "structural_validate"})
        validation_errors = self._planner.validate(plan_output)
        if validation_errors:
            emit(EventType.PLAN_INVALID, run_id, {
                "errors": validation_errors,
            })
            emit(EventType.RUN_FAILED, run_id, {})
            return _project_result(run_id, store)
        emit(EventType.PLAN_VALIDATED, run_id, {"node_count": len(plan_output.nodes)})
        emit(EventType.STAGE_ENDED, run_id, {"stage": "structural_validate"})

        # ── 5. Risk policy ──────────────────────────────────────
        emit(EventType.STAGE_STARTED, run_id, {"stage": "risk_policy"})

        if self._risk_check and not approved_risk:
            risk_result = self._risk_check(plan_output.nodes)
            risk_level = risk_result.get("risk_level", "low")
            emit(EventType.RISK_ASSESSED, run_id, {
                "risk_level": risk_level,
                "hard_block": risk_result.get("hard_block", False),
            })

            if risk_result.get("hard_block"):
                emit(EventType.RUN_FAILED, run_id, {
                    "reason": risk_result.get("reason", "hard blocked"),
                })
                return _project_result(run_id, store)

            if risk_result.get("requires_approval"):
                nodes = risk_result.get("approval_nodes", [])
                emit(EventType.APPROVAL_REQUIRED, run_id, {"nodes": nodes})
                emit(EventType.STAGE_ENDED, run_id, {"stage": "risk_policy"})
                emit(EventType.RUN_COMPLETED, run_id, {})
                return _project_result(run_id, store)

        emit(EventType.STAGE_ENDED, run_id, {"stage": "risk_policy"})

        # ── 6. Execute ──────────────────────────────────────────
        tool_results = await self._executor.execute(
            plan, run_id, emit,
        )

        # ── 7. Finalize ─────────────────────────────────────────
        emit(EventType.STAGE_STARTED, run_id, {"stage": "finalizer"})
        if self._finalize:
            final_text = self._finalize(plan_output, tool_results)
        else:
            final_text = _build_default_final(tool_results)
        emit(EventType.FINAL_RESPONSE, run_id, {"text": final_text})
        emit(EventType.STAGE_ENDED, run_id, {"stage": "finalizer"})

        # ── Done ────────────────────────────────────────────────
        emit(EventType.RUN_COMPLETED, run_id, {})
        return _project_result(run_id, store)

    # ── Query (pure projection from events) ─────────────────────

    def get_progress(self, run_id: str) -> dict[str, Any]:
        """Derive execution progress from events."""
        events = [e.to_dict() for e in self._store.get_events(run_id)]
        return derive_progress(events)

    def get_timeline(self, run_id: str) -> dict[str, Any]:
        """Derive timing from events."""
        events = [e.to_dict() for e in self._store.get_events(run_id)]
        return derive_timeline(events)

    def get_node_timings(self, run_id: str) -> dict[str, Any]:
        """Derive per-node timing from events."""
        events = [e.to_dict() for e in self._store.get_events(run_id)]
        return derive_node_timings(events)


# ── Helpers ────────────────────────────────────────────────────────────

def _project_result(run_id: str, store: GraphStore) -> KernelResult:
    """Build KernelResult from GraphStore projection. Pure derivation."""
    state = store.project(run_id)
    events = [e.to_dict() for e in store.get_events(run_id)]
    timeline = derive_timeline(events)

    return KernelResult(
        run_id=run_id,
        ok=state.get("status") == "done",
        final_response=state.get("final_response", ""),
        node_count=state.get("node_count", 0),
        tool_results=state.get("tool_results", {}),
        errors=state.get("errors", []),
        stage_timings=timeline.get("stage_timings", {}),
        total_elapsed_ms=timeline.get("total_elapsed_ms", 0),
        approval_required=state.get("approval_required", False),
        approval_nodes=state.get("approval_nodes", []),
    )


def _build_default_final(
    tool_results: dict[str, ToolResult],
) -> str:
    if not tool_results:
        return "收到。"
    ok_count = sum(1 for tr in tool_results.values() if tr.success)
    fail_count = len(tool_results) - ok_count
    lines = []
    for nid, tr in tool_results.items():
        status = "✓" if tr.success else "✗"
        summary = str(tr.data)[:200] if tr.data else (tr.error or "—")
        lines.append(f"  [{status}] {nid}: {summary}")
    return f"工具执行完成：成功 {ok_count} 个，失败 {fail_count} 个。\n" + "\n".join(lines)


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
