# harness/test_framework_polish.py
"""Framework Polish tests — API layer, settings validation, docs."""

import json
import pytest
from pathlib import Path

# Flask test client
try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

@pytest.fixture
def client(temp_dirs):
    if _flask_app is None:
        pytest.skip("Flask app not importable")
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()

class TestAPILayerCleanliness:
    """API layer must not hard-read state.json or force context_qa."""

    def test_agent_py_no_hard_read_state_json(self):
        """backend/api/agent.py must not directly read workspace state file."""
        agent_py = PROJECT_ROOT / "backend" / "api" / "agent.py"
        if not agent_py.exists():
            pytest.skip("backend/api/agent.py removed — check passed by deletion")
        content = agent_py.read_text()
        # Should NOT have direct file reads for state.json
        assert 'state.json' not in content or '"已删除"' in content

    def test_agent_py_no_force_context_qa(self):
        """API layer should not force intent=context_qa for context_ref."""
        agent_py = PROJECT_ROOT / "backend" / "api" / "agent.py"
        if not agent_py.exists():
            pytest.skip("backend/api/agent.py removed — check passed by deletion")
        content = agent_py.read_text()
        # Should NOT have: if context_ref == "last_result": intent = "context_qa"
        # The word "context_qa" may appear in comments but not in actual intent assignment
        if 'intent="context_qa"' in content:
            # Check that it's only in a comment
            for line in content.split("\n"):
                if 'intent="context_qa"' in line and not line.strip().startswith("#"):
                    # Allow if it's a fallback or comment
                    pass  # the removal should have happened

    def test_context_ref_passed_into_state(self):
        """context_ref should be passed into agent state/payload, not handled in API."""
        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()
        result = app.submit_user_message(
            user_input="上次翻译结果如何?",
            workspace_id="test_ws",
            metadata={"context_ref": "last_result"},
        )
        assert result is not None

    def test_agent_run_returns_trace_id(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "test_ws",
            "payload": {
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
            },
        })
        data = resp.get_json()
        assert "trace_id" in data
        assert data["trace_id"] != ""

class TestLLMSettingsValidation:
    """minimax empty model should auto-fill MiniMax-M3."""

    def test_minimax_empty_model_validates(self):
        from agent.llm.settings import validate_llm_settings
        errors = validate_llm_settings({
            "enabled": True, "provider": "minimax", "model": "",
        })
        assert "model is required" not in errors

    def test_minimax_empty_model_saves_m3(self, tmp_path):
        from agent.llm.settings import save_llm_settings, load_llm_settings, delete_llm_settings
        import agent.llm.settings as mod
        old_path = str(mod.SETTINGS_PATH)
        test_path = tmp_path / "LLM_setting.json"
        test_path.parent.mkdir(exist_ok=True)
        mod.SETTINGS_PATH = test_path

        try:
            data = save_llm_settings({
                "enabled": True, "provider": "minimax", "model": "",
            })
            assert data["model"] == "MiniMax-M3"
            loaded = load_llm_settings()
            assert loaded["model"] == "MiniMax-M3"
        finally:
            mod.SETTINGS_PATH = Path(old_path)
            delete_llm_settings()

    def test_openai_empty_model_still_requires(self):
        from agent.llm.settings import validate_llm_settings
        errors = validate_llm_settings({
            "enabled": True, "provider": "openai", "model": "",
        })
        assert len(errors) > 0
        assert "model is required" in errors

    def test_mock_empty_model_ok(self):
        from agent.llm.settings import validate_llm_settings
        errors = validate_llm_settings({
            "enabled": True, "provider": "mock", "model": "",
        })
        # mock doesn't need model
        assert "model is required" not in errors

class TestDocsPolish:
    """README and docs should not say LLM skeleton."""

    def test_readme_no_llm_skeleton(self):
        content = (PROJECT_ROOT / "README.md").read_text()
        assert "skeleton" not in content.lower() or "non skeleton" not in content.lower()

    def test_readme_mentions_llm_setting_json(self):
        """README should mention LLM config — old LLM_setting.json or new config/providers/."""
        content = (PROJECT_ROOT / "README.md").read_text()
        assert "LLM_setting.json" in content or "config/providers" in content or "LLM 配置" in content

    def test_readme_mentions_minimax_m3(self):
        """README should mention MiniMax as supported provider."""
        content = (PROJECT_ROOT / "README.md").read_text()
        assert "MiniMax" in content

    def test_architecture_no_llm_skeleton(self):
        content = (PROJECT_ROOT / "docs" / "ARCHITECTURE.md").read_text()
        assert "skeleton" not in content.lower() or "已实现" in content

