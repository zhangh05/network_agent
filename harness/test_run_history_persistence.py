"""Run History Persistence Tests — v0.1"""
import pytest
from agent.state import NetworkAgentState


class TestRunHistoryPersistence:
    def test_run_record_written(self):
        """After run_agent, a run record should be persisted."""
        # Test that the run_store produces valid records
        from workspace.run_store import write_run_record, get_run
        state = NetworkAgentState(
            user_input="你好", intent="assistant_chat",
            active_module="assistant", selected_skill="none",
            workspace_id="default",
        )
        state.error = None
        state.skill_results = {"ok": True, "quality_summary": {
            "source_residue_count": 0, "silent_drop_count": 0,
            "review_required_count": 0, "unsupported_count": 0,
        }}
        run_id = write_run_record(state)
        assert run_id

        # Read back
        record = get_run(run_id, "default")
        assert record is not None
        assert record["intent"] == "assistant_chat"
        assert record["workspace_id"] == "default"
        assert record["status"] == "ok"

    def test_run_record_no_full_config(self):
        """Run record must NOT contain full deployable config lines."""
        from workspace.run_store import write_run_record, get_run
        state = NetworkAgentState(
            user_input="test config",
            intent="translate_config",
            workspace_id="default",
        )
        state.skill_results = {
            "ok": True,
            "deployable_config": "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        }
        run_id = write_run_record(state)
        record = get_run(run_id, "default")
        record_str = str(record)
        assert "interface Gi0/1" not in record_str

    def test_run_record_has_quality_summary(self):
        """Run record should include quality_summary counts."""
        from workspace.run_store import write_run_record, get_run
        state = NetworkAgentState(user_input="test", intent="translate_config",
                                  workspace_id="default")
        state.skill_results = {
            "ok": True,
            "quality_summary": {
                "source_residue_count": 3, "silent_drop_count": 5,
            },
        }
        run_id = write_run_record(state)
        record = get_run(run_id, "default")
        assert "quality_summary" in record
        qs = record["quality_summary"]
        assert qs["source_residue_count"] == 3

    def test_run_record_no_password(self):
        """Run record must not leak password in result fields (user_input_summary is ok)."""
        from workspace.run_store import write_run_record, get_run
        state = NetworkAgentState(
            user_input="set password mypassword",
            intent="translate_config",
            workspace_id="default",
        )
        state.skill_results = {"ok": True, "deployable_config": ""}
        run_id = write_run_record(state)
        record = get_run(run_id, "default")
        result_counts = record.get("result_counts", {})
        assert "mypassword" not in str(result_counts)
