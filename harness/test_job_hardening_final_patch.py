# harness/test_job_hardening_final_patch.py
"""Job Runtime Hardening Final Patch — redaction, state machine, batch, sanitized API."""

import json, pytest
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


class TestLogRedaction:
    def test_append_log_redacts_config(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.store import create_job, append_log, list_logs
        from jobs.schemas import JobRecord
        ws = "jh_log"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run", title="logtest"))
        append_log(ws, rec.job_id, "Processing: hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0")
        logs = list_logs(ws, rec.job_id)
        raw = json.dumps(logs)
        assert "hostname" not in raw.lower() or "hostname" not in raw
        assert "ip address" not in raw

    def test_append_log_redacts_secrets(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.store import create_job, append_log, list_logs
        from jobs.schemas import JobRecord
        ws = "jh_sec"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run"))
        append_log(ws, rec.job_id, "password admin123\ntoken=abc123secret\napi_key=sk-test")
        logs = list_logs(ws, rec.job_id)
        raw = json.dumps(logs)
        assert "admin123" not in raw
        assert "abc123secret" not in raw
        assert "sk-test" not in raw

    def test_append_log_sanitizes_metadata(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.store import create_job, append_log, list_logs
        from jobs.schemas import JobRecord
        ws = "jh_meta"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run"))
        append_log(ws, rec.job_id, "ok", meta={"source_config": "hostname R1\ninterface Gi0/1"})
        logs = list_logs(ws, rec.job_id)
        raw = json.dumps(logs)
        assert "hostname" not in raw


class TestConfigRefSafety:
    def test_config_ref_no_raw_content(self):
        from jobs.redaction import _config_ref
        result = _config_ref({"source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0"}, "source_config")
        assert result["line_count"] == 3
        assert "hostname" not in result.get("summary", "")
        assert "interface" not in result.get("summary", "")

    def test_source_config_ref_safe_summary(self, client):
        resp = client.post("/api/jobs", json={
            "workspace_id": "jh_ref", "job_type": "agent_run",
            "title": "safe ref test",
            "payload": {"source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0"},
        })
        data = resp.get_json()
        raw = json.dumps(data)
        assert "hostname" not in raw

    def test_nested_payload_redacted(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.manager import create_job
        from jobs.store import get_job
        ws = "jh_nest"
        ensure_workspace(ws)
        rec = create_job(workspace_id=ws, job_type="agent_run",
                         payload={"nested": {"source_config": "hostname R1\nip address 10.1.1.1 255.255.255.0"}})
        raw = json.dumps(rec.as_dict())
        assert "hostname" not in raw

    def test_deployable_config_redacted(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.store import create_job, get_job
        from jobs.schemas import JobRecord
        ws = "jh_dc"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run",
                         payload={"deployable_config": "hostname R1\ninterface Gi0/1"}))
        raw = json.dumps(rec.as_dict())
        assert "hostname" not in raw


class TestStateMachine:
    def test_queued_to_failed_allowed(self):
        from jobs.manager import ALLOWED_TRANSITIONS
        assert "failed" in ALLOWED_TRANSITIONS.get("queued", set())

    def test_succeeded_to_queued_rejected(self):
        from jobs.manager import ALLOWED_TRANSITIONS
        assert "queued" not in ALLOWED_TRANSITIONS.get("succeeded", set())

    def test_cancelled_to_running_rejected(self):
        from jobs.manager import ALLOWED_TRANSITIONS
        assert "running" not in ALLOWED_TRANSITIONS.get("cancelled", set())

    def test_mark_running_fails_succeeded(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.manager import create_job, mark_succeeded, mark_running
        ws = "jh_sm1"
        ensure_workspace(ws)
        rec = create_job(workspace_id=ws, job_type="agent_run")
        mark_running(ws, rec.job_id)
        mark_succeeded(ws, rec.job_id)
        with pytest.raises(ValueError):
            mark_running(ws, rec.job_id)

    def test_retry_failed_works(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.manager import create_job, mark_running, mark_failed, retry_job
        ws = "jh_rt1"
        ensure_workspace(ws)
        rec = create_job(workspace_id=ws, job_type="agent_run")
        mark_running(ws, rec.job_id)
        mark_failed(ws, rec.job_id, "fail")
        retried = retry_job(ws, rec.job_id)
        assert retried.status == "queued"
        assert retried.retry_count == 1


class TestAPI:
    def test_create_job_response_no_config(self, client):
        resp = client.post("/api/jobs", json={
            "workspace_id": "jh_api", "job_type": "agent_run",
            "payload": {"message": "test", "source_config": "hostname R1\ninterface Gi0/1"},
        })
        raw = json.dumps(resp.get_json())
        assert "hostname" not in raw

    def test_list_jobs_sanitized(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200

    def test_no_api_translate(self, client):
        assert client.post("/api/translate", json={"test": 1}).status_code in (404, 405)


class TestRegression:
    def test_translate_job_still_works(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.manager import create_job
        from jobs.runner import run_job
        ws = "jh_reg1"
        ensure_workspace(ws)
        rec = create_job(workspace_id=ws, job_type="translate_config",
                         payload={"message": "translate", "source_vendor": "cisco",
                                  "target_vendor": "huawei",
                                  "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0"})
        run_job(ws, rec.job_id)
        from jobs.store import get_job
        final = get_job(ws, rec.job_id)
        assert final and final.status == "succeeded"

    def test_planned_job_goes_running_then_succeeded(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.store import create_job, get_job
        from jobs.schemas import JobRecord
        from jobs.runner import run_job
        ws = "jh_pl"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="topology_build", title="topo"))
        run_job(ws, rec.job_id)
        final = get_job(ws, rec.job_id)
        assert final and final.status == "succeeded"

    def test_agent_run_still_works(self, temp_dirs):
        from workspace.manager import ensure_workspace
        from jobs.manager import create_job
        from jobs.runner import run_job
        from jobs.store import get_job
        ws = "jh_ar"
        ensure_workspace(ws)
        rec = create_job(workspace_id=ws, job_type="agent_run",
                         payload={"message": "translate cisco to huawei",
                                  "source_vendor": "cisco", "target_vendor": "huawei",
                                  "source_config": "hostname R1"})
        run_job(ws, rec.job_id)
        final = get_job(ws, rec.job_id)
        assert final and final.status == "succeeded"

    def test_worker_status(self, client):
        resp = client.get("/api/jobs/worker/status")
        assert resp.status_code == 200
