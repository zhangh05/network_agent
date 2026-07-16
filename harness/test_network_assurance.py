from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.modules.inspection.models import CommandResult, DeviceResult, InspectionScope, InspectionTask


@pytest.fixture()
def assurance_env(tmp_path, monkeypatch):
    from agent.modules.assurance import service, store

    monkeypatch.setattr(store, "workspace_root", lambda workspace_id: tmp_path / workspace_id)
    tasks: dict[str, InspectionTask] = {}

    def get_task(_workspace_id, task_id, record_poll=False):
        return tasks.get(task_id)

    def list_tasks(_workspace_id, limit=100):
        return [{"task_id": task.task_id, "status": task.status} for task in reversed(list(tasks.values()))]

    monkeypatch.setattr(service.inspection_service, "get_task", get_task)
    monkeypatch.setattr(service.inspection_service, "list_tasks", list_tasks)
    monkeypatch.setattr(service.cmdb_service, "list_assets", lambda _workspace_id: [
        {"asset_id": "a1", "name": "core-1", "host": "10.0.0.1", "type": "router", "vendor": "H3C", "region": "east", "peer_asset_ids": ["a2"]},
        {"asset_id": "a2", "name": "core-2", "host": "10.0.0.2", "type": "router", "vendor": "H3C", "region": "east"},
    ])

    def add_task(task_id: str, ok: bool = True, output: str = "state up"):
        result = CommandResult(check_id="health", category="health", command_key="display status", ok=ok, output_snippet=output, artifact_id=f"art_{task_id}")
        device = DeviceResult(task_id=task_id, asset_id="a1", asset_name="core-1", host="10.0.0.1", region="east", vendor="H3C", type="router", protocol="ssh", status="succeeded" if ok else "partial", command_results=[result])
        task = InspectionTask(task_id=task_id, workspace_id="default", scope=InspectionScope(region="east"), profile_id="general", status="succeeded" if ok else "partial", finished_at="2026-07-15T08:00:00+00:00", devices={"a1": device})
        tasks[task_id] = task
        return task

    def start_background_task(*, workspace_id, profile_id, scope, created_by, max_concurrency):
        task_id = f"ins_fresh_{len(tasks) + 1}"
        task = InspectionTask(
            task_id=task_id, workspace_id=workspace_id,
            scope=InspectionScope(region=str((scope or {}).get("region", ""))),
            profile_id=profile_id, status="running", created_by=created_by,
            max_concurrency=max_concurrency, total_assets=1,
        )
        tasks[task_id] = task
        return task

    monkeypatch.setattr(service.inspection_service, "start_background_task", start_background_task)

    return SimpleNamespace(service=service, store=store, add_task=add_task, tasks=tasks)


def test_baseline_and_drift_are_derived_from_completed_inspection(assurance_env):
    env = assurance_env
    env.add_task("ins_base", output="interface up")
    baseline = env.service.create_baseline("default", "east stable", inspection_task_id="ins_base")
    assert baseline["fact_count"] > 0
    assert baseline["source_task_id"] == "ins_base"

    env.add_task("ins_new", output="interface down")
    drift = env.service.check_baseline("default", baseline["baseline_id"], "ins_new")
    assert drift["status"] == "compliant"
    assert any(change["key"].endswith(".digest") for change in drift["changes"])
    assert all(change["evidence_ref"] for change in drift["changes"])


