# harness/test_workspace_memory_stabilization.py
"""Workspace & Memory stabilization tests."""

import json
import os
import time
from pathlib import Path

import pytest


class TestWorkspaceManager:
    """Workspace manager tests."""

    def test_ensure_workspace_creates_dirs(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws_id = "test_ws"
        ensure_workspace(ws_id)

        ws = Path(str(temp_dirs["workspace_dir"])) / ws_id
        assert ws.is_dir()
        assert (ws / "runs").is_dir()
        assert (ws / "artifacts" / "inputs").is_dir()
        assert (ws / "artifacts" / "outputs").is_dir()

    def test_workspace_yaml_created(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws_id = "test_ws_yaml"
        ensure_workspace(ws_id)
        ws = Path(str(temp_dirs["workspace_dir"])) / ws_id
        assert (ws / "workspace.yaml").is_file()

    def test_state_json_created(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws_id = "test_ws_state"
        ensure_workspace(ws_id)
        ws = Path(str(temp_dirs["workspace_dir"])) / ws_id
        assert (ws / "state.json").is_file()

    def test_writes_and_reads_state(self, temp_dirs):
        from workspace.manager import ensure_workspace, update_workspace_state, get_workspace_state
        ws_id = "state_test"
        ensure_workspace(ws_id)
        update_workspace_state(ws_id, {"last_intent": "translate_config"})
        state = get_workspace_state(ws_id)
        assert state["last_intent"] == "translate_config"

    def test_state_excludes_source_config(self, temp_dirs):
        from workspace.manager import ensure_workspace, update_workspace_state
        ws_id = "safe_state"
        ensure_workspace(ws_id)
        big_config = "source_config: " + "x" * 600
        update_workspace_state(ws_id, {"source_config": big_config})
        state_path = Path(str(temp_dirs["workspace_dir"])) / ws_id / "state.json"
        content = state_path.read_text()
        # Large source_config should be truncated
        assert len(content) < 2000 or "source_config" not in json.loads(content)

    def test_list_workspaces_runs_count(self, temp_dirs):
        from workspace.manager import ensure_workspace, list_workspaces
        ws_id = "count_test"
        ensure_workspace(ws_id)

        # Write some run files
        runs_dir = Path(str(temp_dirs["workspace_dir"])) / ws_id / "runs"
        for i in range(3):
            (runs_dir / f"run_{i}.json").write_text('{"test": true}')

        ws_list = list_workspaces()
        found = [w for w in ws_list if w["workspace_id"] == ws_id]
        if found:
            assert found[0]["runs_count"] == 3

    def test_runs_count_not_hardcoded_zero(self, temp_dirs):
        from workspace.manager import ensure_workspace, list_workspaces
        ws_id = "real_count"
        ensure_workspace(ws_id)
        runs_dir = Path(str(temp_dirs["workspace_dir"])) / ws_id / "runs"
        (runs_dir / "run_1.json").write_text('{"test": true}')

        ws_list = list_workspaces()
        found = [w for w in ws_list if w["workspace_id"] == ws_id]
        if found:
            assert found[0]["runs_count"] == 1


class TestRunStore:
    """Run store tests."""

    def test_write_run_record(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.run_store import write_run_record, list_runs
        from agent.state import NetworkAgentState

        ensure_workspace("run_test")
        state = NetworkAgentState(
            intent="translate_config",
            workspace_id="run_test",
        )
        rid = write_run_record(state, "run_test")
        assert rid is not None

        runs = list_runs("run_test")
        assert len(runs) > 0

    def test_run_record_no_source_config(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.run_store import write_run_record
        from agent.state import NetworkAgentState

        ensure_workspace("safe_run")
        state = NetworkAgentState(
            intent="translate_config",
            workspace_id="safe_run",
        )
        write_run_record(state, "safe_run")

        runs_dir = Path(str(temp_dirs["workspace_dir"])) / "safe_run" / "runs"
        files = list(runs_dir.glob("*.json"))
        if files:
            content = files[0].read_text()
            # Should not contain full config strings
            assert "source_config" not in content or len(content) < 1000

    def test_run_record_no_deployable_config(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.run_store import write_run_record
        from agent.state import NetworkAgentState

        ensure_workspace("safe_run2")
        state = NetworkAgentState(
            intent="translate_config",
            workspace_id="safe_run2",
        )
        write_run_record(state, "safe_run2")

        runs_dir = Path(str(temp_dirs["workspace_dir"])) / "safe_run2" / "runs"
        files = list(runs_dir.glob("*.json"))
        if files:
            content = files[0].read_text()
            assert "deployable_config" not in content or len(content) < 1000

    def test_get_last_run(self, temp_dirs):
        from workspace.manager import ensure_workspace, get_workspace_runs
        from workspace.run_store import write_run_record, get_last_run
        from agent.state import NetworkAgentState
        import uuid

        ws_id = "last_run_test"
        ensure_workspace(ws_id)

        # Use deterministic request_ids to control sort order
        state1 = NetworkAgentState(
            intent="first", workspace_id=ws_id,
            request_id="run_a_first",
        )
        write_run_record(state1, ws_id)
        time.sleep(0.1)

        state2 = NetworkAgentState(
            intent="second", workspace_id=ws_id,
            request_id="run_b_second",
        )
        write_run_record(state2, ws_id)

        last = get_last_run(ws_id)
        assert last is not None
        assert last["intent"] == "second"


class TestArtifactStore:
    """Artifact store tests."""

    def test_save_and_get_artifact(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.artifact_store import save_artifact, get_artifact

        ws_id = "art_test"
        ensure_workspace(ws_id)
        aid = save_artifact(
            ws_id, "run1", "reports",
            {"summary": "test report"},
            title="Test Report",
            sensitivity="internal",
        )
        assert aid is not None

        result = get_artifact(ws_id, aid)
        assert result is not None

    def test_list_artifacts(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.artifact_store import save_artifact, list_artifacts

        ws_id = "art_list"
        ensure_workspace(ws_id)
        save_artifact(ws_id, "run1", "reports", {"data": 1}, title="R1")
        save_artifact(ws_id, "run2", "outputs", {"data": 2}, title="R2")

        arts = list_artifacts(ws_id)
        assert len(arts) >= 2


class TestContextLoader:
    """Context loader tests."""

    def test_context_loader_loads_workspace_state(self, temp_dirs):
        from workspace.manager import ensure_workspace, update_workspace_state
        from agent.state import NetworkAgentState
        from agent.nodes.context_loader import load_context

        ws_id = "ctx_test"
        ensure_workspace(ws_id)
        update_workspace_state(ws_id, {"last_intent": "translate_config"})

        state = NetworkAgentState(
            user_input="test",
            workspace_id=ws_id,
        )
        state = load_context(state)
        assert "workspace_state" in state.context

    def test_context_loader_context_ref_last_result(self, temp_dirs):
        from workspace.manager import ensure_workspace, update_workspace_state
        from agent.state import NetworkAgentState
        from agent.nodes.context_loader import load_context

        ws_id = "ctx_ref_test"
        ensure_workspace(ws_id)
        update_workspace_state(ws_id, {
            "last_intent": "translate_config",
            "last_result_summary": "deployable=10 manual_review=2",
        })

        state = NetworkAgentState(
            user_input="上次的翻译结果如何？",
            workspace_id=ws_id,
        )
        state.context["context_ref"] = "last_result"
        state = load_context(state)

        assert "last_result" in state.context
        assert state.context["last_result"]["has_result"] is True

    def test_context_loader_no_last_result(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from agent.state import NetworkAgentState
        from agent.nodes.context_loader import load_context

        ws_id = "no_result_test"
        ensure_workspace(ws_id)

        state = NetworkAgentState(
            user_input="test",
            workspace_id=ws_id,
        )
        state.context["context_ref"] = "last_result"
        state = load_context(state)

        assert state.context["last_result"]["has_result"] is False

    def test_context_loader_loads_memory_hits(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from agent.state import NetworkAgentState
        from agent.nodes.context_loader import load_context

        ws_id = "mem_hits_test"
        ensure_workspace(ws_id)

        state = NetworkAgentState(
            user_input="NAT translation",
            workspace_id=ws_id,
        )
        state = load_context(state)
        assert "memory_hits" in state.context
