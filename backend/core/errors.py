# backend/core/errors.py
"""Unified API error contract — v2.1.1.

All keep API endpoints must use these helpers for consistent error responses.

Standard error structure:
{
    "ok": false,
    "error": "<error_code>",
    "message": "<human-readable>",
    "status": <HTTP status code>,
    "details": <dict | null>,
    "trace_id": "<trace_id | null>"
}
"""

import traceback
import uuid
from flask import jsonify, request, g


def _get_trace_id() -> str | None:
    """Get current request trace_id if available."""
    return getattr(g, 'trace_id', None)


def _make_error(error_code: str, message: str, status: int,
                details: dict | None = None) -> tuple:
    """Build standardized error response tuple."""
    err = {
        "ok": False,
        "error": error_code,
        "message": message,
        "status": status,
        "details": details or {},
        "trace_id": _get_trace_id(),
    }
    return jsonify(err), status


# ── Standard error helpers ──

def bad_request(message: str = "Invalid request", details: dict | None = None):
    """400 — validation_error."""
    return _make_error("validation_error", message, 400, details)


def unauthorized(message: str = "Authentication required"):
    """401 — unauthorized."""
    return _make_error("unauthorized", message, 401)


def forbidden(message: str = "Permission denied", details: dict | None = None):
    """403 — permission_denied."""
    return _make_error("permission_denied", message, 403, details)


def not_found(resource: str = "Resource"):
    """404 — not_found."""
    return _make_error("not_found", f"{resource} not found", 404)


def server_error(message: str = "Internal server error",
                 details: dict | None = None):
    """500 — server_error."""
    # Never expose tracebacks in production
    return _make_error("server_error", message, 500, details)


def tool_error(message: str, details: dict | None = None):
    """tool_error — tool execution failure."""
    return _make_error("tool_error", message, 500, details)


def provider_error(message: str, details: dict | None = None):
    """provider_error — LLM/external service failure."""
    return _make_error("provider_error", message, 502, details)


def context_error(message: str, details: dict | None = None):
    """context_error — context build/resolve failure."""
    return _make_error("context_error", message, 500, details)


def invalid_workspace():
    """Standard invalid workspace response."""
    return _make_error("invalid_workspace_id", "Invalid workspace_id", 400)


def invalid_session():
    """Standard invalid session response."""
    return _make_error("validation_error", "Invalid session_id", 400)


def invalid_artifact():
    """Standard invalid artifact response."""
    return _make_error("validation_error", "Invalid artifact_id", 400)


def too_large(message: str = "Request payload too large"):
    """413 — content too large."""
    return _make_error("validation_error", message, 413)


def not_implemented(feature: str = "Feature"):
    """501 — not implemented."""
    return _make_error("not_implemented", f"{feature} not yet implemented", 501)
