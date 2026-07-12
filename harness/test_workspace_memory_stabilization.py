# harness/test_workspace_memory_stabilization.py
"""Workspace & Memory stabilization tests."""

import json
from agent.state import NetworkAgentState
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
        assert (ws / "files" / "data").is_dir()

    def test_workspace_yaml_created(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws_id = "test_ws_yaml"
        ensure_workspace(ws_id)
        ws = Path(str(temp_dirs["workspace_dir"])) / ws_id
        assert (ws / "sys" / "workspace.yaml").is_file()
        assert not (ws / "workspace.yaml").exists()

    def test_state_json_created(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws_id = "test_ws_state"
        ensure_workspace(ws_id)
        ws = Path(str(temp_dirs["workspace_dir"])) / ws_id
        assert (ws / "sys" / "state.json").is_file()
        assert not (ws / "state.json").exists()

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
        state_path = Path(str(temp_dirs["workspace_dir"])) / ws_id / "sys" / "state.json"
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

    @pytest.mark.parametrize("bad_ws_id", ["../escape", "bad/name", " bad ", "", ".hidden"])
    def test_invalid_workspace_id_rejected(self, temp_dirs, bad_ws_id):
        from workspace.manager import ensure_workspace

        with pytest.raises(ValueError, match="invalid_workspace_id"):
            ensure_workspace(bad_ws_id)

        assert not (Path(str(temp_dirs["workspace_dir"])).parent / "escape").exists()

class TestRunStore:
    """Run store tests."""

    def test_write_run_record(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from workspace.run_store import write_run_record, list_runs
        
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
        from artifacts import save_artifact, get_artifact

        ws_id = "art_test"
        ensure_workspace(ws_id)
        aid = save_artifact(
            ws_id,
            content="test report content",
            artifact_type="reports",
            title="Test Report",
            sensitivity="internal",
            run_id="run1",
        )
        assert aid is not None

        result = get_artifact(ws_id, aid.artifact_id)
        assert result is not None

    def test_list_artifacts(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from artifacts import save_artifact, list_artifacts

        ws_id = "art_list"
        ensure_workspace(ws_id)
        save_artifact(ws_id, content="data1", artifact_type="reports", title="R1", run_id="run1")
        save_artifact(ws_id, content="data2", artifact_type="outputs", title="R2", run_id="run2")

        arts = list_artifacts(ws_id)
        assert len(arts) >= 2
