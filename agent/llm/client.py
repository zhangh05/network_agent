# agent/llm/client.py
"""LLM Client — safe external interface for LLM operations."""

from agent.state import NetworkAgentState
from agent.llm.schemas import SafeLLMOutput
from agent.llm.config import resolve_provider_config, get_llm_status


class LLMClient:
    def __init__(self):
        self._cfg = resolve_provider_config()

    def generate(self, task: str, state: NetworkAgentState, user_question: str = None) -> SafeLLMOutput:
        from agent.llm.runtime import safe_generate
        return safe_generate(task, state, user_question)

    def health(self) -> dict:
        from agent.llm.provider import health
        return health(self._cfg)

    def is_connected(self) -> bool:
        return self._cfg.get("enabled", False) and bool(self._cfg.get("api_key") or self._cfg.get("provider_type") == "mock")

    def provider_info(self) -> dict:
        return {
            "provider": self._cfg.get("default_provider"),
            "type": self._cfg.get("provider_type"),
            "model": self._cfg.get("model"),
            "connected": self.is_connected(),
        }

    @staticmethod
    def status() -> dict:
        return get_llm_status()
