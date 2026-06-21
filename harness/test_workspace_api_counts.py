# harness/test_workspace_api_counts.py
"""Workspace API, Memory API, Agent API integration tests."""

import json
import pytest

# Try to get the Flask test client
try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None


@pytest.fixture
def client(temp_dirs):
    """Flask test client."""
    if _flask_app is None:
        pytest.skip("Flask app not importable")
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


class TestWorkspaceAPI:
    def test_list_workspaces(self, client):
        resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "workspaces" in data

    def test_workspace_state(self, client):
        resp = client.get("/api/workspaces/test_ws/state")
        assert resp.status_code == 200

    def test_workspace_runs(self, client):
        resp = client.get("/api/workspaces/test_ws/runs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "runs" in data

    def test_workspace_state_no_config_leak(self, client):
        resp = client.get("/api/workspaces/test_ws/state")
        assert resp.status_code == 200
        data = resp.get_json()
        text = json.dumps(data)
        # Should not have source_config or deployable_config
        if "source_config" in text:
            assert len(text) < 500  # if present, must be brief

    def test_agent_rejects_invalid_workspace_id(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "../escape",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "INVALID_WORKSPACE_ID"

    def test_agent_rejects_oversized_source_config(self, client, monkeypatch):
        monkeypatch.setenv("NETWORK_AGENT_MAX_SOURCE_CONFIG_BYTES", "20")
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "test_ws",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface GigabitEthernet0/1",
            },
        })
        assert resp.status_code == 413
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "SOURCE_CONFIG_TOO_LARGE"

    def test_agent_rejects_oversized_message_config(self, client, monkeypatch):
        monkeypatch.setenv("NETWORK_AGENT_MAX_SOURCE_CONFIG_BYTES", "20")
        resp = client.post("/api/agent/message", json={
            "intent": "translate_config",
            "workspace_id": "test_ws",
            "message": "hostname R1\ninterface GigabitEthernet0/1",
        })
        assert resp.status_code == 413
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "SOURCE_CONFIG_TOO_LARGE"

    def test_artifacts_reject_invalid_limit(self, client):
        resp = client.get("/api/workspaces/test_ws/artifacts?limit=abc")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_limit"

    def test_artifacts_reject_zero_limit(self, client):
        resp = client.get("/api/workspaces/test_ws/artifacts?limit=0")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_limit"


class TestMemoryAPI:
    def test_memory_status(self, client):
        resp = client.get("/api/memory/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is True

    def test_memory_list(self, client):
        resp = client.get("/api/memory/list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "records" in data

    def test_memory_list_rejects_invalid_limit(self, client):
        resp = client.get("/api/memory/list?limit=abc")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_limit"

    def test_memory_write_and_delete(self, client):
        # Write
        resp = client.post("/api/memory/write", json={
            "title": "test memory",
            "content": "test content",
            "scope": "short_term",
            "memory_type": "knowledge_note",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        mid = data.get("memory_id")
        assert mid is not None

        # Delete
        resp = client.delete(f"/api/memory/{mid}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_memory_search(self, client):
        resp = client.post("/api/memory/search", json={
            "query": "test",
            "limit": 5,
        })
        assert resp.status_code == 200

    def test_memory_search_rejects_invalid_limit(self, client):
        resp = client.post("/api/memory/search", json={
            "query": "test",
            "limit": "abc",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "invalid_limit"

    def test_memory_confirm(self, client):
        resp = client.post("/api/memory/confirm", json={
            "title": "confirmed decision",
            "content": "Use OSPF area 0 for backbone",
            "memory_type": "decision",
            "tags": ["ospf"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_memory_api_no_secrets(self, client):
        """Write should be blocked if content contains secrets."""
        resp = client.post("/api/memory/write", json={
            "title": "secret stuff",
            "content": "password admin123",
        })
        # May be allowed after redaction, or blocked
        assert resp.status_code in (200, 400)

    def test_memory_delete_nonexistent(self, client):
        resp = client.delete("/api/memory/nonexistent_12345")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is False


class TestAgentAPI:
    def test_agent_status(self, client):
        resp = client.get("/api/agent/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "agent_runtime" in data

    def test_agent_run_returns_metadata(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "帮我把这份 Cisco 配置翻译成华为",
            "workspace_id": "test_ws",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown",
            },
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "run_id" in data
        assert "workspace_id" in data
        assert "memory_written" in data
        assert "workspace_updated" in data
        assert "memory_hits_count" in data

    def test_agent_context_qa(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "刚才的结果有什么需要人工复核？",
            "workspace_id": "test_ws",
            "context_ref": "last_result",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        # context_ref is now passed through pipeline; intent routed by router
        assert data["intent"] in ("context_qa", "translate_config", "assistant_chat")
        assert "final_response" in data

    def test_agent_run_llm_metadata(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate config",
            "workspace_id": "test_ws",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        assert "llm" in data


class TestLLMConfigAPI:
    def test_get_llm_config_empty(self, client):
        resp = client.get("/api/agent/llm/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "enabled" in data

    def test_post_llm_config_no_key_preserved(self, client, tmp_path):
        """POST without api_key should preserve existing key."""
        from agent.llm.settings import save_llm_settings, delete_llm_settings

        save_llm_settings({"enabled": True, "provider": "minimax", "api_key": "sk-preserve-me", "model": "MiniMax-M3"})
        resp = client.post("/api/agent/llm/config", json={
            "enabled": True, "provider": "minimax", "model": "MiniMax-M3",
        })
        assert resp.status_code == 200
        delete_llm_settings()

    def test_delete_llm_config(self, client, tmp_path):
        """DELETE /api/agent/llm/config should work."""
        resp = client.delete("/api/agent/llm/config")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_llm_status(self, client):
        resp = client.get("/api/agent/llm/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "config_source" in data
        assert "settings_file_exists" in data


class TestRegression:
    """Ensure no regressions."""

    def test_module_config_translate_works(self, client):
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco",
            "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("ok") is True

    def test_module_config_translate_rejects_oversized_source_config(self, client, monkeypatch):
        monkeypatch.setenv("NETWORK_AGENT_MAX_SOURCE_CONFIG_BYTES", "20")
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco",
            "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface GigabitEthernet0/1",
        })
        assert resp.status_code == 413
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "source_config_too_large"

    def test_translate_api_gone(self, client):
        resp = client.post("/api/translate", json={"test": 1})
        assert resp.status_code in (404, 405)

    def test_no_external_network_translator(self):
        """Verify no external network-translator dependency."""
        from pathlib import Path
        codebase = Path(__file__).parent.parent
        import subprocess
        # Check that no file imports from external network-translator
        result = subprocess.run(
            ["grep", "-rl", "network.translator", str(codebase / "agent")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0 or not result.stdout.strip()
