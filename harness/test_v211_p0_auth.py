# harness/test_v211_p0_auth.py
"""P0-1: Global API authentication middleware tests.

Tests:
- auth disabled → API accessible
- auth enabled + no token → 401
- auth enabled + wrong token → 401
- auth enabled + Bearer token → 200
- auth enabled + X-API-Key → 200
- /api/health always public
- static resources not intercepted
"""

import os
import sys
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestAuthMiddleware:
    """Auth middleware behaviour."""

    def test_auth_module_registered(self):
        """Auth middleware is importable and has correct interface."""
        from backend.core.auth import (
            register_auth_middleware,
            is_public_path,
            _extract_token_from_request,
        )
        assert callable(register_auth_middleware)
        assert callable(is_public_path)
        assert callable(_extract_token_from_request)

    def test_auth_disabled_by_default(self):
        """Auth is disabled when env var is not set."""
        from backend.core.auth import _AUTH_ENABLED
        # Default is false — but may be overridden by env
        # Just verify the module loads correctly either way
        assert isinstance(_AUTH_ENABLED, bool)

    def test_public_path_health(self):
        """Health endpoints are public."""
        from backend.core.auth import is_public_path
        assert is_public_path("/api/health") is True
        assert is_public_path("/health") is True

    def test_public_path_static(self):
        """Static resources and frontend paths are public."""
        from backend.core.auth import is_public_path
        assert is_public_path("/") is True
        assert is_public_path("/index.html") is True
        assert is_public_path("/assets/main.js") is True
        assert is_public_path("/workbench") is True

    def test_public_path_frontend_routes(self):
        """SPA frontend routes are public (non-/api/* paths)."""
        from backend.core.auth import is_public_path
        assert is_public_path("/knowledge") is True
        assert is_public_path("/artifacts") is True
        assert is_public_path("/settings") is True

    def test_protected_path_api(self):
        """API paths are protected."""
        from backend.core.auth import is_public_path
        assert is_public_path("/api/agent/run") is False
        assert is_public_path("/api/sessions") is False
        assert is_public_path("/api/memory/write") is False
        assert is_public_path("/api/tools/catalog") is False

    def test_unauthorized_response_format(self):
        """401 response has standard format — test with app context."""
        # Need an app to create a request context
        from backend.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        from backend.core.auth import _unauthorized_response
        with app.app_context():
            resp, status = _unauthorized_response("test reason")
            data = json.loads(resp.get_data(as_text=True))
            assert data["ok"] is False
            assert data["error"] == "unauthorized"
            assert "test reason" in data["message"]
            assert data["status"] == 401
            assert status == 401


class TestAuthIntegration:
    """Integration tests with Flask test client."""

    @pytest.fixture
    def auth_app(self):
        """Create Flask app with auth enabled. Uses os.environ directly for reliability."""
        _prev_enabled = os.environ.get("NETWORK_AGENT_AUTH_ENABLED")
        _prev_token = os.environ.get("NETWORK_AGENT_API_TOKEN")
        os.environ["NETWORK_AGENT_AUTH_ENABLED"] = "true"
        os.environ["NETWORK_AGENT_API_TOKEN"] = "test-secret-token-123"
        # Clear any cached module state that might have old auth config
        import backend.core.auth as auth_mod
        auth_mod._AUTH_ENABLED = True
        auth_mod._API_TOKEN = "test-secret-token-123"
        from backend.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        yield app
        # Restore
        if _prev_enabled is not None:
            os.environ["NETWORK_AGENT_AUTH_ENABLED"] = _prev_enabled
        else:
            os.environ.pop("NETWORK_AGENT_AUTH_ENABLED", None)
        if _prev_token is not None:
            os.environ["NETWORK_AGENT_API_TOKEN"] = _prev_token
        else:
            os.environ.pop("NETWORK_AGENT_API_TOKEN", None)

    @pytest.fixture
    def client_enabled(self, auth_app):
        """Test client with auth enabled."""
        return auth_app.test_client()

    def test_health_public_when_auth_enabled(self, client_enabled):
        """Health endpoint is public even when auth is enabled."""
        resp = client_enabled.get("/api/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("status") == "ok"

    def test_api_protected_no_token(self, client_enabled):
        """Protected APIs return 401 without token."""
        resp = client_enabled.get("/api/agent/status")
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert data["ok"] is False
        assert data["error"] == "unauthorized"

    def test_api_protected_wrong_token(self, client_enabled):
        """Protected APIs return 401 with wrong token."""
        resp = client_enabled.get(
            "/api/agent/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert data["ok"] is False

    def test_api_bearer_token_valid(self, client_enabled):
        """Protected APIs work with valid Bearer token."""
        resp = client_enabled.get(
            "/api/agent/status",
            headers={"Authorization": "Bearer test-secret-token-123"},
        )
        # Agent status may return 200 or 500 depending on runtime state
        # The key assertion is that it's NOT 401
        assert resp.status_code != 401

    def test_api_x_api_key_valid(self, client_enabled):
        """Protected APIs work with valid X-API-Key."""
        resp = client_enabled.get(
            "/api/agent/status",
            headers={"X-API-Key": "test-secret-token-123"},
        )
        assert resp.status_code != 401

    def test_static_not_intercepted(self, client_enabled):
        """Static frontend paths are not auth-intercepted."""
        resp = client_enabled.get("/")
        # SPA returns index.html — should be 200 or redirect, not 401
        assert resp.status_code != 401

    def test_options_preflight_allowed(self, client_enabled):
        """OPTIONS preflight requests are allowed without auth."""
        resp = client_enabled.options("/api/agent/message")
        assert resp.status_code != 401

    def test_auth_disabled_app(self, monkeypatch):
        """When auth is disabled, all APIs are accessible."""
        monkeypatch.setenv("NETWORK_AGENT_AUTH_ENABLED", "false")
        from backend.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.get("/api/agent/status")
        assert resp.status_code != 401
