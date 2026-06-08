# harness/test_tool_runtime_catalog_v021.py
"""Tool Runtime Catalog v0.2.1 — API verification tests.

Verifies:
  - /api/tools/catalog returns 55 tools
  - Category counts correct
  - Metadata fields complete (no handlers/secrets/paths)
  - No invoke endpoint
"""

import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


EXPECTED_CATEGORY_COUNTS = {
    "artifact": 7,
    "parser": 3,
    "report": 6,
    "command": 2,
    "knowledge": 6,
    "web": 5,
    "session": 7,
    "runtime": 5,
    "text": 8,
    "workspace": 5,
    "powershell": 1,
}


def _get_client():
    from backend.main import app
    app.testing = True
    return app.test_client()


class TestCatalogEndpoint:
    """Verify /api/tools/catalog endpoint."""

    def test_catalog_returns_200(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        assert resp.status_code == 200

    def test_total_tools_55(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        assert data["count"] == 55, f"Expected 55, got {data['count']}"

    def test_tools_array_length_55(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        assert len(data["tools"]) == 55

    def test_category_counts(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        actual = {}
        for t in data["tools"]:
            c = t["category"]
            actual[c] = actual.get(c, 0) + 1
        for cat, expected in EXPECTED_CATEGORY_COUNTS.items():
            assert actual.get(cat) == expected, \
                f"Category {cat}: expected {expected}, got {actual.get(cat)}"

    def test_all_tools_have_metadata(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        required_fields = {"tool_id", "category", "risk_level", "enabled",
                          "requires_approval", "dry_run_supported", "description"}
        for t in data["tools"]:
            for field in required_fields:
                assert field in t, f"Tool {t.get('tool_id','?')} missing field: {field}"

    def test_no_handler_in_catalog(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        for t in data["tools"]:
            assert "handler" not in t
            assert "handler_fn" not in str(t).lower()

    def test_no_internal_paths_in_catalog(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        catalog_str = json.dumps(data)
        assert "/Users" not in catalog_str
        assert "tool_runtime" not in catalog_str

    def test_no_secrets_in_catalog(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        catalog_str = json.dumps(data)
        assert "password" not in catalog_str.lower()
        assert "secret" not in catalog_str.lower()
        assert "api_key" not in catalog_str.lower()

    def test_no_invoke_endpoint(self):
        """Verify /api/tools/invoke does not return catalog JSON (no invoke)."""
        client = _get_client()
        resp = client.get("/api/tools/invoke")
        # Should NOT return a JSON tool response; SPA returns HTML for unknown routes
        ct = resp.content_type or ""
        assert "json" not in ct.lower(), f"Should not return JSON: {ct}"

    def test_catalog_is_readonly(self):
        """POST/DELETE to catalog should be rejected."""
        client = _get_client()
        for method in [client.post, client.delete, client.put, client.patch]:
            resp = method("/api/tools/catalog")
            assert resp.status_code != 200, f"{method.__name__} should not work on catalog"

    def test_note_field_present(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        assert "note" in data

    def test_high_risk_tools_flagged(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        high = [t for t in data["tools"] if t["risk_level"] == "high"]
        assert len(high) == 2
        for t in high:
            assert not t["enabled"], f"{t['tool_id']} should be disabled"
            assert t["requires_approval"], f"{t['tool_id']} should require approval"

    def test_high_risk_tools_in_catalog(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        tool_ids = {t["tool_id"] for t in data["tools"]}
        assert "command.approved_exec" in tool_ids
        assert "powershell.approved_script" in tool_ids
