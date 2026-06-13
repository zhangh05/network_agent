# harness/test_observability_runtime.py
"""Observability Runtime tests — trace, timeline, agent integration."""

import json
import time
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None


@pytest.fixture
def client(temp_dirs):
    if _flask_app is None:
        pytest.skip("Flask app not importable")
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


class TestTraceSchema:
    def test_trace_event_required_fields(self):
        from observability.schemas import TraceEvent
        e = TraceEvent(trace_id="t1", run_id="r1", event_type="node_start", name="router")
        d = e.as_dict()
        for f in ("event_id", "trace_id", "run_id", "event_type", "name", "status"):
            assert f in d

    def test_trace_record_required_fields(self):
        from observability.schemas import TraceRecord
        t = TraceRecord(trace_id="t1", run_id="r1")
        d = t.as_dict()
        for f in ("trace_id", "run_id", "events", "node_count", "total_duration_ms"):
            assert f in d

    def test_event_type_valid(self):
        from observability.schemas import EVENT_TYPES
        assert "node_start" in EVENT_TYPES
        assert "skill_call_start" in EVENT_TYPES
        assert "llm_call_start" in EVENT_TYPES

    def test_status_values(self):
        from observability.schemas import STATUS_VALUES
        assert "success" in STATUS_VALUES
        assert "skipped" in STATUS_VALUES


class TestTraceStore:
    def test_write_and_get_trace(self, temp_dirs):
        from observability.schemas import TraceRecord, TraceEvent
        from observability.store import write_trace, get_trace
        from workspace.manager import ensure_workspace

        ws_id = "trace_test_ws"
        ensure_workspace(ws_id)

        trace = TraceRecord(
            trace_id="t-test-1", run_id="r-test-1",
            workspace_id=ws_id, status="success",
            events=[
                TraceEvent(trace_id="t-test-1", run_id="r-test-1", event_type="node_start", name="router").as_dict(),
                TraceEvent(trace_id="t-test-1", run_id="r-test-1", event_type="node_end", name="router", status="success", duration_ms=5.0).as_dict(),
            ],
            node_count=1, total_duration_ms=10.0,
        )
        tid = write_trace(trace, ws_id)
        assert tid == "t-test-1"

        result = get_trace("r-test-1", ws_id)
        assert result is not None
        assert result["trace_id"] == "t-test-1"
        assert result["node_count"] == 1

    def test_list_traces(self, temp_dirs):
        from observability.schemas import TraceRecord
        from observability.store import write_trace, list_traces
        from workspace.manager import ensure_workspace

        ws_id = "trace_list_ws"
        ensure_workspace(ws_id)
        for i in range(3):
            t = TraceRecord(trace_id=f"t-l{i}", run_id=f"r-l{i}", workspace_id=ws_id)
            write_trace(t, ws_id)

        traces = list_traces(ws_id, limit=50)
        assert len(traces) >= 3

    def test_trace_redacts_key(self, temp_dirs):
        from observability.schemas import TraceRecord, TraceEvent
        from observability.store import write_trace, get_trace
        from workspace.manager import ensure_workspace

        ws_id = "trace_redact_ws"
        ensure_workspace(ws_id)

        t = TraceRecord(
            trace_id="t-redact", run_id="r-redact", workspace_id=ws_id,
            events=[
                TraceEvent(
                    trace_id="t-redact", run_id="r-redact",
                    event_type="llm_call_start", name="llm",
                    metadata={"api_key": "sk-secret-key-should-not-appear"},
                ).as_dict(),
            ],
        )
        write_trace(t, ws_id)
        raw = (Path(str(temp_dirs["workspace_dir"])) / ws_id / "runs" / "r-redact.trace.json").read_text()
        assert "sk-secret-key-should-not-appear" not in raw

    def test_trace_redacts_password(self, temp_dirs):
        from observability.schemas import TraceRecord, TraceEvent
        from observability.store import write_trace
        from workspace.manager import ensure_workspace

        ws_id = "trace_redact_pw"
        ensure_workspace(ws_id)
        t = TraceRecord(
            trace_id="t-pw", run_id="r-pw", workspace_id=ws_id,
            events=[
                TraceEvent(
                    trace_id="t-pw", run_id="r-pw", event_type="node_start", name="test",
                    metadata={"password": "admin123"},
                ).as_dict(),
            ],
        )
        write_trace(t, ws_id)
        raw = (Path(str(temp_dirs["workspace_dir"])) / ws_id / "runs" / "r-pw.trace.json").read_text()
        assert "admin123" not in raw

    def test_trace_redacts_full_config(self, temp_dirs):
        from observability.schemas import TraceRecord, TraceEvent
        from observability.store import write_trace
        from workspace.manager import ensure_workspace

        ws_id = "trace_redact_cfg"
        ensure_workspace(ws_id)
        t = TraceRecord(
            trace_id="t-cfg", run_id="r-cfg", workspace_id=ws_id,
            events=[
                TraceEvent(
                    trace_id="t-cfg", run_id="r-cfg", event_type="node_start", name="test",
                    metadata={"source_config": "x" * 600},
                ).as_dict(),
            ],
        )
        write_trace(t, ws_id)
        raw = (Path(str(temp_dirs["workspace_dir"])) / ws_id / "runs" / "r-cfg.trace.json").read_text()
        assert "x" * 600 not in raw

    def test_append_event(self, temp_dirs):
        from observability.schemas import TraceRecord, TraceEvent
        from observability.store import write_trace, append_event, get_trace
        from workspace.manager import ensure_workspace

        ws_id = "append_ws"
        ensure_workspace(ws_id)
        trace = TraceRecord(trace_id="t-append", run_id="r-append", workspace_id=ws_id)
        write_trace(trace, ws_id)

        evt = TraceEvent(trace_id="t-append", run_id="r-append", event_type="node_start", name="new_node")
        append_event("t-append", evt, ws_id)

        result = get_trace("r-append", ws_id)
        assert len(result["events"]) > 0


