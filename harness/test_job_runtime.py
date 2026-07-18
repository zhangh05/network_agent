# harness/test_job_runtime.py
"""Job / Task Runtime tests — schema, store, manager, runner, API, regression."""

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


class TestJobSchema:
    def test_job_record_fields(self):
        from jobs.schemas import JobRecord
        r = JobRecord(job_type="agent_run", title="test")
        d = r.as_dict()
        assert d["job_id"].startswith("job_")
        assert d["status"] == "created"

    def test_job_event_fields(self):
        from jobs.schemas import JobEvent
        e = JobEvent(job_id="j1", event_type="job_created")
        d = e.as_dict()
        assert d["event_type"] == "job_created"

    def test_progress_fields(self):
        from jobs.schemas import JobProgress
        p = JobProgress(current=5, total=10, message="working")
        assert p.percent == 50

    def test_status_enum(self):
        from jobs.schemas import JOB_STATUSES
        assert "queued" in JOB_STATUSES

    def test_job_type_enum(self):
        from jobs.schemas import JOB_TYPES, ENABLED_JOB_TYPES
        assert "translate_config" in ENABLED_JOB_TYPES


class TestJobStore:
    def test_create_and_get(self, temp_dirs):
        from jobs.store import create_job, get_job
        from jobs.schemas import JobRecord
        from storage.workspace_store import ensure_workspace
        ws = "js_test"
        ensure_workspace(ws)
        rec = JobRecord(workspace_id=ws, job_type="agent_run", title="test job")
        rec = create_job(rec)
        assert rec.job_id
        got = get_job(ws, rec.job_id)
        assert got and got.title == "test job"

    def test_update(self, temp_dirs):
        from jobs.store import create_job, get_job, update_job
        from jobs.schemas import JobRecord
        from storage.workspace_store import ensure_workspace
        ws = "js_upd"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run"))
        updated = update_job(ws, rec.job_id, {"status": "queued"})
        assert updated.status == "queued"

    def test_list(self, temp_dirs):
        from jobs.store import create_job, list_jobs
        from jobs.schemas import JobRecord
        from storage.workspace_store import ensure_workspace
        ws = "js_list"
        ensure_workspace(ws)
        create_job(JobRecord(workspace_id=ws, job_type="agent_run", title="j1"))
        create_job(JobRecord(workspace_id=ws, job_type="agent_run", title="j2"))
        jobs = list_jobs(ws_id=ws)
        assert len(jobs) >= 2

    def test_events(self, temp_dirs):
        from jobs.store import create_job, append_event, list_events
        from jobs.schemas import JobRecord, JobEvent
        from storage.workspace_store import ensure_workspace
        ws = "js_evt"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run"))
        append_event(ws, rec.job_id, JobEvent(job_id=rec.job_id, workspace_id=ws, event_type="job_started"))
        events = list_events(ws, rec.job_id)
        assert len(events) >= 1

    def test_logs(self, temp_dirs):
        from jobs.store import create_job, append_log, list_logs
        from jobs.schemas import JobRecord
        from storage.workspace_store import ensure_workspace
        ws = "js_log"
        ensure_workspace(ws)
        rec = create_job(JobRecord(workspace_id=ws, job_type="agent_run"))
        append_log(ws, rec.job_id, "test log message")
        logs = list_logs(ws, rec.job_id)
        assert len(logs) >= 1


