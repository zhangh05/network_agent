# agent/llm/provider.py
"""LLM provider — uses unified effective config (UI settings priority).

Error diagnostics: preserves HTTP status, error type, and non-sensitive details.
Only masks real tokens/Authorization/Bearer values.
"""

import json, os, urllib.request, urllib.error
from typing import Optional
from agent.llm.schemas import LLMRequest, LLMResponse, LLMToolCall
from agent.llm.key_resolver import mask_secret


# Error type constants (used in metadata and API responses)
ERROR_TYPE_MISSING_API_KEY = "missing_api_key"
ERROR_TYPE_DISABLED_BY_USER = "disabled_by_user"
ERROR_TYPE_PROVIDER_HTTP_400 = "provider_http_400"
ERROR_TYPE_PROVIDER_HTTP_401 = "provider_http_401"
ERROR_TYPE_PROVIDER_HTTP_403 = "provider_http_403"
ERROR_TYPE_PROVIDER_HTTP_404 = "provider_http_404"
ERROR_TYPE_PROVIDER_HTTP_429 = "provider_http_429"
ERROR_TYPE_PROVIDER_TIMEOUT = "provider_timeout"
ERROR_TYPE_PROVIDER_NETWORK_ERROR = "provider_network_error"
ERROR_TYPE_PROVIDER_SCHEMA_REJECTED = "provider_schema_rejected"
ERROR_TYPE_PROVIDER_UNKNOWN = "provider_unknown_error"


def get_provider_config() -> dict:
    """Get provider config via unified path (UI settings > env/file > default)."""
    from agent.llm.config import resolve_provider_config
    return resolve_provider_config()


def generate(req: LLMRequest) -> LLMResponse:
    """Generate LLM response using unified effective config."""
    cfg = get_provider_config()
    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        return LLMResponse(error="LLM disabled", metadata={"error_type": ERROR_TYPE_DISABLED_BY_USER})
    if cfg.get("provider_type") == "mock":
        return _mock_generate(req, cfg)
    return _api_generate(req, cfg)


def health(cfg: dict = None) -> dict:
    """Check provider health with multi-dimensional checks.
    
    Returns dict with:
    - configured: bool (API key present or mock)
    - key_loaded: bool
    - base_url_reachable: bool (lightweight ping)
    - models_endpoint_ok: bool (/models endpoint)
    - chat_completion_ok: bool (lightweight chat/completions ping)
    - provider: str
    - model: str
    - last_error: str (redacted)
    - last_error_type: str
    - http_status: int or None
    """
    if cfg is None:
        cfg = get_provider_config()
    provider_type = cfg.get("provider_type", "disabled")
    has_key = bool(cfg.get("api_key"))
    result = {
        "configured": has_key or provider_type == "mock",
        "provider": cfg.get("provider", cfg.get("default_provider", "disabled")),
        "connected": False,
        "key_loaded": has_key,
        "base_url_reachable": False,
        "models_endpoint_ok": False,
        "chat_completion_ok": False,
        "chat_completion_endpoint_reachable": False,
        "model": cfg.get("model", ""),
        "last_error": None,
        "last_error_type": None,
        "http_status": None,
    }
    if not result["configured"] or provider_type == "disabled":
        result["last_error"] = "no_api_key"
        result["last_error_type"] = ERROR_TYPE_MISSING_API_KEY
        return result
    if provider_type == "mock":
        result["connected"] = True
        result["base_url_reachable"] = True
        result["models_endpoint_ok"] = True
        result["chat_completion_ok"] = True
        result["chat_completion_endpoint_reachable"] = True
        return result
    if not has_key:
        result["last_error"] = "no_api_key"
        result["last_error_type"] = ERROR_TYPE_MISSING_API_KEY
        return result

    # Check 1: base_url reachable (lightweight HEAD or GET)
    try:
        base = cfg["base_url"].rstrip("/")
        ping_req = urllib.request.Request(base, headers={"Authorization": "Bearer " + cfg["api_key"]})
        ping_req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(ping_req, timeout=10) as resp:
            result["base_url_reachable"] = 200 <= resp.status < 400
    except urllib.error.HTTPError as e:
        # HTTP error still means the server is reachable
        result["base_url_reachable"] = True
        result["last_error"] = _redact_error_detail(str(e))
        result["last_error_type"] = f"provider_http_{e.code}"
        result["http_status"] = e.code
    except Exception:
        pass  # network unreachable

    # Check 2: /models endpoint
    try:
        url = cfg["base_url"].rstrip("/") + "/models"
        headers = {"Authorization": "Bearer " + cfg["api_key"]}
        r = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(r, timeout=15) as resp:
            result["models_endpoint_ok"] = resp.status == 200
    except urllib.error.HTTPError as e:
        result["models_endpoint_ok"] = e.code == 200
        if not result["last_error"]:
            result["last_error"] = _redact_error_detail(str(e))
            result["last_error_type"] = f"provider_http_{e.code}"
            result["http_status"] = e.code
    except Exception as e:
        if not result["last_error"]:
            result["last_error"] = _redact_error_detail(str(e))
            result["last_error_type"] = ERROR_TYPE_PROVIDER_NETWORK_ERROR

    # Check 3: chat/completions ping (lightweight, max_tokens=1)
    try:
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        body_dict = {
            "model": cfg.get("model", ""),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        body = json.dumps(body_dict).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        }
        r = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(r, timeout=15) as resp:
            result["chat_completion_ok"] = 200 <= resp.status < 400
            result["chat_completion_endpoint_reachable"] = True
            result["connected"] = result["chat_completion_ok"]
            if result["chat_completion_ok"]:
                result["http_status"] = resp.status
                result["last_error"] = None
                result["last_error_type"] = None
    except urllib.error.HTTPError as e:
        # HTTP error means endpoint responded but with error
        result["chat_completion_endpoint_reachable"] = True
        if 200 <= e.code < 300:
            result["chat_completion_ok"] = True
            result["connected"] = True
        else:
            # HTTP 400/401/403/429 etc — endpoint reachable but request/token invalid
            result["chat_completion_ok"] = False
            result["connected"] = False
        if not result["last_error"]:
            result["last_error"] = _redact_error_detail(str(e))
            result["last_error_type"] = f"provider_http_{e.code}"
            result["http_status"] = e.code
    except Exception as e:
        if not result["last_error"]:
            result["last_error"] = _redact_error_detail(str(e))
            result["last_error_type"] = ERROR_TYPE_PROVIDER_NETWORK_ERROR

    return result


