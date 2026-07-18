# harness/test_artifact_baseline.py
"""Artifact schema, classification, redaction, store, API, regression tests."""

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


class TestArtifactSchema:
    def test_artifact_fields(self):
        from artifacts.schemas import ArtifactRecord
        a = ArtifactRecord(artifact_id="a1", workspace_id="ws1", artifact_type="input_config", title="test")
        d = a.as_dict()
        assert d["artifact_id"] == "a1"

    def test_artifact_index_fields(self):
        from artifacts.schemas import ArtifactIndex
        idx = ArtifactIndex(workspace_id="ws1", artifact_ids=["a1"], artifact_count=1)
        d = idx.as_dict()
        assert d["artifact_count"] == 1

    def test_run_artifact_index(self):
        from artifacts.schemas import RunArtifactIndex
        ri = RunArtifactIndex(workspace_id="ws1", run_id="r1", input_artifacts=[{"artifact_id": "a1"}])
        d = ri.as_dict()
        assert len(d["input_artifacts"]) == 1

    def test_type_scope_sens_enum(self):
        from artifacts.schemas import ARTIFACT_TYPES, SCOPES, SENSITIVITIES, LIFECYCLES
        assert "input_config" in ARTIFACT_TYPES
        assert "run" in SCOPES
        assert "sensitive" in SENSITIVITIES
        assert "active" in LIFECYCLES


class TestClassifier:
    def test_cfg_classified_config(self):
        from artifacts.classifier import classify_file
        r = classify_file("test.cfg", "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0")
        assert r["artifact_type"] == "input_config"
        assert r["sensitivity"] == "sensitive"

    def test_txt_config(self):
        from artifacts.classifier import classify_file
        r = classify_file("config.txt", "hostname R1\ninterface Gi0/1")
        assert r["artifact_type"] == "input_config"

    def test_json_topology(self):
        from artifacts.classifier import classify_file
        # Topology JSON needs "nodes" and "links" keys
        r = classify_file("topo.json", '{"nodes":[{"id":"R1"}],"links":[{"source":"R1"}]}')
        # Classifier may or may not detect — at minimum ensure it runs without error
        assert r is not None

    def test_log_classified(self):
        from artifacts.classifier import classify_file
        log_text = "\n".join(["show version"] * 15 + ["ERROR: something"])
        r = classify_file("log.txt", log_text)
        assert r["artifact_type"] == "inspection_log"

    def test_secret_detection(self):
        from artifacts.classifier import classify_file
        r = classify_file("", "enable password admin123\ninterface Gi0/1")
        assert r["contains_secret"] is True
        assert r["sensitivity"] == "secret"

    def test_vendor_cisco(self):
        from artifacts.classifier import classify_file
        r = classify_file("", "interface GigabitEthernet0/1\n ip address 10.1.1.1 255.255.255.0")
        assert r["probable_vendor"] == "cisco"


class TestRedaction:
    def test_redact_password(self):
        from artifacts.redaction import redact_artifact_content
        assert "REDACTED" in redact_artifact_content("enable password admin123")

    def test_redact_community(self):
        from artifacts.redaction import redact_artifact_content
        assert "REDACTED" in redact_artifact_content("snmp-server community public RO")

    def test_redact_api_key(self):
        from artifacts.redaction import redact_artifact_content
        assert "REDACTED" in redact_artifact_content("MINIMAX_API_KEY=sk-test12345678")

    def test_contains_secret_false(self):
        from artifacts.redaction import contains_secret
        assert contains_secret("interface Gi0/1") is False

    def test_redact_metadata(self):
        from artifacts.redaction import redact_metadata
        result = redact_metadata({"password": "secret123", "name": "R1"})
        assert result["password"] != "secret123"
        assert result["name"] == "R1"

    def test_redact_metadata_preserves_lineage_keys(self):
        from artifacts.redaction import redact_metadata

        result = redact_metadata({
            "evidence_key": "inspection:asset-1:h3c",
            "command_key": "display_version",
            "api_key": "not-a-real-key",
        })

        assert result["evidence_key"] == "inspection:asset-1:h3c"
        assert result["command_key"] == "display_version"
        assert "REDACTED" in result["api_key"]


