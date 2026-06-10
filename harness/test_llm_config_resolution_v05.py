# harness/test_llm_config_resolution_v05.py
"""LLM Config Resolution v0.5 — config precedence tests."""

import os
import json
from unittest.mock import MagicMock, patch


def _write_settings(path, data: dict):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


class TestConfigPrecedence:
    """Test config resolution: ui_settings > env > file > default."""

    def test_no_ui_settings_env_key_exists(self):
        """No UI settings, MINIMAX_API_KEY exists → enabled=true."""
        with patch("agent.llm.settings.load_llm_settings", return_value=None):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="fake-key-123456"):
                with patch("os.environ.get", side_effect=lambda k, default=None: "fake-key" if k == "MINIMAX_API_KEY" else default):
                    from agent.llm.settings import resolve_effective_llm_config
                    cfg = resolve_effective_llm_config()
                    assert cfg["enabled"] is True, "env key should enable LLM"
                    assert cfg["config_source"] == "env"

    def test_auto_default_settings_env_key_exists(self):
        """Auto-default settings (enabled=false) must NOT override env key."""
        auto_cfg = {
            "enabled": False,
            "provider": "minimax",
            "model": "MiniMax-M3",
            "source": "auto_default",
        }
        with patch("agent.llm.settings.load_llm_settings", return_value=auto_cfg):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="fake-key-123456"):
                with patch("os.environ.get", side_effect=lambda k, default=None: "fake-key" if k == "MINIMAX_API_KEY" else default):
                    from agent.llm.settings import resolve_effective_llm_config
                    cfg = resolve_effective_llm_config()
                    # env key exists → enabled should be True (auto_default not authoritative)
                    assert cfg["enabled"] is True, "auto_default enabled=false must not override env key"
                    assert cfg["config_source"] == "env"

    def test_user_saved_disabled_respected(self):
        """User-saved settings with enabled=false → respected."""
        user_cfg = {
            "enabled": False,
            "provider": "minimax",
            "model": "MiniMax-M3",
            "source": "ui_settings",
        }
        with patch("agent.llm.settings.load_llm_settings", return_value=user_cfg):
            from agent.llm.settings import resolve_effective_llm_config
            cfg = resolve_effective_llm_config()
            assert cfg["enabled"] is False, "user_saved disabled should be respected"
            assert cfg["config_source"] == "ui_settings"

    def test_user_saved_api_key_used(self):
        """User-saved settings with api_key → use UI key."""
        user_cfg = {
            "enabled": True,
            "provider": "minimax",
            "model": "MiniMax-M3",
            "api_key": "user-key-123456",
            "source": "ui_settings",
        }
        with patch("agent.llm.settings.load_llm_settings", return_value=user_cfg):
            from agent.llm.settings import resolve_effective_llm_config
            cfg = resolve_effective_llm_config()
            assert cfg["enabled"] is True
            assert cfg["api_key"] == "user-key-123456"
            assert cfg["config_source"] == "ui_settings"

    def test_config_source_values(self):
        """config_source must distinguish: ui_settings / auto_default / env / file / default."""
        # Case 1: ui_settings
        user_cfg = {"enabled": True, "source": "ui_settings", "provider": "minimax"}
        with patch("agent.llm.settings.load_llm_settings", return_value=user_cfg):
            from agent.llm.settings import resolve_effective_llm_config
            cfg = resolve_effective_llm_config()
            assert cfg["config_source"] == "ui_settings"

        # Case 2: auto_default (no env key)
        auto_cfg = {"enabled": False, "source": "auto_default", "provider": "minimax"}
        with patch("agent.llm.settings.load_llm_settings", return_value=auto_cfg):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value=""):
                cfg = resolve_effective_llm_config()
                # auto_default exists, should be used (with enabled=false)
                assert cfg["config_source"] == "auto_default"
                assert cfg["enabled"] is False

        # Case 3: env key (no UI settings)
        with patch("agent.llm.settings.load_llm_settings", return_value=None):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="env-key"):
                with patch("os.environ.get", side_effect=lambda k, default=None: "env-key" if k == "MINIMAX_API_KEY" else default):
                    cfg = resolve_effective_llm_config()
                    assert cfg["config_source"] == "env"


class TestLLMStatusFields:
    """Test /api/agent/llm/status returns correct fields."""

    def test_status_returns_config_source(self):
        """LLM status must return config_source field."""
        from agent.llm.config import get_llm_status
        with patch("agent.llm.config.resolve_provider_config") as mock_resolve:
            mock_resolve.return_value = {
                "enabled": True,
                "provider": "minimax",
                "provider_type": "openai_compatible",
                "model": "MiniMax-M3",
                "config_source": "env",
                "key_loaded": True,
                "key_source": "env",
            }
            status = get_llm_status()
            assert "config_source" in status
            assert status["config_source"] == "env"

    def test_status_returns_key_source(self):
        """LLM status must return key_source field."""
        from agent.llm.config import get_llm_status
        with patch("agent.llm.config.resolve_provider_config") as mock_resolve:
            mock_resolve.return_value = {
                "enabled": True,
                "provider": "minimax",
                "provider_type": "openai_compatible",
                "model": "MiniMax-M3",
                "config_source": "ui_settings",
                "key_loaded": True,
                "key_source": "ui_settings",
            }
            status = get_llm_status()
            assert status["key_source"] == "ui_settings"
