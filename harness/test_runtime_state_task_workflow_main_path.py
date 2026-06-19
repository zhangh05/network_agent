"""Focused tests for runtime state / task workflow main-path wiring."""

from __future__ import annotations

from types import SimpleNamespace

from agent.runtime.state.hooks import prepare_runtime_state_for_turn, complete_runtime_state_after_actions
from agent.runtime.state.models import RuntimeState
from agent.runtime.state.store import RuntimeStateStore
from agent.runtime.tasking.detector import TaskDetector
from agent.runtime.tasking.models import TaskSignal, TaskPlan, WorkflowPlan, StepPlan, StepResult
from agent.runtime.state.transition import RuntimeStateTransition
from agent.runtime.tasking.step import StepExecutor


def make_ctx(text="整理这些资料，生成接口表，然后输出报告"):
    return SimpleNamespace(
        turn_id="turn_1",
        session_id="sess_1",
        workspace_id="ws_1",
        user_input=text,
        metadata={},
    )


def test_prepare_runtime_state_for_turn_creates_task_and_snapshot():
    ctx = make_ctx()
    session = SimpleNamespace(session_id="sess_1", workspace_id="ws_1", metadata={})

    state = prepare_runtime_state_for_turn(ctx, session=session)

    assert ctx.runtime_state is state
    assert state.active_task is not None
    assert state.active_workflow is not None
    assert ctx.metadata["task_signal"]["kind"] == "new_task"
    assert "current_step" in ctx.metadata
    assert "runtime_state_snapshot" in ctx.metadata
    assert "runtime_state_snapshot_summary" in ctx.metadata
    assert session.metadata["runtime_state"]


def test_store_loads_from_session_metadata_when_ctx_empty():
    ctx1 = make_ctx()
    session = SimpleNamespace(metadata={})
    state = RuntimeState()
    state.session.active_task_id = "task_1"
    RuntimeStateStore().save(ctx1, state, session=session)

    ctx2 = make_ctx()
    setattr(ctx2, "session", session)
    loaded = RuntimeStateStore().load(ctx2)

    assert loaded.session.active_task_id == "task_1"


def test_transition_apply_task_plan_sets_active_task_and_workflow():
    ctx = make_ctx()
    state = RuntimeState()
    task_plan = TaskPlan(task_id="task_1", title="整理资料", user_goal="整理资料", steps=["收集资料", "输出报告"])
    workflow_plan = WorkflowPlan(
        workflow_id="wf_1",
        task_id="task_1",
        steps=[
            StepPlan(step_id="step_1", task_id="task_1", title="收集资料", goal="收集资料", order=0),
            StepPlan(step_id="step_2", task_id="task_1", title="输出报告", goal="输出报告", order=1),
        ],
    )

    RuntimeStateTransition().apply_task_plan(state, task_plan, workflow_plan, ctx=ctx)

    assert state.active_task.task_id == "task_1"
    assert state.active_workflow.workflow_id == "wf_1"
    assert state.active_workflow.current_step_id == "step_1"
    assert state.active_workflow.steps[0].status == "running"
    assert ctx.metadata["task_plan"]["task_id"] == "task_1"


def test_prepare_current_step_writes_metadata():
    ctx = make_ctx()
    state = RuntimeState()
    task_plan = TaskPlan(task_id="task_1", title="整理资料", user_goal="整理资料", steps=["收集资料"])
    workflow_plan = WorkflowPlan(
        workflow_id="wf_1",
        task_id="task_1",
        steps=[StepPlan(step_id="step_1", task_id="task_1", title="收集资料", goal="收集资料", order=0)],
    )
    RuntimeStateTransition().apply_task_plan(state, task_plan, workflow_plan, ctx=ctx)

    step = StepExecutor().prepare_current_step(ctx, state)

    assert step.step_id == "step_1"
    assert ctx.metadata["current_step"]["step_id"] == "step_1"


def test_complete_runtime_state_after_actions_updates_step_and_snapshot():
    ctx = make_ctx()
    session = SimpleNamespace(metadata={})
    state = prepare_runtime_state_for_turn(ctx, session=session)
    step_id = state.active_workflow.current_step_id
    ctx.metadata["action_trace"] = [
        {"type": "result", "action_id": "a1", "tool_id": "workspace.file.read", "ok": True, "status": "success", "summary": "read ok"}
    ]
    ctx.metadata["action_evidence_updates"] = [{"action_id": "a1", "summary": "read ok"}]

    complete_runtime_state_after_actions(ctx, session=session)

    assert any(step.step_id == step_id and step.status == "completed" for step in state.active_workflow.steps)
    assert ctx.metadata["runtime_state_snapshot"]
    assert session.metadata["runtime_state"]


def test_cancel_task_pauses_not_fails():
    ctx = make_ctx()
    state = RuntimeState()
    task_plan = TaskPlan(task_id="task_1", title="整理资料", user_goal="整理资料", steps=["收集资料"])
    workflow_plan = WorkflowPlan(
        workflow_id="wf_1",
        task_id="task_1",
        steps=[StepPlan(step_id="step_1", task_id="task_1", title="收集资料", goal="收集资料", order=0)],
    )
    transition = RuntimeStateTransition()
    transition.apply_task_plan(state, task_plan, workflow_plan, ctx=ctx)
    transition.apply_cancel(state, TaskSignal(kind="cancel_task"), ctx=ctx)

    assert state.active_task.status == "paused"
    assert state.active_workflow.status == "paused"


def test_context_builder_and_tool_execution_pipeline_wire_state_hooks():
    from pathlib import Path

    context_builder = Path("agent/runtime/context_builder.py").read_text(encoding="utf-8")
    tool_pipeline = Path("agent/runtime/tool_execution/pipeline.py").read_text(encoding="utf-8")

    assert "prepare_runtime_state_for_turn" in context_builder
    assert "runtime_state_prompt_block" in context_builder
    assert "complete_runtime_state_after_actions" in tool_pipeline