class TestJobManager:
    def test_create_enqueued_job(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jm_cr"
        ensure_workspace(ws)
        from jobs.manager import create_job
        rec = create_job(workspace_id=ws, job_type="agent_run", title="manager test")
        assert rec.status == "queued"

    def test_cancel_queued(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jm_cx"
        ensure_workspace(ws)
        from jobs.manager import create_job, cancel_job
        rec = create_job(workspace_id=ws, job_type="agent_run")
        cancelled = cancel_job(ws, rec.job_id)
        assert cancelled.status == "cancelled"

    def test_retry_failed(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jm_rt"
        ensure_workspace(ws)
        from jobs.manager import create_job, mark_running, mark_failed, retry_job
        rec = create_job(workspace_id=ws, job_type="agent_run")
        mark_running(ws, rec.job_id)
        mark_failed(ws, rec.job_id, "test failure")
        retried = retry_job(ws, rec.job_id)
        assert retried.status == "queued"
        assert retried.retry_count == 1

    def test_retry_max_exceeded(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jm_max"
        ensure_workspace(ws)
        from jobs.manager import create_job, mark_running, mark_failed, retry_job
        from jobs.store import update_job
        rec = create_job(workspace_id=ws, job_type="agent_run")
        update_job(ws, rec.job_id, {"max_retries": 1})
        mark_running(ws, rec.job_id)
        mark_failed(ws, rec.job_id, "fail")
        retry_job(ws, rec.job_id)
        mark_running(ws, rec.job_id)
        mark_failed(ws, rec.job_id, "fail again")
        with pytest.raises(ValueError):
            retry_job(ws, rec.job_id)


class TestJobRunner:
    def test_agent_run_job(self, temp_dirs, monkeypatch):
        from storage.workspace_store import ensure_workspace
        ws = "jr_ar"
        ensure_workspace(ws)

        class FakeResult:
            def to_dict(self):
                return {
                    "ok": True,
                    "run_id": "run_job_test",
                    "trace_id": "trace_job_test",
                    "output_artifacts": [],
                    "report_artifacts": [],
                }

        class FakeAgentApp:
            def submit_user_message(self, **kwargs):
                assert kwargs["workspace_id"] == ws
                assert kwargs["metadata"]["job_id"]
                return FakeResult()

        monkeypatch.setattr(
            "agent.app.service.get_default_agent_app",
            lambda: FakeAgentApp(),
        )
        from jobs.manager import create_job
        rec = create_job(workspace_id=ws, job_type="agent_run",
                         payload={"message": "translate cisco to huawei",
                                  "source_vendor": "cisco", "target_vendor": "huawei",
                                  "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0"})
        from jobs.runner import run_job
        run_job(ws, rec.job_id)
        from jobs.store import get_job
        final = get_job(ws, rec.job_id)
        assert final.status == "succeeded"

    def test_translate_config_job(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jr_tc"
        ensure_workspace(ws)
        from jobs.manager import create_job
        rec = create_job(workspace_id=ws, job_type="translate_config",
                         payload={"message": "translate", "source_vendor": "cisco",
                                  "target_vendor": "huawei",
                                  "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
                                  "export_report": False})
        from jobs.runner import run_job
        run_job(ws, rec.job_id)
        from jobs.store import get_job
        final = get_job(ws, rec.job_id)
        assert final.status == "succeeded"
        assert len(final.run_ids) == 1

    def test_translate_with_export_report(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jr_er"
        ensure_workspace(ws)
        from jobs.manager import create_job
        rec = create_job(workspace_id=ws, job_type="translate_config",
                         payload={"message": "translate", "source_vendor": "cisco",
                                  "target_vendor": "huawei",
                                  "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
                                  "export_report": True, "report_format": "markdown"})
        from jobs.runner import run_job
        run_job(ws, rec.job_id)
        from jobs.store import get_job
        final = get_job(ws, rec.job_id)
        assert final.status == "succeeded"

    def test_planned_job_type(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ws = "jr_pl"
        ensure_workspace(ws)
        from jobs.store import create_job, get_job
        from jobs.schemas import JobRecord
        from jobs.runner import run_job
        rec = create_job(JobRecord(workspace_id=ws, job_type="topology_build", title="topology"))
        run_job(ws, rec.job_id)
        final = get_job(ws, rec.job_id)
        assert final.status == "succeeded"


class TestJobAPI:
    def test_create_job_api(self, client):
        resp = client.post("/api/jobs", json={
            "workspace_id": "ja_test", "job_type": "agent_run",
            "title": "API job", "payload": {},
        })
        assert resp.status_code == 200

    def test_create_job_rejects_invalid_workspace_id(self, client):
        resp = client.post("/api/jobs", json={
            "workspace_id": "../escape", "job_type": "agent_run",
            "title": "bad workspace", "payload": {},
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_workspace_id"

    def test_list_jobs_api(self, client):
        resp = client.get("/api/jobs?workspace_id=default")
        assert resp.status_code == 200

    def test_list_jobs_rejects_invalid_limit(self, client):
        resp = client.get("/api/jobs?limit=abc&workspace_id=default")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_limit"

    def test_worker_status(self, client):
        resp = client.get("/api/jobs/worker/status")
        assert resp.status_code == 200
