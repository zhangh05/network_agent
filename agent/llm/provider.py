# agent/llm/provider.py
"""LLM provider abstraction — disabled, mock, openai_compatible, ollama_compatible."""

import json
import os
from dataclasses import dataclass
from typing import Optional

from agent.llm.schemas import LLMRequest, LLMResponse, LLMMessage


@dataclass
class ProviderConfig:
    type: str = "disabled"  # disabled, mock, openai_compatible, ollama_compatible
    base_url: str = ""
    api_key: str = ""
    model: str = ""


def load_config() -> dict:
    """Load LLM config from config/llm.yaml or environment."""
    try:
        import yaml
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(root, "config", "llm.yaml")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f).get("llm", {})
    except Exception:
        pass
    return {}


def get_provider_config() -> dict:
    """Return active provider configuration."""
    cfg = load_config()
    enabled = cfg.get("enabled", False)
    default = cfg.get("default_provider", "disabled")
    providers = cfg.get("providers", {})

    if not enabled or default == "disabled":
        return {"enabled": False, "type": "disabled", "model": ""}

    provider_cfg = providers.get(default, {})
    api_key_env = provider_cfg.get("api_key_env", "")
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""

    return {
        "enabled": True,
        "type": provider_cfg.get("type", "disabled"),
        "base_url": provider_cfg.get("base_url", ""),
        "api_key": api_key,
        "model": provider_cfg.get("model", ""),
    }


def generate(req: LLMRequest) -> LLMResponse:
    """Dispatch to the appropriate provider based on config."""
    cfg = get_provider_config()

    if not cfg["enabled"] or cfg["type"] == "disabled":
        return LLMResponse(error="LLM disabled")

    if cfg["type"] == "mock":
        return _mock_generate(req, cfg)

    if cfg["type"] in ("openai_compatible", "ollama_compatible"):
        return _api_generate(req, cfg)

    return LLMResponse(error=f"unknown provider type: {cfg['type']}")


def _mock_generate(req: LLMRequest, cfg: dict) -> LLMResponse:
    """Mock provider for testing — returns safe, deterministic responses."""
    task = req.task
    ctx = req.safe_context or {}
    resp_type = ctx.get("_mock_response_type", "safe")

    if resp_type == "unsafe":
        return LLMResponse(
            content="I have updated the deployable_config for you. You can directly deploy now.",
            provider="mock",
            model="mock-unsafe",
        )

    lines = ctx.get("deployable_line_count", 0)
    mr = ctx.get("manual_review_count", 0)
    us = ctx.get("unsupported_count", 0)

    if task == "response_compose":
        content = (
            f"Configuration translation completed. "
            f"{lines} lines generated. "
            f"{mr} items need manual review, {us} unsupported. "
            f"Please verify before deployment."
        )
    elif task == "manual_review_explain":
        content = f"The following {mr} items require manual review. Each item should be evaluated against the target environment."
    elif task == "result_summarize":
        content = f"Translation summary: {lines} deployable lines, {mr} to review, {us} unsupported."
    else:
        content = f"Context QA response for intent: {ctx.get('intent', 'unknown')}"

    return LLMResponse(content=content, provider="mock", model="mock-safe-composer")


def _api_generate(req: LLMRequest, cfg: dict) -> LLMResponse:
    """Call OpenAI-compatible API."""
    if not cfg.get("api_key"):
        return LLMResponse(error="API key not configured")

    try:
        import urllib.request
        url = (cfg["base_url"] or "https://api.openai.com/v1") + "/chat/completions"
        body = json.dumps({
            "model": cfg.get("model", req.model),
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }).encode("utf-8")

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"}
        r = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(r, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            return LLMResponse(
                content=choice.get("message", {}).get("content", ""),
                provider=cfg["type"],
                model=data.get("model", ""),
                usage=data.get("usage"),
                raw=data,
            )
    except Exception as e:
        return LLMResponse(error=str(e))
