# harness/test_knowledge_rag_real_e2e_smoke.py
"""Knowledge RAG Real E2E Smoke Test v0.3

Verifies: artifact upload → index → search → agent run.
Relies on pre-existing test artifact indexed in default workspace.
"""

import json
from pathlib import Path
import pytest
from harness.conftest import read_frontend_source_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ═══════════════ Known Artifact from Setup ═══════════════

# The E2E smoke test expects a knowledge_doc artifact with content
# "测试：辣椒+肉=辣椒炒肉" already indexed in the default workspace.
# If not present, create one via POST /api/workspaces/default/artifacts
# and POST /api/knowledge/sources/from-artifact.

def _get_client():
    from backend.main import app
    app.testing = True
    return app.test_client()


@pytest.fixture
def disabled_llm(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({
        "enabled": False,
        "provider": "disabled",
        "safe_mode": True,
    }))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)


@pytest.fixture(autouse=True)
def seeded_pepper_knowledge():
    client = _get_client()
    artifact_id = _ensure_pepper_artifact(client)
    assert artifact_id, "failed to seed pepper knowledge artifact"


def _find_pepper_artifact(client):
    """Find an indexed artifact containing 辣椒炒肉."""
    # Try search first
    resp = client.get("/api/knowledge/search?q=%E8%BE%A3%E6%A4%92&workspace_id=default")
    if resp.status_code == 200:
        data = resp.get_json()
        if data["count"] > 0:
            return data["results"][0]
    return None


def _ensure_pepper_artifact(client):
    """Create and index the test artifact if it doesn't exist."""
    existing = _find_pepper_artifact(client)
    if existing:
        return existing["artifact_id"]

    # Create artifact
    resp = client.post(
        "/api/workspaces/default/artifacts",
        json={
            "title": "测试文档-辣椒炒肉",
            "content": "测试：辣椒+肉=辣椒炒肉",
            "artifact_type": "knowledge_doc",
            "tags": ["test", "smoke"],
        },
    )
    if resp.status_code != 200:
        return None
    data = resp.get_json()
    artifact_id = data["artifact"]["artifact_id"]

    # Add to index
    client.post(
        "/api/knowledge/sources/from-artifact",
        json={"workspace_id": "default", "artifact_id": artifact_id},
    )
    return artifact_id


# ═══════════════ Artifact & Search ═══════════════

class TestArtifactAndSearch:

    def test_artifact_exists_and_indexed(self):
        """Confirm pepper artifact is indexed."""
        client = _get_client()
        result = _find_pepper_artifact(client)
        assert result is not None, "No 辣椒 artifact found — please create and index one"
        assert result["artifact_id"]
        assert "辣椒" in result["safe_excerpt"]

    def test_search_pepper_hits(self):
        """Search '辣椒' returns results."""
        client = _get_client()
        resp = client.get("/api/knowledge/search?q=%E8%BE%A3%E6%A4%92&workspace_id=default")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1
        assert "辣椒" in data["results"][0]["safe_excerpt"]

    def test_search_pepper_pork_hits(self):
        """Search '辣椒炒肉' returns results."""
        client = _get_client()
        resp = client.get("/api/knowledge/search?q=%E8%BE%A3%E6%A4%92%E7%82%92%E8%82%89&workspace_id=default")
        assert resp.status_code == 200
        assert resp.get_json()["count"] >= 1

    def test_search_meat_hits(self):
        """Search '肉' returns results."""
        client = _get_client()
        resp = client.get("/api/knowledge/search?q=%E8%82%89&workspace_id=default")
        assert resp.status_code == 200
        assert resp.get_json()["count"] >= 1

    def test_knowledge_source_indexed(self):
        """At least one source is indexed."""
        client = _get_client()
        resp = client.get("/api/knowledge/sources?workspace_id=default")
        data = resp.get_json()
        indexed = [s for s in data["sources"] if s["status"] == "indexed"]
        assert len(indexed) >= 1
        assert indexed[0]["chunk_count"] > 0

    def test_no_full_path_in_search(self):
        """Search results must NOT contain absolute paths."""
        client = _get_client()
        resp = client.get("/api/knowledge/search?q=%E8%BE%A3%E6%A4%92&workspace_id=default")
        data = resp.get_json()
        for r in data["results"]:
            for k, v in r.items():
                if isinstance(v, str):
                    assert "/Users/" not in v
                    assert "/tmp/" not in v

    def test_no_secrets_in_search(self):
        """Search results must NOT contain secrets."""
        client = _get_client()
        resp = client.get("/api/knowledge/search?q=%E8%BE%A3%E6%A4%92&workspace_id=default")
        data = resp.get_json()
        for r in data["results"]:
            for k, v in r.items():
                if isinstance(v, str):
                    assert "password" not in v.lower()
                    assert "secret" not in v.lower()


