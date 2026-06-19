"""Tests for Runtime State / Task Workflow Kernel.

Validates state models, task detection, planning, workflow building,
step execution, state transitions, completion evaluation, snapshot, and store.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.core.turn_context import TurnContext

# ── State model imports ─────────────────────────────────────────────────

from agent.runtime.state.models import (
    SessionState, WorkspaceState, ArtifactState, ActionState,
    StepState, WorkflowState, TaskState, RuntimeState, RuntimeStateSnapshot,
)
from agent.runtime.state.store import RuntimeStateStore
from agent.runtime.state.resolver import RuntimeStateResolver
from agent.runtime.state.snapshot import RuntimeStateSnapshotter
from agent.runtime.state.transition import RuntimeStateTransition

# ── Tasking model imports ───────────────────────────────────────────────

from agent.runtime.tasking.models import (
    TaskSignal, TaskPlan, StepPlan, WorkflowPlan, StepResult, TaskProgress,
)
from agent.runtime.tasking.detector import TaskDetector
from agent.runtime.tasking.planner import TaskPlanner
from agent.runtime.tasking.workflow import WorkflowPlanner
from agent.runtime.tasking.step import StepExecutor
from agent.runtime.tasking.progress import TaskProgressCalculator
from agent.runtime.tasking.completion import CompletionEvaluator


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_ctx(**overrides):
    """Build a minimal TurnContext for testing."""
    kw = dict(
        turn_id="turn_1",
        session_id="sess_test",
        workspace_id="ws_test",
        metadata={},
    )
    kw.update(overrides)
    return TurnContext(**kw)


def _make_state_with_task_and_workflow():
    """Return (state, task, workflow) with two pending steps."""
    task = TaskState(task_id="task_a", title="Test task", status="running")
    step1 = StepState(step_id="step_1", task_id="task_a", title="Step 1", order=0, status="running")
    step2 = StepState(step_id="step_2", task_id="task_a", title="Step 2", order=1, status="pending")
    wf = WorkflowState(
        workflow_id="wf_a",
        task_id="task_a",
        status="running",
        current_step_id="step_1",
        steps=[step1, step2],
    )
    state = RuntimeState(active_task=task, active_workflow=wf)
    task.workflow_id = wf.workflow_id
    task.current_step_id = step1.step_id
    state.tasks.append(task)
    state.workflows.append(wf)
    return state, task, wf


# ── 1. State models importable ──────────────────────────────────────────

def test_state_models_importable():
    s = SessionState()
    assert s.session_id.startswith("sess_")
    ws = WorkspaceState()
    assert ws.workspace_id.startswith("ws_")
    t = TaskState()
    assert t.task_id.startswith("task_")
    wf = WorkflowState()
    assert wf.workflow_id.startswith("wf_")
    st = StepState()
    assert st.step_id.startswith("step_")
    art = ArtifactState()
    assert art.artifact_id.startswith("art_")
    act = ActionState()
    assert act.action_id.startswith("act_")
    rs = RuntimeState()
    assert rs.session is not None
    snap = RuntimeStateSnapshot()
    assert snap.turn_id == ""


# ── 2. RuntimeStateResolver creates state and sets ctx.runtime_state ────

def test_resolver_creates_state_and_sets_ctx():
    ctx = _make_ctx()
    resolver = RuntimeStateResolver()
    state = resolver.resolve(ctx)
    assert isinstance(state, RuntimeState)
    assert state.session.session_id == "sess_test"
    assert ctx.runtime_state is state


# ── 3. TaskDetector detects new multi-step task ─────────────────────────

def test_detector_new_multi_step_task():
    det = TaskDetector()
    sig = det.detect("请帮我分析这个项目的代码，然后生成一份报告")
    assert sig.kind == "new_task"
    assert sig.confidence > 0.5


# ── 4. TaskDetector ignores simple chat ─────────────────────────────────

def test_detector_ignores_simple_chat():
    det = TaskDetector()
    sig = det.detect("你好")
    assert sig.kind == "none"

    sig2 = det.detect("翻译这个词")
    assert sig2.kind == "none"


# ── 5. TaskDetector detects continue with active task ───────────────────

def test_detector_continue_with_active_task():
    det = TaskDetector()
    state = RuntimeState(
        active_task=TaskState(task_id="task_x", status="running"),
    )
    sig = det.detect("继续", state=state)
    assert sig.kind == "continue_task"
    assert sig.referenced_task_id == "task_x"


# ── 6. TaskPlanner creates TaskPlan for new task ────────────────────────

def test_planner_creates_task_plan():
    signal = TaskSignal(kind="new_task", confidence=0.9)
    planner = TaskPlanner()
    plan = planner.plan(signal, "分析代码并生成报告")
    assert isinstance(plan, TaskPlan)
    assert plan.task_id.startswith("task_")
    assert plan.title != ""
    assert len(plan.steps) >= 1


# ── 7. WorkflowPlanner creates workflow and steps ───────────────────────

def test_workflow_planner_creates_workflow():
    task_plan = TaskPlan(
        task_id="task_t1",
        title="Test",
        steps=["分析代码结构", "提取关键指标", "生成报告"],
    )
    wp = WorkflowPlanner()
    wf_plan = wp.build(task_plan)
    assert isinstance(wf_plan, WorkflowPlan)
    assert wf_plan.task_id == "task_t1"
    assert len(wf_plan.steps) == 3
    assert wf_plan.steps[0].order == 0
    assert wf_plan.steps[2].order == 2
    for sp in wf_plan.steps:
        assert sp.step_id.startswith("step_")


# ── 8. StepExecutor prepares current step ───────────────────────────────

def test_step_executor_prepare():
    ctx = _make_ctx()
    state, task, wf = _make_state_with_task_and_workflow()
    executor = StepExecutor()
    step = executor.prepare_current_step(ctx, state)
    assert step is not None
    assert step.step_id == "step_1"
    assert step.status == "running"


# ── 9. StepExecutor applies action results ──────────────────────────────

def test_step_executor_apply_action_results():
    ctx = _make_ctx(metadata={
        "action_trace": [
            {"action_id": "act_001", "tool_id": "file.read", "status": "success", "summary": "Read config"},
            {"action_id": "act_002", "tool_id": "file.write", "status": "success", "summary": "Wrote output"},
        ],
        "action_evidence_updates": [
            {"artifact_id": "art_x1"},
        ],
    })
    state, task, wf = _make_state_with_task_and_workflow()
    executor = StepExecutor()
    result = executor.apply_action_results(ctx, state)
    assert result is not None
    assert result.status == "completed"
    assert "act_001" in result.action_ids
    assert "art_x1" in result.artifact_ids


# ── 10. Approval pending updates step status ────────────────────────────

def test_approval_pending_step_status():
    ctx = _make_ctx(metadata={
        "action_trace": [
            {"action_id": "act_010", "status": "approval_pending"},
        ],
        "action_evidence_updates": [],
    })
    state, task, wf = _make_state_with_task_and_workflow()
    executor = StepExecutor()
    result = executor.apply_action_results(ctx, state)
    assert result is not None
    assert result.status == "approval_pending"


# ── 11. RuntimeStateTransition advances to next step ────────────────────

def test_transition_advances_to_next_step():
    state, task, wf = _make_state_with_task_and_workflow()
    transition = RuntimeStateTransition()
    transition.apply_step_result(state, "step_1", "completed", summary="done")
    assert wf.current_step_id == "step_2"
    assert wf.steps[1].status == "running"
    assert task.current_step_id == "step_2"
    assert wf.progress_percent == 50.0


# ── 12. CompletionEvaluator marks task completed ────────────────────────

def test_completion_evaluator_marks_done():
    state, task, wf = _make_state_with_task_and_workflow()
    # Mark both steps completed
    wf.steps[0].status = "completed"
    wf.steps[0].result_summary = "Step 1 done"
    wf.steps[1].status = "completed"
    wf.steps[1].result_summary = "Step 2 done"
    ctx = _make_ctx()
    evaluator = CompletionEvaluator()
    result = evaluator.evaluate(ctx, state)
    assert result is not None
    assert result.status == "completed"
    assert result.progress_percent == 100.0
    assert wf.status == "completed"


# ── 13. Snapshot writes metadata ────────────────────────────────────────

def test_snapshot_writes_metadata():
    ctx = _make_ctx()
    state = RuntimeState(
        active_task=TaskState(task_id="task_snap", status="running", progress_percent=50.0),
    )
    snapshotter = RuntimeStateSnapshotter()
    snap = snapshotter.snapshot(ctx, state)
    assert snap.active_task_id == "task_snap"
    assert snap.task_status == "running"
    stored = ctx.metadata.get("runtime_state_snapshot")
    assert stored is not None
    assert stored["active_task_id"] == "task_snap"
    assert stored["progress_percent"] == 50.0


# ── 14. Store save/load roundtrip ───────────────────────────────────────

def test_store_save_load_roundtrip():
    ctx = _make_ctx()
    store = RuntimeStateStore()
    state = RuntimeState(
        session=SessionState(session_id="sess_rt"),
        workspace=WorkspaceState(workspace_id="ws_rt"),
        active_task=TaskState(task_id="task_rt", title="roundtrip", status="running"),
        active_workflow=WorkflowState(
            workflow_id="wf_rt",
            task_id="task_rt",
            steps=[StepState(step_id="step_rt", task_id="task_rt", title="s1")],
        ),
        tasks=[TaskState(task_id="task_rt", title="roundtrip", status="running")],
    )
    store.save(ctx, state)
    loaded = store.load(ctx)
    assert isinstance(loaded, RuntimeState)
    assert loaded.session.session_id == "sess_rt"
    assert loaded.active_task.task_id == "task_rt"
    assert loaded.active_workflow.workflow_id == "wf_rt"
    assert len(loaded.active_workflow.steps) == 1
    assert loaded.active_workflow.steps[0].step_id == "step_rt"


# ── 15. All modules importable ──────────────────────────────────────────

def test_all_modules_importable():
    import agent.runtime.state
    import agent.runtime.state.models
    import agent.runtime.state.store
    import agent.runtime.state.resolver
    import agent.runtime.state.snapshot
    import agent.runtime.state.transition
    import agent.runtime.tasking
    import agent.runtime.tasking.models
    import agent.runtime.tasking.detector
    import agent.runtime.tasking.planner
    import agent.runtime.tasking.workflow
    import agent.runtime.tasking.step
    import agent.runtime.tasking.progress
    import agent.runtime.tasking.completion
    assert True
