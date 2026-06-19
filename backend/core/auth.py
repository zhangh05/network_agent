# backend/core/auth.py
"""Global API authentication middleware.

Environment variables:
  NETWORK_AGENT_AUTH_ENABLED  — "true" or "false" (default: false)
  NETWORK_AGENT_API_TOKEN     — shared secret for Bearer / X-API-Key auth

Public endpoints (no auth required even when enabled):
  - /api/health, /health
  - Static frontend resources (non-/api/* paths)

Auth methods:
  - Authorization: Bearer <token>
  - X-API-Key: <token>

Returns 401 on auth failure:
  {"ok": false, "error": "unauthorized", "message": "...", "status": 401}
"""

import os
import logging
import hmac
from functools import wraps

import flask

logger = logging.getLogger("network_agent.auth")

def _is_auth_enabled() -> bool:
    """Read NETWORK_AGENT_AUTH_ENABLED from env (re-evaluated each call for testability)."""
    return os.environ.get("NETWORK_AGENT_AUTH_ENABLED", "false").strip().lower() in (
        "true", "1", "yes", "on",
    )


def _get_api_token() -> str:
    """Read NETWORK_AGENT_API_TOKEN from env (re-evaluated each call for testability)."""
    return os.environ.get("NETWORK_AGENT_API_TOKEN", "").strip()


# ── Module-level defaults (used for logging) ──
_AUTH_ENABLED = _is_auth_enabled()
_API_TOKEN = _get_api_token()

# ── Public endpoints (no auth required) ──
_PUBLIC_PREFIXES = frozenset([
    "/api/health",
    "/health",
])

_PUBLIC_EXACT = frozenset([
    "/",
])


def is_public_path(path: str) -> bool:
    """Check if a request path is public (no auth required)."""
    # Exact matches
    if path in _PUBLIC_EXACT:
        return True
    # Prefix matches
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path == prefix:
            return True
    # Non-API paths (static frontend resources)
    if not path.startswith("/api/"):
        return True
    return False


def _unauthorized_response(message: str = "Missing or invalid API token") -> flask.Response:
    """Return a standardized 401 response."""
    return flask.jsonify({
        "ok": False,
        "error": "unauthorized",
        "message": message,
        "status": 401,
    }), 401


def _extract_token_from_request() -> str | None:
    """Extract bearer or API-key token from request headers.

    Does NOT log the token value.
    """
    # Authorization: Bearer <token>
    auth_header = flask.request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    # X-API-Key: <token>
    api_key = flask.request.headers.get("X-API-Key", "").strip()
    if api_key:
        return api_key

    return None


def register_auth_middleware(app: flask.Flask) -> None:
    """Register before_request auth middleware on a Flask app.

    Call after all routes are defined but before first request.
    """
    if not _AUTH_ENABLED:
        logger.info("API authentication disabled (NETWORK_AGENT_AUTH_ENABLED=false)")
        return

    if not _API_TOKEN:
        logger.warning(
            "NETWORK_AGENT_AUTH_ENABLED=true but NETWORK_AGENT_API_TOKEN is empty! "
            "All protected endpoints will reject requests."
        )

    logger.info(
        "API authentication enabled — %d public prefixes, %d public exact paths",
        len(_PUBLIC_PREFIXES), len(_PUBLIC_EXACT),
    )

    @app.before_request
    def _auth_before_request():
        # Re-evaluate env vars each request (for test monkeypatching)
        if not _is_auth_enabled():
            return None

        # OPTIONS preflight — always allow
        if flask.request.method == "OPTIONS":
            return None

        path = flask.request.path

        # Public endpoints — no auth
        if is_public_path(path):
            return None

        # Protected endpoints — require token
        token = _extract_token_from_request()
        api_token = _get_api_token()

        if not api_token:
            logger.error("auth_denied: NETWORK_AGENT_API_TOKEN is empty but auth is enabled")
            return _unauthorized_response("Server authentication misconfigured — no API token set")

        if not token:
            logger.warning("auth_denied: path=%s reason=no_token", path)
            return _unauthorized_response("Missing API token — provide Authorization: Bearer <token> or X-API-Key: <token>")

        # Constant-time comparison: prevents timing-based token leakage.
        if not hmac.compare_digest(str(token), str(api_token)):
            logger.warning("auth_denied: path=%s reason=invalid_token", path)
            return _unauthorized_response("Invalid API token")

        # Token valid — proceed
        return None

    # Register teardown to clean up any auth state if needed
    @app.teardown_request
    def _auth_teardown(exc=None):
        pass  # No persistent auth state to clean up
