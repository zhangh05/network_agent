# agent/llm/client.py
"""LLM client — skeleton placeholder. Not connected to real APIs."""

class LLMClient:
    """Skeleton LLM client. To be implemented when agent LLM layer is activated."""
    def __init__(self, provider="openai", api_key=None, base_url=None, model=None):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def chat(self, messages, **kwargs):
        raise NotImplementedError("LLM client is a skeleton — not connected to real APIs.")

    def is_connected(self):
        return False
