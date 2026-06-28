"""ModuleRegistry — thin view over the business capability catalog.

v3.9.4: ModuleRegistry no longer depends on a CapabilityRegistry or
CapabilityManifest. It reads the new business capability catalog
(`agent.capabilities.catalog`) directly. The catalog is the single
source of truth for business capabilities; this view projects them
into a ModuleSpec list for the API.
"""

from __future__ import annotations

from typing import List, Optional

from agent.capabilities import catalog as _catalog


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
    """Read-only view of business capabilities, projected from catalog."""

    def __init__(self, *args, **kwargs):
        # Backward-compat shim: accept an old CapabilityRegistry arg
        # but ignore it; the catalog is the new source of truth.
        pass

    def list_enabled_modules(self) -> list:
        return [_module_spec_from_capability(c)
                for c in _catalog.list_enabled()]

    def list_planned_modules(self) -> list:
        return [_module_spec_from_capability(c)
                for c in _catalog.list_planned()]

    def get_module(self, module_id: str):
        for cap in _catalog.list_all():
            if cap["module_ids"] and cap["module_ids"][0] == module_id:
                return _module_spec_from_capability(cap)
        return None

    def snapshot(self) -> dict:
        return {
            "enabled": [
                {"module_id": m.module_id, "name": m.name,
                 "description": m.description, "related_tools": m.related_tools}
                for m in self.list_enabled_modules()
            ],
            "planned": [
                {"module_id": m.module_id, "name": m.name,
                 "description": m.description}
                for m in self.list_planned_modules()
            ],
        }

    @classmethod
    def from_capabilities(cls, capability_registry) -> "ModuleRegistry":
        # v3.9.4: catalog is the source of truth; the registry builds itself
        # from it directly. The capability_registry arg is ignored.
        del capability_registry
        return cls()


def _module_spec_from_capability(cap: dict) -> ModuleSpec:
    module_id = cap["module_ids"][0] if cap["module_ids"] else cap["capability_id"]
    return ModuleSpec(
        module_id=module_id,
        name=cap["display_name"],
        status=cap["status"],
        service_path=f"agent.modules.{module_id}"
        if module_id in {"artifact", "browser", "cmdb", "git",
                          "inspection", "knowledge", "pcap", "remote",
                          "review", "topology", "memory", "workspace",
                          "config_analysis", "runtime"}
        else "",
        skill_id=cap["capability_id"],
        related_tools=list(cap["recommended_tool_ids"]),
        description=cap["description"],
    )


__all__ = ["ModuleSpec", "ModuleRegistry"]