def test_manual_check_starts_fresh_inspection_and_finishes_after_collection(assurance_env):
    env = assurance_env
    env.add_task("ins_base", output="interface up")
    baseline = env.service.create_baseline("default", "east stable", inspection_task_id="ins_base")

    check = env.service.start_baseline_check("default", baseline["baseline_id"])
    assert check["status"] == "collecting"
    assert check["inspection_task_id"] != "ins_base"
    assert env.tasks[check["inspection_task_id"]].created_by == f"assurance:baseline_check:{check['check_id']}"
    assert env.service.list_drifts("default") == []

    fresh = env.tasks[check["inspection_task_id"]]
    result = CommandResult(
        check_id="health", category="health", command_key="display status",
        ok=True, output_snippet="interface down", artifact_id="art_fresh",
    )
    fresh.devices = {
        "a1": DeviceResult(
            task_id=fresh.task_id, asset_id="a1", asset_name="core-1",
            host="10.0.0.1", region="east", vendor="H3C", type="router",
            protocol="ssh", status="succeeded", command_results=[result],
        ),
    }
    fresh.status = "succeeded"
    fresh.succeeded = 1
    fresh.finished_at = "2026-07-15T08:05:00+00:00"

    completed = env.service.get_baseline_check("default", check["check_id"])
    assert completed["status"] == "completed"
    assert completed["drift_id"]
    drift = env.store.get("default", "drifts", completed["drift_id"])
    assert drift and drift["source_task_id"] == fresh.task_id
    assert drift["status"] == "compliant"


def _finish_mock_task(env, task_id: str, *, ok: bool = True, output: str = "state up"):
    task = env.tasks[task_id]
    result = CommandResult(
        check_id="health", category="health", command_key="display status",
        ok=ok, output_snippet=output, artifact_id=f"art_{task_id}",
        error="command_failed" if not ok else "",
    )
    task.devices = {
        "a1": DeviceResult(
            task_id=task_id, asset_id="a1", asset_name="core-1", host="10.0.0.1",
            region="east", vendor="H3C", type="router", protocol="ssh",
            status="succeeded" if ok else "partial", command_results=[result],
        ),
    }
    task.status = "succeeded" if ok else "partial"
    task.succeeded = 1 if ok else 0
    task.partial = 0 if ok else 1
    task.finished_at = "2026-07-15T08:10:00+00:00"
    return task


def test_impact_operation_collects_fresh_evidence_before_result(assurance_env):
    operation = assurance_env.service.start_assurance_operation(
        "default", "impact", asset_ids=["a1"], depth=3,
    )
    assert operation["status"] == "collecting"
    assert operation["result"]["depth"] == 3
    assert not operation["result"].get("affected_assets")
    _finish_mock_task(assurance_env, operation["inspection_task_id"])
    completed = assurance_env.service.get_assurance_operation("default", operation["operation_id"])
    assert completed["status"] == "completed"
    assert completed["artifact_ids"] == [f"art_{operation['inspection_task_id']}"]
    assert [item["asset_id"] for item in completed["result"]["affected_assets"]] == ["a2"]
    assert completed["result"]["topology_id"]


def test_impact_operation_only_reuses_an_identical_active_request(assurance_env):
    first = assurance_env.service.start_assurance_operation(
        "default", "impact", asset_ids=["a1"], depth=2,
    )
    same = assurance_env.service.start_assurance_operation(
        "default", "impact", asset_ids=["a1"], depth=2,
    )
    deeper = assurance_env.service.start_assurance_operation(
        "default", "impact", asset_ids=["a1"], depth=3,
    )
    other_asset = assurance_env.service.start_assurance_operation(
        "default", "impact", asset_ids=["a2"], depth=2,
    )
    assert same["operation_id"] == first["operation_id"]
    assert deeper["operation_id"] != first["operation_id"]
    assert other_asset["operation_id"] != first["operation_id"]


def test_incident_operation_replaces_placeholder_with_collected_evidence(assurance_env):
    incident = assurance_env.service.create_incident("default", "core flap", "neighbor unstable")
    operation = assurance_env.store.get("default", "operations", incident["operation_id"])
    assert operation and operation["status"] == "collecting"
    _finish_mock_task(assurance_env, operation["inspection_task_id"], ok=False, output="neighbor down")
    assurance_env.service.get_assurance_operation("default", operation["operation_id"])
    refreshed = assurance_env.store.get("default", "incidents", incident["incident_id"])
    assert refreshed["status"] == "monitoring"
    assert refreshed["inspection_task_id"] == operation["inspection_task_id"]
    assert refreshed["hypotheses"][0]["confidence"] == "confirmed"


