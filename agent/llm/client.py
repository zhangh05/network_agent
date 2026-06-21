# agent/llm/client.py
"""LLM Client — safe external interface, uses unified effective config."""

from agent.state import NetworkAgentState
from agent.llm.schemas import SafeLLMOutput
from agent.llm.config import resolve_provider_config, get_llm_status


class LLMClient:
    def __init__(self, overrides: dict = None):
        cfg = resolve_provider_config()
        if overrides:
            cfg = {**cfg}
            for k in ("base_url", "model", "api_key", "provider"):
                if overrides.get(k):
                    cfg[k] = overrides[k]
        self._cfg = cfg

    def generate(self, task: str, state: NetworkAgentState, user_question: str = None) -> SafeLLMOutput:
        from agent.llm.runtime import safe_generate
        return safe_generate(
            task,
            state,
            user_input=user_question or "",
            config_override=self._cfg,
        )

    def health(self) -> dict:
        from agent.llm.provider import health
        return health(self._cfg)

    def is_connected(self) -> bool:
        return self._cfg.get("enabled", False) and bool(
            self._cfg.get("api_key") or self._cfg.get("provider_type") == "mock"
        )

    def provider_info(self) -> dict:
        return {
            "provider": self._cfg.get("provider", self._cfg.get("default_provider")),
            "type": self._cfg.get("provider_type"),
            "model": self._cfg.get("model"),
            "config_source": self._cfg.get("config_source", "default"),
            "connected": self.is_connected(),
        }

    @staticmethod
    def status() -> dict:
        return get_llm_status()
