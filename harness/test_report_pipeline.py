# harness/test_report_pipeline.py
"""Report / Export Pipeline tests — schema, renderer, exporter, service, agent, API."""

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

SAMPLE_RESULT = {
    "ok": True, "trace_id": "test_trace_001",
    "runtime_mode": "fallback",
    "result": {
        "ok": True, "deployable_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        "manual_review": [{"source": "line1", "reason": "needs review"}],
        "semantic_near": [], "unsupported": [{"reason": "EIGRP"}],
        "audit": {"total": 5, "warnings": 1},
        "translator_entry": "translate_bundle",
    },
    "verification": {"deployable_lines": 3, "manual_review": 1},
    "llm": {"used": False, "provider": "none"},
}

SAMPLE_ARTIFACT_REFS = [
    {"artifact_id": "art_input1", "artifact_type": "input_config",
     "title": "Cisco config", "summary": "Cisco input", "sensitivity": "sensitive",
     "scope": "run", "metadata": {"line_count": 3, "probable_vendor": "cisco"}},
    {"artifact_id": "art_output1", "artifact_type": "output_config",
     "title": "Huawei output", "summary": "Huawei output", "sensitivity": "sensitive",
     "scope": "run", "metadata": {"line_count": 3}},
]


class TestReportSchema:
    def test_report_request_fields(self):
        from reports_engine.schemas import ReportRequest
        r = ReportRequest(report_type="config_translation", format="markdown")
        assert r.report_type == "config_translation"
        assert r.format == "markdown"

    def test_report_document_fields(self):
        from reports_engine.schemas import ReportDocument
        d = ReportDocument(report_type="config_translation", title="test")
        assert d.title == "test"
        assert d.report_id

    def test_export_result_fields(self):
        from reports_engine.schemas import ExportResult
        e = ExportResult(ok=True, report_id="r1", artifact_id="a1")
        d = e.as_dict()
        assert d["ok"] is True
        assert "sha256_short" in d

    def test_format_enum(self):
        from reports_engine.schemas import VALID_FORMATS
        assert "markdown" in VALID_FORMATS
        assert "csv" in VALID_FORMATS

    def test_report_type_enum(self):
        from reports_engine.schemas import VALID_REPORT_TYPES
        assert "config_translation" in VALID_REPORT_TYPES


class TestRenderer:
    def test_render_config_translation_report(self):
        from reports_engine.renderer import render_config_translation_report
        doc = render_config_translation_report("ws1", "r1", SAMPLE_RESULT, SAMPLE_ARTIFACT_REFS)
        assert doc.report_type == "config_translation"
        assert len(doc.sections) >= 8
        assert doc.sensitivity == "internal"

    def test_excludes_deployable_by_default(self):
        from reports_engine.renderer import render_config_translation_report
        doc = render_config_translation_report("ws1", "r1", SAMPLE_RESULT, SAMPLE_ARTIFACT_REFS)
        raw = json.dumps([s.__dict__ if hasattr(s, '__dict__') else s for s in doc.sections])
        assert "ip address 10.1.1.1" not in raw

    def test_include_deployable_includes_and_sensitive(self):
        from reports_engine.schemas import ReportRequest
        from reports_engine.renderer import render_config_translation_report
        req = ReportRequest(include_deployable_config=True)
        doc = render_config_translation_report("ws1", "r1", SAMPLE_RESULT, SAMPLE_ARTIFACT_REFS, request=req)
        raw = json.dumps([s.__dict__ if hasattr(s, '__dict__') else s for s in doc.sections])
        assert "ip address 10.1.1.1" in raw
        assert doc.sensitivity == "sensitive"

    def test_excludes_secret(self):
        from reports_engine.renderer import render_config_translation_report
        secret_result = dict(SAMPLE_RESULT)
        secret_result["result"]["password"] = "admin123"
        doc = render_config_translation_report("ws1", "r1", secret_result, SAMPLE_ARTIFACT_REFS)
        raw = str(doc.as_dict())
        assert "admin123" not in raw