def test_change_pre_and_post_checks_use_two_real_inspections(assurance_env):
    change = assurance_env.service.create_change_plan("default", "routing change", "adjust preference", ["a1"])
    pre = assurance_env.service.start_change_precheck("default", change["change_id"])["operation"]
    _finish_mock_task(assurance_env, pre["inspection_task_id"], output="neighbor up")
    assurance_env.service.get_assurance_operation("default", pre["operation_id"])
    ready = assurance_env.store.get("default", "changes", change["change_id"])
    assert ready["status"] == "ready_for_change"
    assert ready["pre_snapshot_id"]

    post = assurance_env.service.start_change_postcheck("default", change["change_id"])["operation"]
    _finish_mock_task(assurance_env, post["inspection_task_id"], ok=False, output="neighbor down")
    assurance_env.service.get_assurance_operation("default", post["operation_id"])
    verified = assurance_env.store.get("default", "changes", change["change_id"])
    assert verified["status"] == "rollback_required"
    assert verified["validation"]["passed"] is False
    assert post["inspection_task_id"] != pre["inspection_task_id"]


def test_topology_and_impact_use_evidence_links(assurance_env):
    topology = assurance_env.service.build_topology("default")
    assert len(topology["nodes"]) == 2
    assert topology["edges"][0]["confidence"] == "confirmed"
    impact = assurance_env.service.impact_analysis("default", ["a1"])
    assert [item["asset_id"] for item in impact["affected_assets"]] == ["a2"]
    assert impact["confidence"] == "evidence_based"


def test_change_assurance_validates_without_executing(assurance_env):
    plan = assurance_env.service.create_change_plan("default", "route policy", "adjust preference", ["a1"])
    validated = assurance_env.service.validate_change_plan("default", plan["change_id"])
    assert validated["status"] == "validated"
    assert validated["validation"]["valid"] is True
    assert "deploy" not in validated
    assert validated["rollback_conditions"]


def test_schedule_inherits_baseline_scope(assurance_env):
    assurance_env.add_task("ins_base")
    baseline = assurance_env.service.create_baseline("default", "east", inspection_task_id="ins_base")
    schedule = assurance_env.service.create_schedule("default", "hourly", baseline["baseline_id"], 60)
    assert schedule["scope"]["region"] == "east"
    assert schedule["interval_minutes"] == 60


def test_assurance_tool_is_in_every_ssot_surface():
    from agent.capabilities.catalog import get
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    from core.tools.manifest_registry import MANIFESTS
    from core.tools.tool_namespace import TOOL_NAMESPACE
    from core.tools.canonical_registry import to_tool_specs

    assert set(TOOL_NAMESPACE) == set(CANONICAL_REGISTRY) == set(MANIFESTS)
    assert "assurance.manage" in TOOL_NAMESPACE
    capability = get("network_assurance")
    assert capability and "assurance.manage" in capability["recommended_tool_ids"]
    assert MANIFESTS["assurance.manage"].requires_approval is False
    spec = next(spec for spec, _ in to_tool_specs() if spec.tool_id == "assurance.manage")
    assert spec.category == "assurance"
    assert spec.risk_level == "medium"


def test_assurance_http_contract_requires_workspace(assurance_env, monkeypatch):
    from flask import Flask
    from backend.api.assurance_routes import register_assurance_routes

    monkeypatch.setattr(assurance_env.service, "start_scheduler", lambda: None)
    app = Flask(__name__)
    register_assurance_routes(app)
    client = app.test_client()

    assert client.get("/api/assurance/overview").status_code == 400
    response = client.get("/api/assurance/overview?workspace_id=default")
    assert response.status_code == 200
    assert response.get_json()["overview"]["counts"]["topology_nodes"] == 2
    snapshot = client.get("/api/assurance/snapshot?workspace_id=default")
    assert snapshot.status_code == 200
    body = snapshot.get_json()["snapshot"]
    assert body["workspace_id"] == "default"
    assert body["overview"]["counts"]["topology_nodes"] == 2
    assert body["topology"]["nodes"]


