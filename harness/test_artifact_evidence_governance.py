from artifacts.governance import AUTHORITY_POLICY, build_governance, governance_summary
from artifacts.schemas import ArtifactRecord


def _record(
    artifact_id: str,
    created_at: str,
    quality: str,
    *,
    asset_id: str = "a1",
    assurance_kind: str = "",
    assurance_ref_id: str = "",
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        workspace_id="default",
        artifact_type="inspection_raw",
        created_at=created_at,
        metadata={
            "asset_id": asset_id,
            "script_profile_id": "h3c_general",
            "evidence_role": "raw_observation",
            "evidence_key": f"inspection:{asset_id}:h3c_general",
            "evidence_quality": quality,
            "producer_kind": "inspection_task",
            "producer_id": f"ins_{artifact_id}",
            "assurance_kind": assurance_kind,
            "assurance_ref_id": assurance_ref_id,
        },
    )


def test_latest_complete_observation_is_authoritative():
    old = _record("old", "2026-07-16T01:00:00+00:00", "complete")
    current = _record("current", "2026-07-16T02:00:00+00:00", "complete")
    projection = build_governance([old, current])
    assert projection["old"]["authority_status"] == "historical"
    assert projection["current"]["authority_status"] == "authoritative"
    assert projection["current"]["authority_policy"] == AUTHORITY_POLICY


def test_newer_partial_observation_never_replaces_complete_authority():
    complete = _record("complete", "2026-07-16T01:00:00+00:00", "complete")
    partial = _record("partial", "2026-07-16T03:00:00+00:00", "partial")
    projection = build_governance([complete, partial])
    assert projection["complete"]["authority_status"] == "authoritative"
    assert projection["partial"]["authority_status"] == "incomplete"
    assert projection["partial"]["is_latest_observation"] is True


def test_partial_is_provisional_when_stream_has_no_complete_observation():
    partial = _record("partial", "2026-07-16T03:00:00+00:00", "partial")
    projection = build_governance([partial])
    assert projection["partial"]["authority_status"] == "provisional"


def test_streams_are_isolated_by_asset_and_script_profile():
    first = _record("a1", "2026-07-16T01:00:00+00:00", "complete", asset_id="a1")
    second = _record("a2", "2026-07-16T02:00:00+00:00", "complete", asset_id="a2")
    report = ArtifactRecord(artifact_id="report", artifact_type="report")
    summary = governance_summary([first, second, report])
    assert summary["evidence_streams"] == 2
    assert summary["authoritative"] == 2
    assert summary["deliverables"] == 1


def test_redacted_evidence_keys_use_asset_streams():
    first = _record("a1", "2026-07-16T01:00:00+00:00", "complete", asset_id="a1")
    second = _record("a2", "2026-07-16T02:00:00+00:00", "complete", asset_id="a2")
    first.metadata["evidence_key"] = "[REDACTED_SECRET]"
    second.metadata["evidence_key"] = "[REDACTED_SECRET]"

    projection = build_governance([first, second])

    assert projection["a1"]["authority_status"] == "authoritative"
    assert projection["a2"]["authority_status"] == "authoritative"
    assert projection["a1"]["evidence_key"] == "inspection:a1:h3c_general"
    assert projection["a2"]["evidence_key"] == "inspection:a2:h3c_general"


def test_impact_evidence_never_replaces_current_state_authority():
    baseline = _record(
        "baseline", "2026-07-16T01:00:00+00:00", "complete",
        assurance_kind="baseline_capture", assurance_ref_id="op_1",
    )
    impact = _record(
        "fault_propagation", "2026-07-16T02:00:00+00:00", "complete",
        assurance_kind="fault_propagation", assurance_ref_id="op_1",
    )

    projection = build_governance([baseline, impact])

    assert projection["baseline"]["authority_domain"] == "current_state"
    assert projection["baseline"]["authority_status"] == "authoritative"
    assert projection["fault_propagation"]["authority_domain"] == "contextual"
    assert projection["fault_propagation"]["authority_status"] == "contextual"


def test_newer_baseline_capture_replaces_only_the_same_current_state_stream():
    old = _record(
        "old-baseline", "2026-07-16T01:00:00+00:00", "complete",
        assurance_kind="baseline_capture", assurance_ref_id="op_1",
    )
    current = _record(
        "current-baseline", "2026-07-16T03:00:00+00:00", "complete",
        assurance_kind="baseline_capture", assurance_ref_id="op_2",
    )

    projection = build_governance([old, current])

    assert projection["old-baseline"]["authority_status"] == "historical"
    assert projection["current-baseline"]["authority_status"] == "authoritative"
    assert projection["current-baseline"]["authority_domain"] == "current_state"


def test_schedule_evidence_cannot_become_current_state_authority_even_with_stale_metadata():
    schedule = _record(
        "schedule", "2026-07-16T04:00:00+00:00", "complete",
        assurance_kind="schedule", assurance_ref_id="sched_1",
    )
    schedule.metadata["authority_domain"] = "current_state"

    projection = build_governance([schedule])

    assert projection["schedule"]["authority_domain"] == "contextual"
    assert projection["schedule"]["authority_status"] == "contextual"


def test_hard_delete_removes_payload_metadata_and_run_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path))
    import storage.workspace_store as workspace_manager

    from artifacts.store import delete_artifact, get_artifact, get_run_artifacts, save_artifact
    from storage.file_store import get_file_record

    record = save_artifact(
        "default",
        content="inspection output",
        artifact_type="inspection_raw",
        title="Device inspection",
        run_id="run_delete_test",
    )
    assert record is not None
    payload = tmp_path / "default" / record.relative_path
    assert payload.is_file()

    assert delete_artifact("default", record.artifact_id, hard=True) is True
    assert get_artifact("default", record.artifact_id) is None
    assert not payload.exists()
    assert get_file_record("default", record.file_id) is None
    run_index = get_run_artifacts("default", "run_delete_test")
    assert all(
        item.get("artifact_id") != record.artifact_id
        for field in ("input_artifacts", "output_artifacts", "report_artifacts", "temp_artifacts")
        for item in run_index.get(field, [])
    )
    artifact_index = tmp_path / "default" / "index" / "artifacts.jsonl"
    assert record.artifact_id not in artifact_index.read_text(encoding="utf-8")
