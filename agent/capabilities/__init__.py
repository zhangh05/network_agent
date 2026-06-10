# agent/capabilities/__init__.py
"""Capability Layer v0.8 — unified CapabilityManifest / CapabilityRegistry.

A Capability is the canonical, truth-source definition of a business
capability: a Module + Tool(s) + Skill(s) + Output Contract + Safety
Contract. RuntimeSnapshot / ModuleRegistry / SkillRegistry / ToolRegistry
all derive from this single source.

Design contract:
- Module: business implementation, structured in/out, may write artifacts,
  does NOT know about LLM / Skill / ToolRouter.
- Tool: LLM-callable entry. Defines tool_id / schema / risk / approval /
  callable_by_llm. Lightweight argument validation, dispatches to Module,
  wraps ToolResult.
- Skill: tells the LLM when to use the capability, its pre/post conditions
  and safety rules. Does NOT execute code.
- Capability: a Capability bundles Module + Tool(s) + Skill(s) + Output
  Contract + Safety Contract.
"""

from agent.capabilities.schemas import (
    CapabilityStatus,
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
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
    "CapabilitySkillSpec",
    "CapabilityToolRef",
    "CapabilityOutputSpec",
    "CapabilitySafetySpec",
    "CapabilityRegistry",
    "get_default_capability_registry",
]
