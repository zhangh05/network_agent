# agent/runtime/prompt_architecture/__init__.py
"""Capability-first prompt architecture."""

from agent.runtime.prompt_architecture.models import PromptBlock, PromptAssembly
from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt

__all__ = ["PromptBlock", "PromptAssembly", "compile_runtime_prompt"]
