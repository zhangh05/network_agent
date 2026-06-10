# backend/core/rate_limit.py
"""Simple in-memory rate limiter for Flask — no external dependencies.

Uses a sliding window counter per client IP + endpoint.
Thread-safe via threading.Lock.

Default limits:
  - /api/agent/run: 10 req/min
  - /api/agent/llm/test: 5 req/min
  - /api/tools/invoke: 30 req/min
  - All other /api/*: 60 req/min
"""

import os
import time
import threading
from collections import defaultdict
from flask import request, jsonify


# ─── Configuration ───

# endpoint_prefix → (max_requests, window_seconds)
RATE_LIMITS = {
    "/api/agent/run": (10, 60),
    "/api/agent/llm/test": (5, 60),
    "/api/tools/invoke": (30, 60),
}

# Default limit for any unmatched /api/* endpoint
DEFAULT_LIMIT = (60, 60)


# ─── Sliding window counter ───

class _WindowCounter:
    """Thread-safe sliding window counter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets = defaultdict(int)   # timestamp_bucket → count
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Check if request is allowed. Returns True if under limit."""
        now = time.time()
        bucket = int(now)
        cutoff = bucket - self.window_seconds

        with self._lock:
            # Prune old buckets
            old_keys = [k for k in self._buckets if k < cutoff]
            for k in old_keys:
                del self._buckets[k]

            # Count requests in window
            total = sum(v for k, v in self._buckets.items() if k >= cutoff)
            if total >= self.max_requests:
                return False

            self._buckets[bucket] += 1
            return True


# ─── Per-IP, per-endpoint limiters ───

_limiters: dict[str, tuple] = {}  # key → (_WindowCounter, last_access_time)
_limiters_lock = threading.Lock()
_LIMITER_TTL = 3600  # Evict limiters idle > 1 hour


def _get_limiter(endpoint: str, client_ip: str) -> _WindowCounter:
    """Get or create a rate limiter for a client IP + endpoint combination.

    Args:
        endpoint: The API endpoint path (e.g., "/api/agent/run")
        client_ip: The client's IP address (from _get_client_ip())

    Returns:
        A _WindowCounter instance for this client IP + endpoint
    """
    # Find matching limit config (longest prefix match)
    matched = DEFAULT_LIMIT
    matched_len = 0
    for prefix, limit in RATE_LIMITS.items():
        if endpoint.startswith(prefix) and len(prefix) > matched_len:
            matched = limit
            matched_len = len(prefix)

    max_req, window = matched
    # Key includes client_ip to ensure per-IP rate limiting
    key = f"{client_ip}:{endpoint}:{max_req}:{window}"
    now = time.time()

    with _limiters_lock:
        # Periodic eviction of stale limiters (every ~1000 calls)
        if len(_limiters) > 100:
            stale = [k for k, (_, t) in _limiters.items() if now - t > _LIMITER_TTL]
            for k in stale:
                del _limiters[k]

        if key not in _limiters:
            _limiters[key] = (_WindowCounter(max_req, window), now)
        else:
            counter, _ = _limiters[key]
            _limiters[key] = (counter, now)  # update access time
        return _limiters[key][0]


def _get_client_ip() -> str:
    """Extract client IP from request.

    Only trusts X-Forwarded-For when the app is explicitly configured
    behind a trusted reverse proxy (TRUSTED_PROXY=true env).
    Otherwise defaults to request.remote_addr to prevent IP spoofing.
    """
    if os.environ.get("TRUSTED_PROXY", "").lower() in ("1", "true", "yes"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def rate_limit_middleware(app):
    """Register rate limiting before_request hook on a Flask app.

    Only applies to /api/* endpoints. Non-API routes are not limited.
    Disabled when RATE_LIMIT_DISABLED env var is set or when Flask testing mode is on.
    """
    @app.before_request
    def _check_rate_limit():
        # Skip rate limiting in test mode or when explicitly disabled
        if app.config.get("TESTING"):
            return None
        if os.environ.get("RATE_LIMIT_DISABLED"):
            return None
        # Only limit API endpoints
        if not request.path.startswith("/api/"):
            return None

        client_ip = _get_client_ip()
        limiter = _get_limiter(request.path, client_ip)

        if not limiter.allow():
            return jsonify({
                "ok": False,
                "error": "rate_limit_exceeded",
                "detail": f"Rate limit exceeded for {request.path}. Try again later.",
                "retry_after_seconds": limiter.window_seconds,
            }), 429
