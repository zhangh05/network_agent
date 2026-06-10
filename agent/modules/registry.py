# agent/modules/registry.py
"""ModuleRegistry — manages enabled/planned modules."""

from dataclasses import dataclass, field


@dataclass
class ModuleSpec:
    module_id: str = ""
    name: str = ""
    status: str = "disabled"  # enabled | disabled | planned
    service_path: str = ""
    skill_id: str = ""
    related_tools: list = field(default_factory=list)
    description: str = ""


# Default module definitions
MODULE_CONFIG_TRANSLATION = ModuleSpec(
    module_id="config_translation",
    name="Config Translation",
    status="enabled",
    skill_id="config_translation",
    related_tools=["parser.parse_config_text", "parser.extract_interfaces"],
    description="Translate network configuration between vendors",
)

MODULE_KNOWLEDGE = ModuleSpec(
    module_id="knowledge",
    name="Knowledge / RAG",
    status="enabled",
    skill_id="knowledge_query",
    related_tools=["knowledge.search"],
    description="Query network documentation",
)

MODULE_TOPOLOGY = ModuleSpec(
    module_id="topology",
    name="Topology",
    status="planned",
    related_tools=[],
    description="Network topology analysis",
)

MODULE_INSPECTION = ModuleSpec(
    module_id="inspection",
    name="Inspection",
    status="planned",
    related_tools=[],
    description="Network device inspection",
)

MODULE_CMDB = ModuleSpec(
    module_id="cmdb",
    name="CMDB",
    status="planned",
    related_tools=[],
    description="Configuration management database",
)


class ModuleRegistry:
    def __init__(self):
        self._modules: dict = {}
        self._register_defaults()

    def _register_defaults(self):
        defaults = [MODULE_CONFIG_TRANSLATION, MODULE_KNOWLEDGE, MODULE_TOPOLOGY, MODULE_INSPECTION, MODULE_CMDB]
        for m in defaults:
            self._modules[m.module_id] = m

    def list_enabled_modules(self) -> list:
        return [m for m in self._modules.values() if m.status == "enabled"]

    def list_planned_modules(self) -> list:
        return [m for m in self._modules.values() if m.status == "planned"]

    def get_module(self, module_id: str) -> ModuleSpec:
        return self._modules.get(module_id)

    def snapshot(self) -> dict:
        return {
            "enabled": [{"module_id": m.module_id, "name": m.name, "description": m.description, "related_tools": m.related_tools}
                        for m in self.list_enabled_modules()],
            "planned": [{"module_id": m.module_id, "name": m.name, "description": m.description}
                        for m in self.list_planned_modules()],
        }
