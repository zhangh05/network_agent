# agent/runtime/state/hooks.py
"""Runtime state hooks for wiring task workflow state into each turn."""

from __future__ import annotations

from agent.runtime.state.resolver import RuntimeStateResolver
from agent.runtime.state.snapshot import RuntimeStateSnapshotter
from agent.runtime.state.store import RuntimeStateStore
from agent.runtime.state.transition import RuntimeStateTransition
from agent.runtime.tasking.completion import CompletionEvaluator
from agent.runtime.tasking.detector import TaskDetector
from agent.runtime.tasking.planner import TaskPlanner
from agent.runtime.tasking.step import StepExecutor
from agent.runtime.tasking.workflow import WorkflowPlanner


def prepare_runtime_state_for_turn(ctx, session=None):
    """Resolve task workflow state and prepare the current step before prompting."""
    if session is not None:
        setattr(ctx, "session", session)

    state = RuntimeStateResolver().resolve(ctx)
    signal = TaskDetector().detect(getattr(ctx, "user_input", ""), ctx=ctx, state=state)
    ctx.metadata["task_signal"] = {
        "kind": signal.kind,
        "confidence": signal.confidence,
        "reason": signal.reason,
        "referenced_task_id": signal.referenced_task_id,
    }

    transition = RuntimeStateTransition()
    if signal.kind == "new_task":
        task_plan = TaskPlanner().plan(signal, getattr(ctx, "user_input", ""), ctx=ctx, state=state)
        if task_plan is not None:
            workflow_plan = WorkflowPlanner().build(task_plan, ctx=ctx, state=state)
            transition.apply_task_plan(state, task_plan, workflow_plan, ctx=ctx)
    elif signal.kind == "continue_task":
        transition.apply_continue(state, signal, ctx=ctx)
    elif signal.kind == "cancel_task":
        transition.apply_cancel(state, signal, ctx=ctx)

    StepExecutor().prepare_current_step(ctx, state)
    _snapshot_and_save(ctx, state, session=session)
    return state


def complete_runtime_state_after_actions(ctx, session=None):
    """Apply action metadata to the current step and snapshot state."""
    if session is not None:
        setattr(ctx, "session", session)

    state = getattr(ctx, "runtime_state", None)
    if state is None:
        state = RuntimeStateResolver().resolve(ctx)

    transition = RuntimeStateTransition()
    step_result = StepExecutor().apply_action_results(ctx, state)
    if step_result is not None:
        transition.apply_step_result(state, step_result, ctx=ctx)

    CompletionEvaluator().evaluate(ctx, state)

    _run_finalization_kernels(ctx)
    _snapshot_and_save(ctx, state, session=session)
    return state


def _snapshot_and_save(ctx, state, session=None):
    snapshot = RuntimeStateSnapshotter().snapshot(ctx, state)
    ctx.metadata["runtime_state_snapshot_summary"] = _snapshot_summary(snapshot)
    RuntimeStateStore().save(ctx, state, session=session)
    return snapshot


def _snapshot_summary(snapshot) -> str:
    active_task = snapshot.active_task_id or "none"
    active_step = snapshot.active_step_id or "none"
    return (
        f"active_task={active_task} "
        f"task_status={snapshot.task_status or 'none'} "
        f"active_step={active_step} "
        f"workflow_status={snapshot.workflow_status or 'none'} "
        f"progress={snapshot.progress_percent}% "
        f"pending_approvals={len(snapshot.pending_approvals or [])}"
    )[:1500]


def runtime_state_prompt_block(ctx) -> str:
    """Return a compact runtime-state block for safe context renderers."""
    snap = ctx.metadata.get("runtime_state_snapshot") or {}
    summary = ctx.metadata.get("runtime_state_snapshot_summary", "")
    current_step = ctx.metadata.get("current_step") or {}
    pending = ctx.metadata.get("pending_approvals") or []
    if not snap and not summary and not current_step:
        return ""
    lines = ["## Runtime State", summary]
    if current_step:
        lines.append(
            "Current step: "
            f"{current_step.get('step_id', '')} "
            f"{current_step.get('title', '')} "
            f"status={current_step.get('status', '')}"
        )
    if pending:
        lines.append(f"Pending approvals: {len(pending)}. Await approval before repeating gated actions.")
    return "\n".join(x for x in lines if x)[:1500]


def _run_finalization_kernels(ctx) -> None:
    """Run output/response/memory/observability/truth finalization kernels.

    Each kernel writes to ctx.metadata. Failures are swallowed to avoid
    breaking the main turn flow.
    """
    if ctx is None:
        return

    # Ensure action_trace key exists (no-tool turns produce empty list)
    ctx.metadata.setdefault("action_trace", [])

    # 1. Output Kernel: collect → plan → write → register → summarize
    try:
        from agent.runtime.output.collector import ResultCollector
        from agent.runtime.output.planner import ArtifactPlanner
        from agent.runtime.output.writer import ArtifactWriter
        from agent.runtime.output.registry import ArtifactRegistry
        from agent.runtime.output.summary import OutputSummarizer

        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        task_id = snap.get("active_task_id", "") if isinstance(snap, dict) else ""
        step_id = snap.get("active_step_id", "") if isinstance(snap, dict) else ""

        sources = ResultCollector().collect(ctx)
        plans = ArtifactPlanner().plan(sources, task_id=task_id, step_id=step_id)
        writer = ArtifactWriter()
        records = [writer.write(p, sources) for p in plans]
        ArtifactRegistry().register_all(ctx, records)
        OutputSummarizer().summarize(ctx, sources, records, task_id=task_id, step_id=step_id)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("output_kernel_failed")

    # 2. Response Composer
    try:
        from agent.runtime.response.composer import ResponseComposer
        ResponseComposer().compose(ctx)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("response_composer_failed")

    # 3. Memory Write Planner
    try:
        from agent.runtime.memory_write.planner import MemoryWritePlanner
        MemoryWritePlanner().plan(ctx)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("memory_write_planner_failed")

    # 4. Observability Collector
    try:
        from agent.runtime.observability.collector import ObservabilityCollector
        ObservabilityCollector().collect(ctx)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("observability_collector_failed")

    # 5. Truth Reporter
    try:
        from agent.runtime.truth.report import TruthReporter
        TruthReporter().report(ctx)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("truth_reporter_failed")

    # 6. Stability Gate
    try:
        from agent.runtime.stability.gate import StabilityGate
        StabilityGate().check(ctx)
    except Exception:
        ctx.metadata.setdefault("runtime_state_warnings", []).append("stability_gate_failed")
