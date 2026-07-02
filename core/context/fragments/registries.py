# context/fragments/registries.py
"""Module and capability registry fragments — available capabilities context."""

import json
import logging
import os

from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ModuleRegistryFragment(ContextFragment):
    """Loads module availability from modules/registry.json."""

    priority = FragmentPriority.REGISTRY
    token_budget = 1024
    fragment_id = "module_registry"

    def build(self, state) -> dict:
        try:
            with open(os.path.join(ROOT, "modules", "registry.json"), encoding="utf-8") as f:
                modules = json.load(f)
            return {
                "ok": True,
                "modules": {
                    m["module_name"]: m["status"]
                    for m in modules.get("modules", [])
                },
            }
        except Exception:
            logger.debug("ModuleRegistryFragment: load failed", exc_info=True)
            return {"ok": True, "modules": {}}

    def render(self, data: dict) -> str:
        mods = data.get("modules", {})
        if not mods:
            return ""
        enabled = [k for k, v in mods.items() if v == "enabled"]
        return self.cap(f"[modules] enabled={', '.join(enabled[:10])}")


class SkillRegistryFragment(ContextFragment):
    """v3.2: Capability registry from CAPABILITY_PACKAGES (was skills/registry.json)."""

    priority = FragmentPriority.REGISTRY
    token_budget = 1024
    fragment_id = "capability_registry"

    def build(self, state) -> dict:
        try:
            return {
                "ok": True,
                "capabilities": {
                    # v3.9.3: skill_packages inlined elsewhere; fragment is empty.
                    {}
                },
            }
        except Exception:
            logger.debug("SkillRegistryFragment: load failed", exc_info=True)
            return {"ok": True, "capabilities": {}}

    def render(self, data: dict) -> str:
        caps = data.get("capabilities", {})
        if not caps:
            return ""
        names = list(caps.values())[:10]
        return self.cap(f"[capabilities] {', '.join(names)}")