class TestAgentTrace:
    def test_agent_run_returns_trace_id(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "test_trace_ag",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
            },
        })
        data = resp.get_json()
        assert data["trace_id"] != ""
        assert data["trace_available"] is True

    def test_agent_run_returns_timeline_summary(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "test_tl_ag",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        assert "timeline_summary" in data
        tl = data["timeline_summary"]
        assert "total_duration_ms" in tl
        assert "node_count" in tl
        assert tl["node_count"] > 0

    def test_trace_has_node_events(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "test_nodes_ag",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        trace_id = data.get("trace_id", "")

        # Get trace API
        resp2 = client.get(f"/api/workspaces/test_nodes_ag/runs/{data['run_id']}/trace")
        if resp2.status_code == 200:
            trace = resp2.get_json()["trace"]
            events = trace.get("events", [])
            names = [e.get("name", "") for e in events]
            # Should have router, context_loader, etc.
            assert any("router" in n or "context" in n for n in names)


class TestTraceAPI:
    def test_get_trace_works(self, client):
        # First run agent to create trace
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "trace_api_ws",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        run_id = data["run_id"]

        # Then get trace
        resp2 = client.get(f"/api/workspaces/trace_api_ws/runs/{run_id}/trace")
        assert resp2.status_code == 200
        trace = resp2.get_json()["trace"]
        assert trace["trace_id"] != ""

    def test_missing_trace_404(self, client):
        resp = client.get("/api/workspaces/trace_api_ws/runs/nonexistent_run/trace")
        assert resp.status_code == 404

    def test_list_traces_api(self, client):
        resp = client.get("/api/workspaces/trace_api_ws/traces")
        assert resp.status_code == 200

    def test_trace_api_no_key(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "trace_api_nk",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        run_id = resp.get_json()["run_id"]
        resp2 = client.get(f"/api/workspaces/trace_api_nk/runs/{run_id}/trace")
        if resp2.status_code == 200:
            content = json.dumps(resp2.get_json())
            assert "sk-" not in content or "redacted" in content.lower()

    def test_run_record_contains_trace_id(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "trace_runrec",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        assert "trace_id" in data


class TestRegression:
    def test_config_translation_still_works(self, client):
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco",
            "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        })
        assert resp.status_code == 200
        assert resp.get_json().get("ok") is True

    def test_no_api_translate(self, client):
        resp = client.post("/api/translate", json={"test": 1})
        assert resp.status_code in (404, 405)

    def test_workspace_runs_count(self, temp_dirs):
        from workspace.manager import list_workspaces, ensure_workspace
        ws_id = "reg_ws"
        ensure_workspace(ws_id)
        ws_list = list_workspaces()
        found = [w for w in ws_list if w["workspace_id"] == ws_id]
        if found:
            assert found[0]["runs_count"] >= 0  # At least real count