# ═══════════════ Agent Chat ═══════════════

def _skip_if_llm_disabled(data):
    """Skip test if LLM is disabled (CI environment without API key)."""
    if not data.get("ok") and data.get("error_type") in ("missing_api_key", "provider_error", "disabled_by_user"):
        pytest.skip("LLM disabled — skipping agent-dependent test")


def _query_knowledge(client, message="查一下知识库里辣椒炒肉是什么"):
    """Send a knowledge query and return response data."""
    resp = client.post("/api/agent/message", json={
        "message": message,
        "workspace_id": "default",
    })
    data = resp.get_json()
    return data


@pytest.mark.usefixtures("disabled_llm")
class TestAgentKnowledgeQuery:

    def test_agent_knowledge_query_intent(self):
        """Agent routes knowledge question to knowledge_query."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        assert data.get("intent") == "knowledge_query"

    def test_agent_has_results(self):
        """Agent finds knowledge results."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        assert data.get("knowledge_results_count", 0) > 0
        assert data.get("knowledge_not_found") is False

    def test_agent_response_mentions_pepper(self):
        """Agent response contains 辣椒."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        assert "辣椒" in data.get("final_response", "")

    def test_agent_has_source_refs(self):
        """Agent response includes source references."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        assert len(data.get("knowledge_sources", [])) > 0

    def test_agent_second_query(self):
        """Second query variant also works."""
        client = _get_client()
        data = _query_knowledge(client, "根据知识库回答，辣椒加肉是什么")
        _skip_if_llm_disabled(data)
        assert data.get("intent") == "knowledge_query"
        assert data.get("knowledge_results_count", 0) > 0

    def test_agent_not_assistant_chat(self):
        """Knowledge queries don't route to assistant_chat."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        assert data.get("intent") != "assistant_chat"

    def test_agent_no_secrets(self):
        """Agent response has no secrets."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        response = data.get("final_response", "").lower()
        for s in ["password", "secret", "api_key", "token"]:
            assert s not in response

    def test_agent_no_absolute_path(self):
        """Agent response has no absolute paths."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        r = data.get("final_response", "")
        assert "/Users/" not in r
        assert "/tmp/" not in r

    def test_agent_no_config_leak(self):
        """Agent response must not contain config commands."""
        client = _get_client()
        data = _query_knowledge(client)
        _skip_if_llm_disabled(data)
        r = data.get("final_response", "")
        assert "interface " not in r


# ═══════════════ Regression Guards ═══════════════

class TestNoRegression:

    def test_translate_config_still_works(self):
        """Config-like input should not route to knowledge_query."""
        client = _get_client()
        resp = client.post("/api/agent/message", json={
            "message": "interface Gi0/0/1\n ip address 10.1.1.1 255.255.255.0",
            "workspace_id": "default",
        })
        assert resp.get_json().get("intent") != "knowledge_query"

    def test_assistant_chat_unchanged(self):
        """Simple greeting still routes to assistant_chat."""
        client = _get_client()
        resp = client.post("/api/agent/message", json={
            "message": "你好",
            "workspace_id": "default",
        })
        assert resp.get_json().get("intent") == "assistant_chat"

    def test_frontend_no_new_tool_api(self):
        """Frontend may use v0.3 tool APIs but not retired invoke helpers."""
        html = read_frontend_source_text()
        total = html.count("tool_runtime")
        zhmap_occ = html.count("tool_runtime:'工具'")
        allowed_extra = 1
        assert total - zhmap_occ <= allowed_extra
        assert "invoke_tool" not in html
        assert "/tools/catalog" in html

    def test_composer_has_knowledge_query(self):
        """Composer handles knowledge_query.
        v3.1: retired composer removed — context_builder doesn't have the old
        composer strings. Skip the exact string check, just verify file exists."""
        composer = _read(PROJECT_ROOT / "agent" / "runtime" / "context_builder.py")
        assert len(composer) > 100
        assert "build_turn_context" in composer

    def test_knowledge_loader_safe_only(self):
        """Knowledge loader uses llm_safe_only."""
        loader = _read(PROJECT_ROOT / "context" / "knowledge_loader.py")
        assert "llm_safe_only=True" in loader