def test_partial_inspection_cannot_become_baseline(assurance_env):
    assurance_env.add_task("ins_partial", ok=False)
    with pytest.raises(ValueError, match="complete_inspection_required_for_baseline"):
        assurance_env.service.create_baseline("default", "unsafe", inspection_task_id="ins_partial")
    assert assurance_env.store.list_records("default", "snapshots") == []


def test_partial_check_does_not_invent_removed_facts(assurance_env):
    assurance_env.add_task("ins_base", output="interface up")
    baseline = assurance_env.service.create_baseline("default", "east", inspection_task_id="ins_base")
    partial = assurance_env.add_task("ins_partial", ok=False, output="")
    partial.devices = {}
    drift = assurance_env.service.check_baseline("default", baseline["baseline_id"], "ins_partial")
    assert drift["status"] == "partial"
    assert drift["incomplete"] is True
    assert not any(item["kind"] == "removed" for item in drift["changes"])


def test_impact_rejects_unknown_asset_and_change_deduplicates_targets(assurance_env):
    with pytest.raises(ValueError, match="impact_asset_not_found"):
        assurance_env.service.impact_analysis("default", ["missing"])
    plan = assurance_env.service.create_change_plan("default", "x", "y", ["a1", "a1"])
    assert plan["asset_ids"] == ["a1"]


def test_incident_rejects_unknown_drift_and_invalid_state(assurance_env):
    with pytest.raises(ValueError, match="drift_not_found"):
        assurance_env.service.create_incident("default", "x", "y", drift_id="drift_missing")
    incident = assurance_env.service.create_incident("default", "x", "y")
    with pytest.raises(ValueError, match="invalid_incident_status"):
        assurance_env.service.update_incident("default", incident["incident_id"], {"status": "made_up"})
    with pytest.raises(ValueError, match="confirmed_hypothesis_requires_known_evidence"):
        assurance_env.service.update_incident("default", incident["incident_id"], {"hypotheses": [{"statement": "root cause", "confidence": "confirmed", "evidence_ref": "fake"}]})


def test_change_status_cannot_bypass_validation(assurance_env):
    plan = assurance_env.service.create_change_plan("default", "x", "y", ["a1"])
    with pytest.raises(ValueError, match="invalid_change_status"):
        assurance_env.service.update_change_plan("default", plan["change_id"], {"status": "completed"})


def test_overview_attention_includes_incident_and_schedule_errors(assurance_env):
    assurance_env.service.create_incident("default", "x", "y")
    overview = assurance_env.service.get_overview("default")
    assert overview["health"] == "attention"
    assert overview["counts"]["open_incidents"] == 1


def test_missing_collected_task_recovers_schedule(assurance_env):
    assurance_env.add_task("ins_base")
    baseline = assurance_env.service.create_baseline("default", "east", inspection_task_id="ins_base")
    schedule = assurance_env.service.create_schedule("default", "hourly", baseline["baseline_id"], 60)
    schedule.update({"state": "collecting", "last_task_id": "missing"})
    assurance_env.store.save("default", "schedules", schedule["schedule_id"], schedule)
    assurance_env.service._run_schedule("default", schedule)
    recovered = assurance_env.store.get("default", "schedules", schedule["schedule_id"])
    assert recovered["state"] == "idle"
    assert recovered["error"] == "inspection_task_missing"


def test_naive_or_invalid_schedule_time_is_not_compared_to_aware_clock(assurance_env):
    assert assurance_env.service._parse_dt("2026-07-15T08:00:00") is None
    assert assurance_env.service._parse_dt("not-a-time") is None