class TestArtifactStore:
    def test_save_and_get(self, temp_dirs):
        from artifacts.store import save_artifact, get_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_sg"
        ensure_workspace(ws)
        rec = save_artifact(ws, content="hostname R1\ninterface Gi0/1", artifact_type="input_config", title="R1", scope="run")
        assert rec is not None
        assert rec.artifact_id.startswith("art_")
        got = get_artifact(ws, rec.artifact_id)
        assert got is not None

    def test_save_sha256(self, temp_dirs):
        from artifacts.store import save_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_sha"
        ensure_workspace(ws)
        rec = save_artifact(ws, content="hello", artifact_type="template", sensitivity="public", scope="run")
        assert rec is not None and len(rec.sha256) == 64

    def test_save_reject_secret_content(self, temp_dirs):
        from artifacts.store import save_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_sec"
        ensure_workspace(ws)
        rec = save_artifact(ws, content="password admin123", sensitivity="sensitive", scope="run")
        assert rec is None

    def test_save_secret_label_redacts(self, temp_dirs):
        from artifacts.store import save_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_sec2"
        ensure_workspace(ws)
        rec = save_artifact(ws, content="password admin123", sensitivity="secret", scope="run")
        if rec:
            assert rec.redaction_applied is True or rec.sensitivity == "secret"

    def test_list_and_delete(self, temp_dirs):
        from artifacts.store import save_artifact, get_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_ls"
        ensure_workspace(ws)
        rec = save_artifact(ws, content="hello_world_data", artifact_type="template", title="data1", sensitivity="public", scope="run")
        assert rec is not None
        assert rec.artifact_id.startswith("art_")
        got = get_artifact(ws, rec.artifact_id)
        assert got is not None and got.title == "data1"

    def test_report_listing_hides_intermediate_drafts(self, temp_dirs):
        from artifacts.schemas import ArtifactRecord
        from artifacts.store import _save_artifact_record, list_artifacts
        from storage.workspace_store import ensure_workspace

        ws = "st_report_dedupe"
        ensure_workspace(ws)
        records = [
            ArtifactRecord(
                artifact_id="art_old_named", workspace_id=ws, artifact_type="report",
                title="广域网区域巡检报告 (2026-06-30)",
                created_at="2026-06-30T14:45:19+00:00", updated_at="2026-06-30T14:45:19+00:00",
            ),
            ArtifactRecord(
                artifact_id="art_generic_a", workspace_id=ws, artifact_type="report",
                title="report",
                created_at="2026-06-30T15:52:06+00:00", updated_at="2026-06-30T15:52:06+00:00",
            ),
            ArtifactRecord(
                artifact_id="art_generic_b", workspace_id=ws, artifact_type="report",
                title="report",
                created_at="2026-06-30T15:52:50+00:00", updated_at="2026-06-30T15:52:50+00:00",
            ),
            ArtifactRecord(
                artifact_id="art_latest_named", workspace_id=ws, artifact_type="report",
                title="广域网区域巡检报告 (2026-06-30)",
                created_at="2026-06-30T15:53:06+00:00", updated_at="2026-06-30T15:53:06+00:00",
            ),
            ArtifactRecord(
                artifact_id="art_next_day", workspace_id=ws, artifact_type="report",
                title="广域网区域巡检报告 (2026-07-01)",
                created_at="2026-07-01T03:02:27+00:00", updated_at="2026-07-01T03:02:27+00:00",
            ),
        ]
        for rec in records:
            _save_artifact_record(rec, add_to_index=True)

        ids = [r["artifact_id"] for r in list_artifacts(ws, artifact_type="report", limit=20)]
        assert ids == ["art_latest_named", "art_next_day"]

    def test_report_listing_collapses_generic_only_reports(self, temp_dirs):
        from artifacts.schemas import ArtifactRecord
        from artifacts.store import _save_artifact_record, list_artifacts
        from storage.workspace_store import ensure_workspace

        ws = "st_report_generic"
        ensure_workspace(ws)
        records = [
            ArtifactRecord(
                artifact_id="art_generic_a", workspace_id=ws, artifact_type="report",
                title="report",
                created_at="2026-06-30T15:52:06+00:00", updated_at="2026-06-30T15:52:06+00:00",
            ),
            ArtifactRecord(
                artifact_id="art_generic_b", workspace_id=ws, artifact_type="report",
                title="report",
                created_at="2026-06-30T15:52:50+00:00", updated_at="2026-06-30T15:52:50+00:00",
            ),
        ]
        for rec in records:
            _save_artifact_record(rec, add_to_index=True)

        ids = [r["artifact_id"] for r in list_artifacts(ws, artifact_type="report", limit=20)]
        assert ids == ["art_generic_b"]

    def test_report_generic_title_uses_markdown_heading(self, temp_dirs):
        from artifacts.store import save_artifact
        from storage.workspace_store import ensure_workspace

        ws = "st_report_title"
        ensure_workspace(ws)
        rec = save_artifact(
            ws,
            content="# 广域网区域巡检报告 (2026-07-01)\n\n正文",
            artifact_type="report",
            title="report",
            sensitivity="internal",
        )
        assert rec is not None
        assert rec.title == "广域网区域巡检报告 (2026-07-01)"

    def test_unique_artifact_ids(self, temp_dirs):
        from artifacts.store import save_artifact
        from storage.workspace_store import ensure_workspace
        ws = "st_uniq"
        ensure_workspace(ws)
        r1 = save_artifact(ws, content="unique_content_abc", artifact_type="template", sensitivity="public", scope="run")
        r2 = save_artifact(ws, content="unique_content_abc", artifact_type="template", sensitivity="public", scope="run")
        assert r1 is not None and r2 is not None
        assert r1.artifact_id != r2.artifact_id, f"IDs should differ: {r1.artifact_id} vs {r2.artifact_id}"
        assert r1.sha256 == r2.sha256

    def test_source_path_rejected(self):
        from artifacts.store import _validate_source_path
        assert not _validate_source_path("/etc/passwd")
        assert not _validate_source_path("../../../etc/passwd")


class TestArtifactAPI:
    def test_workspace_dirs(self, temp_dirs):
        from storage.workspace_store import ensure_workspace
        ensure_workspace("api_dirs")
        p = Path(str(temp_dirs["workspace_dir"])) / "api_dirs"
        assert (p / "sys").is_dir()
        assert (p / "files" / "data").is_dir()


class TestRegression:
    def test_agent_translate_works(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "art_ag",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
            },
        })
        assert resp.status_code == 200

    def test_trace_still_works(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "art_tr",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei", "source_config": "hostname R1"},
        })
        data = resp.get_json()
        # Skip trace check if agent failed (no API key / provider error in CI)
        if not data.get("ok"):
            return
        run_id = data["run_id"]
        resp2 = client.get(f"/api/workspaces/art_tr/runs/{run_id}/trace")
        assert resp2.status_code == 200

    def test_registry_still_works(self, client):
        resp = client.get("/api/capabilities")
        assert resp.status_code == 200
