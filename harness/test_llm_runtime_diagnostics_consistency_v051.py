# harness/test_llm_runtime_diagnostics_consistency_v051.py
"""LLM Runtime v0.5.1 — diagnostics consistency tests.

Tests:
1. safe_generate preserves provider error metadata
2. invoke_llm disabled branch has error_type=disabled_by_user
3. request policy receives safe_context and tools (non-blocking)
4. ui_settings empty key uses env_fallback key_source
5. ui_settings disabled not overridden by env
6. auto_default disabled + env key → config_source=env
7. orchestrator has no unused LLMRequest req construction
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSafeGenerateProviderMetadataPassthrough:
    """Fix 1: safe_generate() error branch must pass through provider metadata."""

    def test_safe_generate_preserves_provider_error_metadata(self):
        """Provider error metadata must be merged into SafeLLMOutput.metadata."""
        from agent.llm.schemas import LLMResponse, LLMMessage
        from unittest.mock import MagicMock, patch

        mock_resp = LLMResponse(
            error="provider_http_401: invalid API key",
            metadata={
                "error_type": "provider_http_401",
                "http_status": 401,
                "error_detail": "invalid API key",
            },
        )

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
                "api_key": "sk-fake",
                "base_url": "https://api.minimaxi.com/v1",
            }
            with patch("agent.llm.runtime._build_prompt_messages") as mock_msgs:
                mock_msgs.return_value = [LLMMessage(role="user", content="test")]
                with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
                    from agent.llm.runtime import safe_generate
                    output = safe_generate("result_summarize", user_input="test")

                    assert output.llm_used is False
                    assert output.metadata["provider_error_type"] == "provider_http_401"
                    assert output.metadata["http_status"] == 401
                    assert "invalid API key" in output.metadata.get("provider_error_message", "")
                    assert output.fallback_reason is not None
                    assert "provider_unavailable" in output.fallback_reason
                    assert len(output.answer) > 0


class TestInvokeLLMDisabledErrorType:
    """Fix 2: invoke_llm() disabled branch must have error_type."""

    def test_invoke_llm_disabled_enabled_false(self):
        """enabled=false → error_type=disabled_by_user."""
        from agent.llm.schemas import LLMMessage
        from unittest.mock import patch

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": False,
                "provider_type": "disabled",
                "provider": "disabled",
            }
            from agent.llm.runtime import invoke_llm
            resp = invoke_llm("result_summarize")

            assert resp.error is not None
            assert resp.metadata["error_type"] == "disabled_by_user"
            assert resp.metadata.get("error_detail") is not None

    def test_invoke_llm_disabled_provider_type_disabled(self):
        """provider_type=disabled → error_type=disabled_by_user."""
        from agent.llm.schemas import LLMMessage
        from unittest.mock import patch

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "disabled",
                "provider": "disabled",
            }
            from agent.llm.runtime import invoke_llm
            resp = invoke_llm("result_summarize")

            assert resp.error is not None
            assert resp.metadata["error_type"] == "disabled_by_user"


class TestRequestPolicyReceivesSafeContext:
    """Fix 3: request policy check must pass safe_context and tools."""

    def test_request_policy_receives_safe_context_nonblocking(self):
        """request policy receives safe_context with source_config > 80 chars."""
        from unittest.mock import MagicMock, patch
        from agent.llm.schemas import LLMResponse, LLMMessage

        mock_resp = LLMResponse(content="Provider response", provider="mock", model="mock")

        # safe_context with long source_config (>80 chars to trigger policy)
        safe_ctx = {
            "source_config": "interface GigabitEthernet0/0/1\n ip address 10.1.1.1 255.255.255.0\n ospf 1 area 0\n" * 5,
            "deployable_config": None,
        }

        policy_violations = []

        def capture_check_request(req, state=None):
            # Verify safe_context is in the request
            if req.safe_context:
                sc = req.safe_context.get("source_config", "")
                if len(sc) > 80:
                    policy_violations.append({"rule": "source_config_too_long", "length": len(sc)})
            return MagicMock(allowed=False, violations=policy_violations)

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
                "api_key": "sk-fake",
                "base_url": "https://api.minimaxi.com/v1",
            }
            with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
                with patch("agent.llm.policy.check_request", side_effect=capture_check_request):
                    from agent.llm.runtime import safe_generate
                    output = safe_generate(
                        "result_summarize",
                        user_input="test",
                        safe_context=safe_ctx,
                    )

                    # Provider should still be called (non-blocking)
                    assert output.llm_used is True
                    # Answer should be returned
                    assert len(output.answer) > 0
                    # Policy violations should be in warnings
                    assert len(output.metadata.get("request_policy_violations", [])) > 0


class TestKeySourceEnvFallback:
    """Fix 4: key_source must distinguish ui_settings / env_fallback / env."""

    def test_ui_settings_empty_key_uses_env_fallback(self):
        """source=ui_settings, enabled=true, no api_key, env has key → key_source=env_fallback."""
        import os
        from unittest.mock import patch

        ui = {
            "enabled": True,
            "provider": "minimax",
            "source": "ui_settings",
            "model": "MiniMax-M3",
            "api_key": "",  # No key in UI
        }

        with patch("agent.llm.settings.load_llm_settings", return_value=ui):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="env-key-123456"):
                from agent.llm.settings import resolve_effective_llm_config
                cfg = resolve_effective_llm_config()

                assert cfg["enabled"] is True
                assert cfg["key_loaded"] is True
                assert cfg["key_source"] == "env_fallback"
                assert cfg["key_fallback_used"] is True
                assert cfg["config_source"] == "ui_settings"

    def test_ui_settings_disabled_not_overridden_by_env(self):
        """source=ui_settings, enabled=false + env key → enabled=false (not overridden)."""
        from unittest.mock import patch

        ui = {
            "enabled": False,
            "provider": "disabled",
            "source": "ui_settings",
        }

        with patch("agent.llm.settings.load_llm_settings", return_value=ui):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="env-key-123456"):
                from agent.llm.settings import resolve_effective_llm_config
                cfg = resolve_effective_llm_config()

                assert cfg["enabled"] is False
                assert cfg["key_source"] == "none"
                assert cfg["key_loaded"] is False

    def test_auto_default_disabled_env_key_overrides_to_env_source(self):
        """auto_default enabled=false + env key → enabled=true, config_source=env, key_source=env."""
        from unittest.mock import patch

        auto_cfg = {
            "enabled": False,
            "provider": "minimax",
            "model": "MiniMax-M3",
            "source": "auto_default",
        }

        with patch("agent.llm.settings.load_llm_settings", return_value=auto_cfg):
            with patch("agent.llm.key_resolver.resolve_api_key", return_value="env-key-123456"):
                from agent.llm.settings import resolve_effective_llm_config
                cfg = resolve_effective_llm_config()

                assert cfg["enabled"] is True
                assert cfg["config_source"] == "env"
                assert cfg["key_source"] == "env"
                assert cfg.get("enabled_reason") == "env_key_override_auto_default"


class TestOrchestratorNoUnusedReq:
    """Fix 5: orchestrator must not have unused LLMRequest constructions."""

    def test_orchestrator_has_no_unused_req_construction(self):
        """Verify orchestrator source has no remaining unused req = LLMRequest(...) blocks."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        orch_path = root / "agent" / "legacy" / "llm_orchestrator.py"
        source = orch_path.read_text()

        # LLMRequest should only appear in the import line
        llm_request_lines = [l for l in source.split("\n") if "LLMRequest" in l and not l.strip().startswith("#")]

        # Should only have the import line and possibly docs/comments
        actual_usage_lines = [l for l in llm_request_lines if "LLMRequest(" in l and "from agent.llm.schemas import" not in l]
        assert len(actual_usage_lines) == 0, (
            f"Found {len(actual_usage_lines)} unused LLMRequest( constructions:\n"
            + "\n".join(actual_usage_lines)
        )
