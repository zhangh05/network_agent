# agent/llm/provider.py
"""LLM provider abstraction — skeleton, not connected to real APIs."""

PROVIDERS = {
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    "minimax": {"base_url": "https://api.minimaxi.com/v1", "default_model": "MiniMax-M3"},
    "ollama": {"base_url": "http://localhost:11434/v1", "default_model": "llama3.1"},
}
