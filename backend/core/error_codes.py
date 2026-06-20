# backend/core/error_codes.py
"""Minimal unified backend error codes and response helpers."""

from __future__ import annotations

from typing import Any

# ── Error codes ──

WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
INVALID_WORKSPACE_ID = "INVALID_WORKSPACE_ID"
FILE_NOT_FOUND = "FILE_NOT_FOUND"
FILE_NOT_ACCESSIBLE = "FILE_NOT_ACCESSIBLE"
ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
PCAP_SESSION_NOT_FOUND = "PCAP_SESSION_NOT_FOUND"
REFERENCE_NOT_FOUND = "REFERENCE_NOT_FOUND"
TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
RISK_APPROVAL_REQUIRED = "RISK_APPROVAL_REQUIRED"
INTERNAL_ERROR = "INTERNAL_ERROR"


def api_ok(data: Any = None, summary: str = "") -> dict[str, Any]:
    """Build a success envelope."""
    return {
        "ok": True,
        "status": "ok",
        "summary": summary,
        "data": data,
        "errors": [],
    }


def api_error(error_code: str, summary: str = "", status_code: int = 400,
              details: list[str] | None = None) -> tuple[dict[str, Any], int]:
    """Build an error envelope and HTTP status code."""
    return (
        {
            "ok": False,
            "status": "failed",
            "summary": summary,
            "error_code": error_code,
            "errors": details or [summary],
        },
        status_code,
    )
