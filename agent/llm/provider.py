# agent/llm/provider.py
"""LLM provider — uses unified effective config (UI settings priority)."""

import json, os, urllib.request, urllib.error
from typing import Optional
from agent.llm.schemas import LLMRequest, LLMResponse, LLMToolCall
from agent.llm.key_resolver import mask_secret


def get_provider_config() -> dict:
    """Get provider config via unified path (UI settings > env/file > default)."""
    from agent.llm.config import resolve_provider_config
    return resolve_provider_config()


def generate(req: LLMRequest) -> LLMResponse:
    """Generate LLM response using unified effective config."""
    cfg = get_provider_config()
    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        return LLMResponse(error="LLM disabled")
    if cfg.get("provider_type") == "mock":
        return _mock_generate(req, cfg)
    return _api_generate(req, cfg)


def health(cfg: dict = None) -> dict:
    """Check provider health without leaking keys."""
    if cfg is None:
        cfg = get_provider_config()
    provider_type = cfg.get("provider_type", "disabled")
    has_key = bool(cfg.get("api_key"))
    result = {
        "configured": has_key or provider_type == "mock",
        "provider": cfg.get("provider", cfg.get("default_provider", "disabled")),
        "connected": False,
        "model": cfg.get("model", ""),
        "last_error": None,
    }
    if not result["configured"] or provider_type == "disabled":
        return result
    if provider_type == "mock":
        result["connected"] = True
        return result
    if not has_key:
        result["last_error"] = "no_api_key"
        return result
    try:
        url = cfg["base_url"].rstrip("/") + "/models"
        headers = {"Authorization": "Bearer " + cfg["api_key"]}
        r = urllib.request.Request(url, headers=headers)
        urllib.request.urlopen(r, timeout=10)
        result["connected"] = True
    except Exception as e:
        result["last_error"] = mask_secret(str(e))[:100]
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
        return LLMResponse(error="API key not configured")
    try:
        url = cfg.get("base_url", "https://api.minimax.chat/v1").rstrip("/") + "/chat/completions"
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
        with urllib.request.urlopen(r, timeout=cfg.get("timeout", 30)) as resp:
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
    except Exception as e:
        return LLMResponse(error=_redact_error(str(e)))


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


def _redact_error(msg: str) -> str:
    for kw in ["Authorization", "Bearer", "api_key", "key"]:
        if kw.lower() in msg.lower():
            return "[REDACTED] provider error"
    return msg[:200]
