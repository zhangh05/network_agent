# agent/capabilities/builtin.py
"""Built-in capability registry — the default set of capabilities.

v0.8 defaults:
- config_translation: enabled
- knowledge:          enabled
- topology:           planned
- inspection:         planned
- cmdb:               planned

Adding a new capability = adding a CAPABILITY_* constant to its module
directory and listing it here. The registry remains the truth source.
"""

from functools import lru_cache

from agent.capabilities.registry import CapabilityRegistry
from agent.capabilities.schemas import CapabilityManifest

from agent.modules.config_translation.capability import CAPABILITY_CONFIG_TRANSLATION
from agent.modules.knowledge.capability import CAPABILITY_KNOWLEDGE
from agent.modules.topology.capability import CAPABILITY_TOPOLOGY
from agent.modules.inspection.capability import CAPABILITY_INSPECTION
from agent.modules.cmdb.capability import CAPABILITY_CMDB


BUILTIN_CAPABILITIES: list[CapabilityManifest] = [
    CAPABILITY_CONFIG_TRANSLATION,
    CAPABILITY_KNOWLEDGE,
    CAPABILITY_TOPOLOGY,
    CAPABILITY_INSPECTION,
    CAPABILITY_CMDB,
]


@lru_cache(maxsize=1)
def get_default_capability_registry() -> CapabilityRegistry:
    """Return the process-wide default CapabilityRegistry.

    Cached so every consumer (ModuleRegistry, SkillRegistry,
    ToolRegistry, RuntimeSnapshot) sees the SAME registry instance.
    """
    reg = CapabilityRegistry(BUILTIN_CAPABILITIES)
    # Sanity: assert the five v0.8 expected entries exist.
    expected = {"config_translation", "knowledge", "topology", "inspection", "cmdb"}
    ids = {m.capability_id for m in reg.list_all()}
    missing = expected - ids
    if missing:
        raise RuntimeError(
            f"Default CapabilityRegistry missing expected capabilities: {sorted(missing)}"
        )
    return reg


def reset_default_capability_registry_cache() -> None:
    """For tests: clear the lru_cache so a fresh registry is built."""
    get_default_capability_registry.cache_clear()
