# agent/capabilities/__init__.py
"""Capability Layer v0.8 — unified CapabilityManifest / CapabilityRegistry.

A Capability is the canonical, truth-source definition of a business
capability: a Module + Tool(s) + Output Contract + Safety
Contract. RuntimeSnapshot / ModuleRegistry / ToolRegistry
all derive from this single source.

Design contract:
- Module: business implementation, structured in/out, may write artifacts,
  does NOT know about LLM / ToolRouter.
- Tool: LLM-callable entry. Defines tool_id / schema / risk / approval /
  callable_by_llm. Lightweight argument validation, dispatches to Module,
  wraps ToolResult.
- Capability: a Capability bundles Module + Tool(s) + intent routing
  (intent_patterns / prompt_summary) + Output Contract + Safety Contract.
"""

from agent.capabilities.schemas import (
    CapabilityStatus,
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)
from agent.capabilities.registry import (
    CapabilityRegistry,
)
from agent.capabilities.builtin import (
    get_default_capability_registry,
    BUILTIN_CAPABILITIES,
)

__all__ = [
    "CapabilityStatus",
    "CapabilityManifest",
    "CapabilityModuleSpec",
    "CapabilityToolRef",
    "CapabilityOutputSpec",
    "CapabilitySafetySpec",
    "CapabilityRegistry",
    "get_default_capability_registry",
]
