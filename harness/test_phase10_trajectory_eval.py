# harness/test_phase10_trajectory_eval.py
"""Phase 10: Trajectory evaluation tests."""

import pytest, uuid
from agent.runtime.durable.trajectory import (
    build_trajectory, persist_trajectory, get_trajectory,
    list_trajectories, evaluate_trajectory, save_feedback,
    TrajectoryRecord, TrajectoryMetrics,
)


class TestTrajectoryBuilder:
    def test_build_from_task(self):
        from agent.runtime.durable.store import save_task, get_task
        from agent.runtime.durable.models import TaskState, RuntimeStep
        ws = f"ws_t10_{uuid.uuid4().hex[:8]}"
        task = TaskState.new(workspace_id=ws, session_id="s1", run_id="r1",
                             user_goal="Test trajectory building")
        task.add_step(RuntimeStep(step_id="s1", task_id=task.task_id, kind="model", title="Step 1"))
        task.update_status("succeeded"); save_task(task)

        traj = build_trajectory(task.task_id, ws)
        assert traj is not None
        assert traj.task_id == task.task_id
        assert traj.final_status == "succeeded"
        assert traj.metrics.task_success is True

    def test_trajectory_persists_and_reads(self):
        ws = f"ws_tp_{uuid.uuid4().hex[:8]}"
        rec = TrajectoryRecord(task_id="t1", workspace_id=ws,
                               session_id="s1", final_status="succeeded",
                               user_goal="test", metrics=TrajectoryMetrics(task_success=True))
        persist_trajectory(rec)
        loaded = get_trajectory(rec.trajectory_id, ws)
        assert loaded is not None
        assert loaded["metrics"]["task_success"] is True

    def test_list_trajectories(self):
        ws = f"ws_tl_{uuid.uuid4().hex[:8]}"
        r1 = TrajectoryRecord(task_id="t1", workspace_id=ws, session_id="s1",
                              final_status="succeeded")
        r2 = TrajectoryRecord(task_id="t2", workspace_id=ws, session_id="s1",
                              final_status="failed")
        persist_trajectory(r1); persist_trajectory(r2)
        items = list_trajectories(ws)
        assert len(items) >= 2


class TestMetrics:
    def test_task_failure_detected(self):
        from agent.runtime.durable.store import save_task
        from agent.runtime.durable.models import TaskState
        ws = f"ws_mf_{uuid.uuid4().hex[:8]}"
        task = TaskState.new(workspace_id=ws, session_id="s1")
        task.update_status("failed"); save_task(task)
        traj = build_trajectory(task.task_id, ws)
        assert traj.metrics.task_success is False

    def test_unverified_completion_detected(self):
        from agent.runtime.durable.store import save_task
        from agent.runtime.durable.models import TaskState
        ws = f"ws_uv_{uuid.uuid4().hex[:8]}"
        task = TaskState.new(workspace_id=ws, session_id="s1")
        task.update_status("succeeded"); save_task(task)
        traj = build_trajectory(task.task_id, ws)
        assert traj.metrics.unverified_completion is True


class TestEvaluation:
    def test_eval_scoring(self):
        traj = {"metrics": {"task_success": True, "unverified_completion": False,
                             "tool_failure_count": 0, "retry_count": 0,
                             "memory_conflict_count": 0, "duration_ms": 1000}}
        result = evaluate_trajectory(traj)
        assert result["ok"] is True
        assert result["score"] == 10

    def test_eval_detects_issues(self):
        traj = {"metrics": {"task_success": False, "tool_failure_count": 3,
                             "retry_count": 5, "memory_conflict_count": 1}}
        result = evaluate_trajectory(traj)
        assert result["ok"] is False
        assert "task_failed" in result["issues"]
        assert "retry_loop" in result["issues"]


class TestFeedback:
    def test_feedback_not_active_memory(self):
        ws = f"ws_fb_{uuid.uuid4().hex[:8]}"
        rec = TrajectoryRecord(task_id="t1", workspace_id=ws, session_id="s1",
                               final_status="succeeded")
        persist_trajectory(rec)

        result = save_feedback(rec.trajectory_id, ws,
                               {"rating": 4, "comment": "Good answer but missing error handling"})
        assert result["ok"] is True


class TestPhase9Unaffected:
    def test_subagent_profiles_still_valid(self):
        from agent.runtime.durable.subagent import BUILTIN_PROFILES
        assert len(BUILTIN_PROFILES) == 7