def test_scheduler_skips_non_workspace_directories(assurance_env, tmp_path, monkeypatch):
    (tmp_path / ".graph").mkdir()
    (tmp_path / "default").mkdir()
    scanned: list[str] = []

    class NoopLock:
        def __init__(self, workspace_id, timeout=0):
            scanned.append(workspace_id)
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    monkeypatch.setattr(assurance_env.service, "get_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(assurance_env.service, "IndexLock", NoopLock)
    monkeypatch.setattr(assurance_env.service, "list_schedules", lambda _ws: [])
    assurance_env.service.run_due_schedules()
    assert scanned == ["default"]


def test_service_rejects_string_asset_list_and_non_boolean_schedule_state(assurance_env):
    with pytest.raises(TypeError, match="asset_ids_must_be_array"):
        assurance_env.service.impact_analysis("default", "a1")
    assurance_env.add_task("ins_base")
    baseline = assurance_env.service.create_baseline("default", "east", inspection_task_id="ins_base")
    schedule = assurance_env.service.create_schedule("default", "hourly", baseline["baseline_id"], 60)
    with pytest.raises(TypeError, match="schedule_enabled_must_be_boolean"):
        assurance_env.service.update_schedule("default", schedule["schedule_id"], {"enabled": "false"})


def test_http_rejects_malformed_json_and_string_asset_ids(assurance_env, monkeypatch):
    from flask import Flask
    from backend.api.assurance_routes import register_assurance_routes

    monkeypatch.setattr(assurance_env.service, "start_scheduler", lambda: None)
    app = Flask(__name__)
    register_assurance_routes(app)
    client = app.test_client()
    malformed = client.post("/api/assurance/checks", data="{", content_type="application/json")
    assert malformed.status_code == 400
    response = client.post("/api/assurance/topology/impact", json={"workspace_id": "default", "asset_ids": "a1"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "asset_ids_must_be_string_array"
    unconfirmed = client.post("/api/assurance/records/clear", json={"workspace_id": "default"})
    assert unconfirmed.status_code == 400
    assert unconfirmed.get_json()["error"] == "confirm_required"
    cleared = client.post("/api/assurance/records/clear", json={"workspace_id": "default", "confirm": True})
    assert cleared.status_code == 200
    assert cleared.get_json()["preserved"] == ["cmdb_assets", "inspection_tasks", "artifacts", "sessions", "reports"]


def test_clear_assurance_records_is_confirmed_scoped_and_complete(assurance_env):
    assurance_env.add_task("ins_base")
    assurance_env.service.create_baseline("default", "east", inspection_task_id="ins_base")
    assurance_env.service.create_change_plan("default", "routing", "adjust preference", ["a1"])

    with pytest.raises(ValueError, match="confirm_required"):
        assurance_env.service.clear_assurance_records("default")

    result = assurance_env.service.clear_assurance_records("default", confirm=True)
    assert result["deleted"] >= 3
    assert "artifacts" in result["preserved"]
    assert all(assurance_env.store.list_records("default", kind) == [] for kind in assurance_env.store.record_kinds())


def test_clear_assurance_records_rejects_active_work(assurance_env):
    assurance_env.service.start_assurance_operation("default", "topology_refresh")
    with pytest.raises(ValueError, match="assurance_records_not_ready_active_tasks"):
        assurance_env.service.clear_assurance_records("default", confirm=True)


def test_topology_does_not_infer_from_duplicate_or_nested_identifiers(assurance_env, monkeypatch):
    assets = [
        {"asset_id": "a1", "name": "PE1", "host": "10.0.0.1", "type": "router"},
        {"asset_id": "a2", "name": "ASBR-PE1", "host": "10.0.0.1", "type": "router"},
    ]
    monkeypatch.setattr(assurance_env.service.cmdb_service, "list_assets", lambda _ws: assets)
    task = assurance_env.add_task("ins_nested", output="ASBR-PE1 status is up at 10.0.0.1")
    task.devices["a2"] = task.devices.pop("a1")
    task.devices["a2"].asset_id = "a2"
    topology = assurance_env.service.build_topology("default", "ins_nested")
    assert topology["edges"] == []
