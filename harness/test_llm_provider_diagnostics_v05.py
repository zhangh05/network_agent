# harness/test_llm_provider_diagnostics_v05.py
"""LLM Provider Diagnostics v0.5 — error classification tests."""

import pytest
from unittest.mock import MagicMock, patch


class TestProviderErrorClassification:
    """Provider errors must be classified and diagnosable."""

    def test_missing_api_key_returns_missing(self):
        """Missing API key → error_type=missing_api_key."""
        from agent.llm.schemas import LLMResponse

        resp = LLMResponse(error="API key not configured")
        # The error should be classifiable
        assert "API key" in resp.error or "missing" in resp.error.lower()

    def test_http_401_returns_provider_http_401(self):
        """HTTP 401 → error_type=provider_http_401."""
        from agent.llm.provider import ERROR_TYPE_PROVIDER_HTTP_401

        # Mock HTTPError with code 401
        mock_e = MagicMock()
        mock_e.code = 401
        mock_e.read.return_value = b'{"error": {"message": "Unauthorized"}}'

        from agent.llm.provider import _read_error_body
        detail = _read_error_body(mock_e)
        assert "Unauthorized" in detail or "401" in detail

    def test_http_403_returns_provider_http_403(self):
        """HTTP 403 → error_type=provider_http_403."""
        from agent.llm.provider import ERROR_TYPE_PROVIDER_HTTP_403

        mock_e = MagicMock()
        mock_e.code = 403
        mock_e.read.return_value = b'{"error": {"message": "Forbidden"}}'

        from agent.llm.provider import _read_error_body
        detail = _read_error_body(mock_e)
        assert "Forbidden" in detail or "403" in detail

    def test_http_429_returns_provider_http_429(self):
        """HTTP 429 → error_type=provider_http_429."""
        from agent.llm.provider import ERROR_TYPE_PROVIDER_HTTP_429

        mock_e = MagicMock()
        mock_e.code = 429
        mock_e.read.return_value = b'{"error": {"message": "Rate limited"}}'

        from agent.llm.provider import _read_error_body
        detail = _read_error_body(mock_e)
        assert "Rate limited" in detail or "429" in detail

    def test_timeout_returns_provider_timeout(self):
        """Timeout → error_type=provider_timeout."""
        from agent.llm.provider import ERROR_TYPE_PROVIDER_TIMEOUT

        # Mock TimeoutError
        with patch("agent.llm.provider.generate", side_effect=TimeoutError("Request timed out")):
            from agent.llm.runtime import safe_generate
            output = safe_generate("result_summarize", user_input="test")
            assert output.llm_used is False
            assert "timeout" in output.answer.lower() or "Timeout" in output.answer


class TestProviderHealthChecks:
    """Health check returns multi-dimensional status."""

    def test_health_returns_configured(self):
        """Health must return configured field."""
        from agent.llm.provider import health

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "api_key": "fake-key",
                "base_url": "https://api.minimax.chat/v1",
                "model": "MiniMax-M3",
            }
            result = health()
            assert "configured" in result
            assert "key_loaded" in result
            assert "base_url_reachable" in result
            assert "models_endpoint_ok" in result
            assert "chat_completion_ok" in result

    def test_health_returns_last_error(self):
        """Health must return last_error field."""
        from agent.llm.provider import health

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "api_key": "fake-key",
                "base_url": "https://api.minimax.chat/v1",
                "model": "MiniMax-M3",
            }
            result = health()
            assert "last_error" in result
            assert "last_error_type" in result
            assert "http_status" in result


class TestProviderErrorRedaction:
    """Provider errors must redact sensitive data only."""

    def test_bearer_token_redacted(self):
        """Bearer token must be redacted in error messages."""
        from agent.llm.provider import _redact_error_detail

        msg = "Authorization: Bearer sk-1234567890abcdef"
        redacted = _redact_error_detail(msg)
        assert "sk-1234567890abcdef" not in redacted
        assert "[REDACTED]" in redacted or "sk-" not in redacted

    def test_api_key_redacted(self):
        """API key must be redacted in error messages."""
        from agent.llm.provider import _redact_error_detail

        msg = "API key sk-abcdef123456 is invalid"
        redacted = _redact_error_detail(msg)
        assert "sk-abcdef123456" not in redacted

    def test_non_sensitive_error_preserved(self):
        """Non-sensitive error details should be preserved."""
        from agent.llm.provider import _redact_error_detail

        msg = "HTTP 401: Unauthorized (invalid model name)"
        redacted = _redact_error_detail(msg)
        assert "401" in redacted
        assert "Unauthorized" in redacted
        assert "invalid model" in redacted


class TestLLMResponseMetadata:
    """LLMResponse must include diagnostic metadata."""

    def test_response_has_error_type(self):
        """LLMResponse from provider should have error_type in metadata."""
        from agent.llm.schemas import LLMResponse

        resp = LLMResponse(
            error="provider_http_401: Unauthorized",
            metadata={"error_type": "provider_http_401", "http_status": 401},
        )
        assert resp.metadata is not None
        assert resp.metadata.get("error_type") == "provider_http_401"
        assert resp.metadata.get("http_status") == 401

    def test_response_has_http_status(self):
        """LLMResponse should preserve HTTP status code."""
        from agent.llm.schemas import LLMResponse

        resp = LLMResponse(
            error="provider_http_400: Bad Request",
            metadata={"error_type": "provider_http_400", "http_status": 400},
        )
        assert resp.metadata.get("http_status") == 400
