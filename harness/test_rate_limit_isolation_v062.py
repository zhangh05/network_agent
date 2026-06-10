"""Rate Limit Test Isolation v0.6.2.

Verifies that:
1. RATE_LIMIT_DISABLED env var does not leak between tests
2. Rate limiter global state is properly cleared
3. Per-IP rate limit buckets are independent
"""

import os
import pytest


@pytest.fixture(autouse=True)
def _clean_rate_limit_env(monkeypatch):
    """Ensure no RATE_LIMIT_DISABLED in env before each test."""
    monkeypatch.delenv("RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY", raising=False)


class TestRateLimitEnvIsolation:
    """RATE_LIMIT_DISABLED must not leak between tests."""

    def test_rate_limit_disabled_env_does_not_leak(self, monkeypatch):
        """Setting RATE_LIMIT_DISABLED in one test must not affect next."""
        # Test A: set the env
        monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
        assert os.environ.get("RATE_LIMIT_DISABLED") == "1"

    def test_rate_limit_env_cleaned_after_previous_test(self):
        """After previous test, RATE_LIMIT_DISABLED must be absent."""
        assert "RATE_LIMIT_DISABLED" not in os.environ, \
            "RATE_LIMIT_DISABLED leaked from previous test"


class TestRateLimiterGlobalState:
    """Global _limiters dict must be clearable between tests."""

    def test_rate_limiter_global_state_clearable(self):
        """Create limiter state, clear it, assert empty."""
        from backend.core.rate_limit import (
            _limiters, _limiters_lock, clear_rate_limit_state_for_tests
        )
        # Add some state
        with _limiters_lock:
            _limiters["test_key"] = (None, 0)
        assert len(_limiters) > 0

        # Clear
        clear_rate_limit_state_for_tests()
        assert len(_limiters) == 0

    def test_rate_limiter_starts_clean(self):
        """Before any setup, _limiters should be empty from fixture cleanup."""
        from backend.core.rate_limit import _limiters
        assert len(_limiters) == 0, \
            f"_limiters not empty before test: {len(_limiters)} entries"


class TestPerIPIndependent:
    """Per-IP rate limit buckets must be independent."""

    @pytest.fixture
    def rate_app(self):
        from flask import Flask
        from backend.core.rate_limit import rate_limit_middleware

        app = Flask(__name__)
        app.config["TESTING"] = False
        rate_limit_middleware(app)

        @app.route("/api/agent/run", methods=["POST"])
        def api_agent_run():
            return {"ok": True}

        return app

    def test_different_ip_buckets_independent(self, rate_app, monkeypatch):
        """Filling one IP bucket must not affect another."""
        monkeypatch.delenv("RATE_LIMIT_DISABLED", raising=False)
        from backend.core.rate_limit import clear_rate_limit_state_for_tests
        clear_rate_limit_state_for_tests()

        client = rate_app.test_client()

        # IP1: fill to limit (10 requests)
        for i in range(10):
            resp = client.post(
                "/api/agent/run",
                json={"message": f"ip1_{i}"},
                environ_base={"REMOTE_ADDR": "10.0.0.1"},
            )
            assert resp.status_code == 200, f"IP1 request {i} should succeed"

        # IP1: 11th should fail
        resp = client.post(
            "/api/agent/run",
            json={"message": "ip1_11"},
            environ_base={"REMOTE_ADDR": "10.0.0.1"},
        )
        assert resp.status_code == 429, "IP1 11th request should be rate limited"

        # IP2: should still be able to send requests (different bucket)
        for i in range(10):
            resp = client.post(
                "/api/agent/run",
                json={"message": f"ip2_{i}"},
                environ_base={"REMOTE_ADDR": "10.0.0.2"},
            )
            assert resp.status_code == 200, f"IP2 request {i} should succeed (independent bucket)"

    def test_same_ip_limit_enforced_after_cleanup(self, rate_app, monkeypatch):
        """After cleanup, same IP still gets rate limited at threshold."""
        monkeypatch.delenv("RATE_LIMIT_DISABLED", raising=False)
        from backend.core.rate_limit import clear_rate_limit_state_for_tests
        clear_rate_limit_state_for_tests()

        client = rate_app.test_client()
        ip = "172.16.0.1"

        # 10 requests should succeed
        for i in range(10):
            resp = client.post(
                "/api/agent/run",
                json={"message": f"req_{i}"},
                environ_base={"REMOTE_ADDR": ip},
            )
            assert resp.status_code == 200

        # 11th should fail
        resp = client.post(
            "/api/agent/run",
            json={"message": "overflow"},
            environ_base={"REMOTE_ADDR": ip},
        )
        assert resp.status_code == 429