def _mock_generate(req: LLMRequest, cfg: dict) -> LLMResponse:
    ctx = req.safe_context or {}
    if ctx.get("_mock_response_type") == "unsafe":
        return LLMResponse(
            content="I updated the deployable_config. You can 可直接下发 now.",
            provider="mock", model="mock-unsafe",
        )
    return LLMResponse(
        content=f"Translation completed. {ctx.get('deployable_line_count', 0)} lines. "
                f"{ctx.get('manual_review_count', 0)} items need review.",
        provider="mock", model=cfg.get("model", "mock-safe"),
    )


def _api_generate(req: LLMRequest, cfg: dict) -> LLMResponse:
    if not cfg.get("api_key"):
        return LLMResponse(
            error="API key not configured",
            metadata={"error_type": ERROR_TYPE_MISSING_API_KEY},
        )
    try:
        url = cfg.get("base_url", "https://api.minimaxi.com/v1").rstrip("/") + "/chat/completions"
        body_dict = {
            "model": cfg.get("model", req.model),
            "messages": [_format_message(m) for m in req.messages],
            "temperature": cfg.get("temperature", req.temperature),
            "max_tokens": cfg.get("max_tokens", req.max_tokens),
        }
        if req.tools:
            body_dict["tools"] = req.tools
            body_dict["tool_choice"] = "auto"
        body = json.dumps(body_dict).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        }
        r = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(r, timeout=cfg.get("timeout", 90)) as resp:
            d = json.loads(resp.read().decode())
        choice = d.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "") or ""
        tool_calls = _parse_tool_calls(message.get("tool_calls", []))
        return LLMResponse(
            content=content,
            provider=cfg.get("provider", cfg.get("default_provider", "")),
            model=d.get("model", ""),
            usage=d.get("usage"),
            finish_reason=choice.get("finish_reason", ""),
            raw=d,
            tool_calls=tool_calls,
        )
    except urllib.error.HTTPError as e:
        # Extract HTTP status and error detail
        http_status = e.code
        error_detail = _read_error_body(e)
        error_type = f"provider_http_{http_status}"
        redacted = _redact_error_detail(error_detail)
        return LLMResponse(
            error=f"{error_type}: {redacted}",
            metadata={
                "error_type": error_type,
                "http_status": http_status,
                "error_detail": redacted[:200],
            },
        )
    except urllib.error.URLError as e:
        # Network error — classify timeout vs other network errors
        reason = str(e.reason) if hasattr(e, 'reason') else str(e)
        is_timeout = 'timeout' in reason.lower() or 'timed out' in reason.lower()
        error_type = ERROR_TYPE_PROVIDER_TIMEOUT if is_timeout else ERROR_TYPE_PROVIDER_NETWORK_ERROR
        redacted = _redact_error_detail(str(e))
        meta = {
            "error_type": error_type,
            "http_status": None,
            "error_detail": redacted[:200],
        }
        if is_timeout:
            meta["retryable"] = True
            meta["timeout_seconds"] = cfg.get("timeout", 90)
        return LLMResponse(
            error=f"{error_type}: {redacted}",
            metadata=meta,
        )
    except TimeoutError:
        error_type = ERROR_TYPE_PROVIDER_TIMEOUT
        timeout_s = cfg.get('timeout', 90)
        return LLMResponse(
            error=f"{error_type}: Request timed out after {timeout_s} seconds",
            metadata={
                "error_type": error_type,
                "http_status": None,
                "error_detail": f"timeout after {timeout_s}s",
                "retryable": True,
                "timeout_seconds": timeout_s,
            },
        )
    except json.JSONDecodeError as e:
        error_type = ERROR_TYPE_PROVIDER_SCHEMA_REJECTED
        return LLMResponse(
            error=f"{error_type}: Invalid JSON response from provider",
            metadata={
                "error_type": error_type,
                "http_status": None,
                "error_detail": str(e)[:200],
            },
        )
    except Exception as e:
        error_type = ERROR_TYPE_PROVIDER_UNKNOWN
        redacted = _redact_error_detail(str(e))
        return LLMResponse(
            error=f"{error_type}: {redacted}",
            metadata={
                "error_type": error_type,
                "http_status": None,
                "error_detail": redacted[:200],
            },
        )


