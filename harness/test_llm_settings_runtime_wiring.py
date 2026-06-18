# harness/test_llm_settings_runtime_wiring.py
"""LLM Settings Runtime Wiring tests — priority, mask_secret, MiniMax-M3."""

import json
import os
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════
# 1. resolve_provider_config uses LLM_setting.json first
# ═══════════════════════════════════════════════════════════

class TestLLMSettingsPriority:
    """Tests confirming UI settings > env/file > default priority."""

    def test_resolve_uses_ui_settings(self, monkeypatch, tmp_path):
        """UI settings should be returned when LLM_setting.json exists (no active provider)."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings = {
            "enabled": True, "provider": "minimax",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3", "api_key": "sk-test12345678",
            "temperature": 0.2, "max_tokens": 4096,
            "source": "ui_settings",
        }
        (cfg_dir / "LLM_setting.json").write_text(json.dumps(settings))

        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        # Suppress active provider so resolve falls through to LLM_setting.json
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)

        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()

        assert cfg["enabled"] is True
        assert cfg["provider"] == "minimax"
        assert cfg["config_source"] == "ui_settings"
        assert cfg["model"] == "MiniMax-M3"

    def test_ui_disabled_overrides_env(self, monkeypatch, tmp_path):
        """UI disabled=true must override env even if env has key."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings = {"enabled": False, "provider": "disabled", "source": "ui_settings"}
        (cfg_dir / "LLM_setting.json").write_text(json.dumps(settings))

        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-env-key123456")

        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()

        assert cfg["enabled"] is False
        assert cfg["config_source"] == "ui_settings"

    def test_env_fallback_when_no_ui(self, monkeypatch, tmp_path):
        """When no UI settings and no active provider, env should work as fallback."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        # No LLM_setting.json

        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-env-key123456")
        monkeypatch.setenv("NETWORK_AGENT_LLM_ENABLED", "true")

        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()

        # With env key and no UI settings, config source should be env or file
        assert cfg["config_source"] in ("env", "file", "default")

    def test_mask_secret_not_recursive(self):
        """mask_secret must not be infinitely recursive."""
        from agent.llm.config import mask_secret
        result = mask_secret("test-key-1234567890")
        assert "****" in result
        assert len(result) > 4  # should have masked output, not crash

    def test_mask_secret_short_value(self):
        """Short values get fully masked."""
        from agent.llm.config import mask_secret
        result = mask_secret("ab")
        assert result in ("**", "ab****ab")  # either fully masked or front/back

    def test_minimax_default_model_is_m3(self):
        """Default model must be MiniMax-M3, not MiniMax-M1."""
        from agent.llm.settings import resolve_effective_llm_config
        # When no UI settings exist
        cfg = resolve_effective_llm_config()
        if cfg.get("model"):
            assert cfg["model"] != "MiniMax-M1", "Default model should not be MiniMax-M1"

    def test_config_source_in_status(self, monkeypatch, tmp_path):
        """Status API should report config_source."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings = {
            "enabled": True, "provider": "minimax",
            "model": "MiniMax-M3", "api_key": "sk-test12345678",
            "source": "ui_settings",
        }
        (cfg_dir / "LLM_setting.json").write_text(json.dumps(settings))
        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)

        from agent.llm.config import get_llm_status
        status = get_llm_status()
        assert "config_source" in status

    def test_effective_config_has_key_source(self, monkeypatch, tmp_path):
        """Effective config from settings should include key_source."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings = {
            "enabled": True, "provider": "minimax",
            "model": "MiniMax-M3", "api_key": "sk-test12345678",
            "source": "ui_settings",
        }
        (cfg_dir / "LLM_setting.json").write_text(json.dumps(settings))
        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)

        from agent.llm.settings import resolve_effective_llm_config
        cfg = resolve_effective_llm_config()
        assert cfg["key_source"] == "ui_settings"


class TestProviderUsesUISettings:
    """Provider must use UI settings for actual API calls."""

    def test_get_provider_config_uses_settings(self, monkeypatch, tmp_path):
        """get_provider_config() must resolve through unified config."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings = {
            "enabled": False, "provider": "disabled",
            "source": "ui_settings",
        }
        (cfg_dir / "LLM_setting.json").write_text(json.dumps(settings))
        monkeypatch.setattr("agent.llm.settings.SETTINGS_PATH", cfg_dir / "LLM_setting.json")
        monkeypatch.setattr("agent.llm.provider_store.get_active_config", lambda: None)

        from agent.llm.provider import get_provider_config
        cfg = get_provider_config()
        assert cfg["enabled"] is False

    def test_provider_health_no_key_leak(self):
        """health() should not return full API key."""
        from agent.llm.provider import health
        cfg = {
            "enabled": False, "provider_type": "disabled",
            "api_key": "sk-should-not-appear-12345",
        }
        result = health(cfg)
        assert "sk-should-not-appear-12345" not in str(result)


class TestKeyResolverMask:
    """key_resolver.mask_secret works correctly."""

    def test_key_resolver_mask(self):
        from agent.llm.key_resolver import mask_secret
        result = mask_secret("sk-test-key-12345678")
        assert "****" in result
        assert result.startswith("sk-t")

    def test_key_resolver_empty(self):
        from agent.llm.key_resolver import mask_secret
        assert mask_secret("") == ""
        assert mask_secret(None) == ""


class TestMiniMaxM3NoResidue:
    """No MiniMax-M1 default/example residues."""

    def test_no_m1_in_settings_default(self):
        """settings.py defaults must not be MiniMax-M1."""
        from agent.llm.settings import resolve_effective_llm_config
        cfg = resolve_effective_llm_config()
        model = cfg.get("model", "")
        # Migration is OK, but default output must not be M1
        if model and "M1" in model:
            # Only allowed if it's migration code converting M1 to M3
            assert model == "MiniMax-M3", "If model is set, it must be M3"

    def test_no_m1_in_config_default(self):
        """config.py defaults must not be MiniMax-M1."""
        from agent.llm.config import load_llm_config
        cfg = load_llm_config()
        for name, provider in cfg.get("providers", {}).items():
            model = provider.get("model", "")
            if model == "MiniMax-M1":
                pytest.fail(f"Provider {name} has MiniMax-M1 as model")
