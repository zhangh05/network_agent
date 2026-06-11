# agent/modules/registry.py
"""ModuleRegistry — thin view over CapabilityRegistry.

v1.0.3.1: ModuleRegistry is no longer a parallel source of truth.
It MUST be constructed with a CapabilityRegistry and reads everything
through it. There is no default-construct path that loads hardcoded
modules, eliminating the previous risk of "legacy modules override
capability modules" or vice versa.
"""

from __future__ import annotations

from typing import List, Optional

from agent.capabilities.schemas import CapabilityManifest


class ModuleSpec:
    __slots__ = ("module_id", "name", "status", "service_path",
                 "skill_id", "related_tools", "description")

    def __init__(self, *, module_id, name, status, service_path,
                 skill_id, related_tools, description):
        self.module_id = module_id
        self.name = name
        self.status = status
        self.service_path = service_path
        self.skill_id = skill_id
        self.related_tools = related_tools
        self.description = description


class ModuleRegistry:
    """Read-only view of capability modules, projected from CapabilityRegistry."""

    def __init__(self, capability_registry):
        if capability_registry is None:
            raise ValueError(
                "ModuleRegistry requires a CapabilityRegistry; "
                "there is no default. Construct via "
                "ModuleRegistry(get_default_capability_registry()) or "
                "ModuleRegistry.from_capabilities(cap_reg)."
            )
        self._cap_reg = capability_registry

    def list_enabled_modules(self) -> list:
        return [_module_spec_from_capability(c) for c in self._cap_reg.list_enabled()]

    def list_planned_modules(self) -> list:
        return [_module_spec_from_capability(c) for c in self._cap_reg.list_planned()]

    def get_module(self, module_id: str):
        for cap in self._cap_reg.list_all():
            if cap.module.module_id == module_id:
                return _module_spec_from_capability(cap)
        return None

    def snapshot(self) -> dict:
        return {
            "enabled": [
                {"module_id": m.module_id, "name": m.name, "description": m.description,
                 "related_tools": m.related_tools}
                for m in self.list_enabled_modules()
            ],
            "planned": [
                {"module_id": m.module_id, "name": m.name, "description": m.description}
                for m in self.list_planned_modules()
            ],
        }

    @classmethod
    def from_capabilities(cls, capability_registry) -> "ModuleRegistry":
        return cls(capability_registry)

    @property
    def capability_registry(self):
        return self._cap_reg


def _module_spec_from_capability(cap: CapabilityManifest) -> ModuleSpec:
    sk = cap.skills[0] if cap.skills else None
    return ModuleSpec(
        module_id=cap.module.module_id,
        name=cap.name,
        status=cap.module.status,
        service_path=cap.module.service_path,
        skill_id=sk.skill_id if sk else cap.capability_id,
        related_tools=[t.tool_id for t in cap.tools],
        description=cap.module.description or cap.description,
    )
