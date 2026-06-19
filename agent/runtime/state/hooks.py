# agent/runtime/state/hooks.py
"""Runtime state hooks for wiring task workflow state into each turn."""

from __future__ import annotations

from dataclasses import asdict

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

    resolver = RuntimeStateResolver()
    state = resolver.resolve(ctx)

    detector = TaskDetector()
    signal = detector.detect(getattr(ctx, "user_input", ""), ctx=ctx, state=state)
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
    """Apply ActionExecutionKernel metadata to the current step and snapshot state."""
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
    """Return a compact runtime-state block for safe context / prompt renderers."""
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
        lines.append(f"Pending approvals: {len(pending)}. Do not repeat high-risk actions until approved.")
    return "\n".join(x for x in lines if x)[:1500]
