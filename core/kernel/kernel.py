"""
Kernel — Thin dispatcher. Zero internal knowledge.

Rules:
  - No knowledge of execution internals
  - No state awareness
  - No routing decisions
  - ONLY forward: task → ExecutionEngine

  Kernel.execute(task):
    → build snapshot
    → LLM.plan(snapshot)
    → ExecutionEngine.execute(plan)
    → GraphStore.append(events)

All state = GraphStore.project(run_id)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from core.graph.graph_store import (
    get_graph_store, GraphStore, EventType,
)
from core.time.clock import RunTimeline, derive_progress, derive_node_timings
from core.execution.engine import (
    ExecutionEngine, ExecutionPlan, ToolResult,
)
from core.llm.planner import Planner, PlannerSnapshot, PlannerOutput


# ── Kernel result (pure projection) ────────────────────────────────────

@dataclass
class KernelResult:
    run_id: str
    ok: bool
    final_response: str
    node_count: int
    tool_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timeline: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    approval_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "ok": self.ok,
            "final_response": self.final_response,
            "node_count": self.node_count,
            "tool_results": self.tool_results,
            "errors": self.errors,
            "timeline": self.timeline,
            "approval_required": self.approval_required,
            "approval_nodes": self.approval_nodes,
        }


# ── Kernel ─────────────────────────────────────────────────────────────

class Kernel:
    """Thin dispatcher. Routes task → engine. No business logic."""

    def __init__(self, llm_invoke: Callable[..., str]):
        self._planner = Planner(llm_invoke=llm_invoke)
        self._store = get_graph_store()

    def execute(
        self,
        task_input: str,
        handlers: dict[str, Callable],
        tools: dict[str, dict] | None = None,
        workspace_id: str = "default",
        session_id: str = "",
        approved_risk: bool = False,
        risk_check: Callable | None = None,
        finalize_fn: Callable | None = None,
    ) -> KernelResult:
        return _run_async(self.async_execute(
            task_input, handlers, tools, workspace_id,
            session_id, approved_risk, risk_check, finalize_fn,
        ))

    async def async_execute(
        self,
        task_input: str,
        handlers: dict[str, Callable],
        tools: dict[str, dict] | None = None,
        workspace_id: str = "default",
        session_id: str = "",
        approved_risk: bool = False,
        risk_check: Callable | None = None,
        finalize_fn: Callable | None = None,
    ) -> KernelResult:
        """Execute task — pure forwarding, no business logic."""
        store = self._store
        tools = tools or {}
        import hashlib, uuid
        safe_prefix = hashlib.sha256(task_input.encode()).hexdigest()[:12]
        run_id = f"run_{safe_prefix}_{uuid.uuid4().hex[:8]}"

        def emit(et: str, rid: str, payload: dict | None = None) -> None:
            store.append(et, rid, payload)

        # 1. Run created
        emit(EventType.RUN_CREATED, run_id, {
            "input": task_input, "workspace_id": workspace_id,
        })
        emit(EventType.RUN_STARTED, run_id, {})

        # 2. Build snapshot (immutable at this point)
        snapshot = self._planner.build_snapshot(task_input, tools)

        # 3. Plan (LLM)
        emit(EventType.STAGE_STARTED, run_id, {"stage": "planner"})
        plan_output = self._planner.plan(snapshot)

        if not plan_output.nodes:
            emit(EventType.STAGE_ENDED, run_id, {"stage": "planner"})
            emit(EventType.FINAL_RESPONSE, run_id, {
                "text": plan_output.final_response or "收到。",
            })
            emit(EventType.RUN_COMPLETED, run_id, {})
            return _project(run_id, store)

        emit(EventType.PLAN_GENERATED, run_id, {
            "nodes": list(plan_output.nodes),
            "node_count": len(plan_output.nodes),
        })
        emit(EventType.STAGE_ENDED, run_id, {"stage": "planner"})

        # 4. Compile
        emit(EventType.STAGE_STARTED, run_id, {"stage": "compile"})
        plan = ExecutionPlan.from_plan_dicts(list(plan_output.nodes))
        emit(EventType.STAGE_ENDED, run_id, {"stage": "compile"})

        # 5. Validate
        emit(EventType.STAGE_STARTED, run_id, {"stage": "structural_validate"})
        validation_errors = self._planner.validate(plan_output)
        if validation_errors:
            emit(EventType.PLAN_INVALID, run_id, {"errors": validation_errors})
            emit(EventType.RUN_FAILED, run_id, {})
            return _project(run_id, store)
        emit(EventType.PLAN_VALIDATED, run_id, {"node_count": len(plan_output.nodes)})
        emit(EventType.STAGE_ENDED, run_id, {"stage": "structural_validate"})

        # 6. Risk
        emit(EventType.STAGE_STARTED, run_id, {"stage": "risk_policy"})
        if risk_check and not approved_risk:
            risk_result = risk_check(list(plan_output.nodes))
            emit(EventType.RISK_ASSESSED, run_id, {
                "risk_level": risk_result.get("risk_level", "low"),
            })
            if risk_result.get("hard_block"):
                emit(EventType.RUN_FAILED, run_id, {
                    "reason": risk_result.get("reason", "hard blocked"),
                })
                return _project(run_id, store)
            if risk_result.get("requires_approval"):
                nodes = risk_result.get("approval_nodes", [])
                emit(EventType.APPROVAL_REQUIRED, run_id, {"nodes": nodes})
                emit(EventType.STAGE_ENDED, run_id, {"stage": "risk_policy"})
                emit(EventType.RUN_COMPLETED, run_id, {})
                return _project(run_id, store)
        emit(EventType.STAGE_ENDED, run_id, {"stage": "risk_policy"})

        # 7. Execute — forward to stateless engine
        tool_results = await ExecutionEngine.execute(
            plan, run_id, emit, handlers,
        )

        # 8. Finalize
        emit(EventType.STAGE_STARTED, run_id, {"stage": "finalizer"})
        final_text = (
            finalize_fn(plan_output, tool_results) if finalize_fn
            else _build_default_final(tool_results)
        )
        emit(EventType.FINAL_RESPONSE, run_id, {"text": final_text})
        emit(EventType.STAGE_ENDED, run_id, {"stage": "finalizer"})

        # Done
        emit(EventType.RUN_COMPLETED, run_id, {})
        return _project(run_id, store)

    # ── Queries (pure event projections) ──────────────────────────

    def get_progress(self, run_id: str) -> dict[str, Any]:
        return derive_progress([e.to_dict() for e in self._store.get_events(run_id)])

    def get_timeline(self, run_id: str) -> dict[str, Any]:
        events = [e.to_dict() for e in self._store.get_events(run_id)]
        return RunTimeline.compute(events).to_dict()

    def get_node_timings(self, run_id: str) -> dict[str, dict[str, Any]]:
        return derive_node_timings([e.to_dict() for e in self._store.get_events(run_id)])


# ── Helpers (pure) ─────────────────────────────────────────────────────

def _project(run_id: str, store: GraphStore) -> KernelResult:
    state = store.project(run_id)
    events = [e.to_dict() for e in store.get_events(run_id)]
    timeline = RunTimeline.compute(events)

    return KernelResult(
        run_id=run_id,
        ok=state.get("status") == "done",
        final_response=state.get("final_response", ""),
        node_count=state.get("node_count", 0),
        tool_results=state.get("tool_results", {}),
        errors=state.get("errors", []),
        timeline=timeline.to_dict(),
        approval_required=state.get("approval_required", False),
        approval_nodes=state.get("approval_nodes", []),
    )


def _build_default_final(results: dict[str, ToolResult]) -> str:
    if not results:
        return "收到。"
    ok_count = sum(1 for r in results.values() if r.success)
    fail_count = len(results) - ok_count
    lines = []
    for nid, tr in results.items():
        status = "✓" if tr.success else "✗"
        summary = str(tr.data)[:200] if tr.data else (tr.error or "—")
        lines.append(f"  [{status}] {nid}: {summary}")
    return f"工具执行完成：成功 {ok_count} 个，失败 {fail_count} 个。\n" + "\n".join(lines)


def _run_async(coro):
    """Run coroutine. If already in async context, raise — the caller
    MUST use ``await kernel.async_execute(...)`` directly to get a
    KernelResult.  Returning the unconsumed coroutine would silently
    break every caller that expects a synchronous KernelResult.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to run synchronously.
        return asyncio.run(coro)
    raise RuntimeError(
        "Kernel.execute() called from within an async event loop. "
        "Use `await kernel.async_execute(...)` instead."
    )
