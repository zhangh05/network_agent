"""Capability-first routing for the business execution layer.

This package defines the boundary between capabilities, modules, and tools:

- Capability package: business scene and tool exposure policy.
- Module service: domain implementation behind tools.
- Tool bundle: small visible tool set for the current turn.
"""

from .models import CapabilityPackage, ModuleServiceManifest, ToolBundle
from .router import CapabilityRouter, route_capabilities
from .toolset import build_active_tool_bundle
from .evaluation import RoutingCase, evaluate_router

__all__ = [
    "CapabilityPackage",
    "ModuleServiceManifest",
    "ToolBundle",
    "CapabilityRouter",
    "route_capabilities",
    "build_active_tool_bundle",
    "RoutingCase",
    "evaluate_router",
]