def _read_error_body(http_error: urllib.error.HTTPError) -> str:
    """Read error response body (for HTTPError with response body)."""
    try:
        body = http_error.read().decode("utf-8", errors="replace")
        d = json.loads(body)
        # OpenAI-compatible error format: {"error": {"message": "...", "type": "...", "code": ...}}
        err = d.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", "")
            if msg:
                return msg
        # Fallback: return raw body (truncated)
        return body[:500]
    except Exception:
        return str(http_error)


def _redact_error_detail(msg: str) -> str:
    """Redact sensitive data (tokens, Authorization) from error messages.

    Preserves non-sensitive error details (HTTP status, error type, etc.)
    Only masks: Authorization header values, Bearer tokens, API keys.
    """
    if not msg:
        return msg
    import re
    # Mask "Bearer <token>" → Bearer [REDACTED]
    msg = re.sub(r'Bearer\s+\S+', 'Bearer [REDACTED]', msg)
    # Mask "Authorization: <value>" → Authorization: [REDACTED]
    msg = re.sub(r'Authorization:\s*\S+', 'Authorization: [REDACTED]', msg)
    # Mask api_key/apikey/token assignments: api_key=VALUE → api_key=[REDACTED]
    msg = re.sub(
        r'(["\']?(?:api_key|apikey|token)["\']?\s*[:=]\s*["\']?)\S+(["\']?)',
        r'\1[REDACTED]\2',
        msg,
        flags=re.IGNORECASE,
    )
    # Mask "API key <value>" / "api key <value>" pattern (no = or :)
    msg = re.sub(
        r'(?i)(api\s+key\s+)\S+',
        r'\1[REDACTED]',
        msg,
    )
    return msg


def _format_message(m) -> dict:
    msg = {"role": m.role, "content": m.content}
    if m.tool_call_id:
        msg["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        msg["tool_calls"] = m.tool_calls
    return msg


def _parse_tool_calls(raw: list) -> list:
    """Parse OpenAI-format tool_calls into LLMToolCall objects."""
    result = []
    for tc in raw:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            args = {}
        result.append(LLMToolCall(
            id=tc.get("id", ""),
            name=fn.get("name", ""),
            arguments=args,
        ))
    return result