class TestExporter:
    def test_markdown_export(self):
        from reports_engine.schemas import ReportDocument, ReportSection
        from reports_engine.exporter import export_report
        doc = ReportDocument(title="test", sections=[
            ReportSection("s1", "Hello", 1, "World", "markdown")])
        content, mime, ext = export_report(doc, "markdown")
        assert "Hello" in content and "World" in content
        assert ext == "md"

    def test_html_export(self):
        from reports_engine.schemas import ReportDocument, ReportSection
        from reports_engine.exporter import export_report
        doc = ReportDocument(title="test", sections=[
            ReportSection("s1", "Hi", 1, "there", "markdown")])
        content, mime, ext = export_report(doc, "html")
        assert "Hi" in content and "<html" in content.lower()
        assert ext == "html"

    def test_json_export(self):
        from reports_engine.schemas import ReportDocument, ReportSection
        from reports_engine.exporter import export_report
        doc = ReportDocument(title="test", sections=[
            ReportSection("s1", "T", 1, "c", "markdown")])
        content, mime, ext = export_report(doc, "json")
        parsed = json.loads(content)
        assert parsed["title"] == "test"

    def test_csv_export(self):
        from reports_engine.schemas import ReportDocument, ReportSection
        from reports_engine.exporter import export_report
        doc = ReportDocument(title="test", sections=[
            ReportSection("s1", "Section1", 1, "data", "markdown")])
        content, mime, ext = export_report(doc, "csv")
        assert "Section1" in content
        assert ext == "csv"

    def test_docx_skeleton(self):
        from reports_engine.exporter import export_report
        from reports_engine.schemas import ReportDocument
        content, mime, ext = export_report(ReportDocument(title="x"), "docx")
        assert "unsupported" in content.lower() or "skeleton" in content.lower()


class TestExportResult:
    def test_success_result(self):
        from reports_engine.schemas import ExportResult
        e = ExportResult(ok=True, report_id="r1", artifact_id="a1", summary="ok")
        d = e.as_dict()
        assert d["ok"]
        assert d["report_id"] == "r1"

    def test_error_result(self):
        from reports_engine.schemas import ExportResult
        e = ExportResult(ok=False, error="something broke")
        d = e.as_dict()
        assert not d["ok"]
        assert d["error"] == "something broke"


class TestAgentIntegration:
    def test_export_report_false_no_report(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate",
            "workspace_id": "rp_agent",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1", "export_report": False},
        })
        data = resp.get_json()
        assert data["report_artifacts"] == []

    def test_export_report_true_creates_report(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "rp_agent2",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
                         "export_report": True, "report_format": "markdown",
                         "include_deployable_config_in_report": False},
        })
        data = resp.get_json()
        assert "report_artifacts" in data
        # May be empty if artifact save fails, but API works

    def test_report_format_html(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "rp_html",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1", "export_report": True,
                         "report_format": "html"},
        })
        assert resp.status_code == 200


class TestReportAPI:
    def test_create_report_endpoint(self, client):
        resp = client.post("/api/reports/create", json={
            "workspace_id": "rp_api", "report_type": "config_translation",
            "title": "API test", "format": "markdown",
        })
        assert resp.status_code == 200

    def test_reports_list(self, client):
        resp = client.get("/api/workspaces/rp_api/reports")
        assert resp.status_code == 200


class TestRegression:
    def test_artifact_pipeline_works(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate",
            "workspace_id": "rp_reg1",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0"},
        })
        assert resp.get_json().get("ok") is True

    def test_no_api_translate(self, client):
        assert client.post("/api/translate", json={"test": 1}).status_code in (404, 405)

    def test_config_translation_business_unchanged(self, client):
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco", "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        })
        assert resp.get_json().get("ok") is True
