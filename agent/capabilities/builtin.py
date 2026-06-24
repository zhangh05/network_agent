# agent/capabilities/builtin.py
"""Built-in capability registry — the default set of capabilities.

v3.2 defaults:
- config_translation: handled via CapabilityPackage (capability-first routing)
- knowledge:          enabled
- artifact:           enabled
- review:             enabled
- cmdb:               enabled
- topology:           planned
- inspection:         planned

Adding a new capability = adding a CAPABILITY_* constant to its module
directory and listing it here. The registry remains the truth source.
"""

from functools import lru_cache

from agent.capabilities.registry import CapabilityRegistry
from agent.capabilities.schemas import CapabilityManifest

from agent.modules.knowledge.capability import CAPABILITY_KNOWLEDGE
from agent.modules.artifact.capability import CAPABILITY_ARTIFACT
from agent.modules.review.capability import CAPABILITY_REVIEW
from agent.modules.topology.capability import CAPABILITY_TOPOLOGY
from agent.modules.inspection.capability import CAPABILITY_INSPECTION
from agent.modules.cmdb.capability import CAPABILITY_CMDB
from agent.modules.remote.capability import CAPABILITY_REMOTE
from agent.modules.pcap.capability import CAPABILITY_PCAP
from agent.modules.git.capability import CAPABILITY_CODING
from agent.modules.browser.capability import CAPABILITY_BROWSER


BUILTIN_CAPABILITIES: list[CapabilityManifest] = [
    CAPABILITY_KNOWLEDGE,
    CAPABILITY_ARTIFACT,
    CAPABILITY_REVIEW,
    CAPABILITY_TOPOLOGY,
    CAPABILITY_INSPECTION,
    CAPABILITY_CMDB,
    CAPABILITY_REMOTE,
    CAPABILITY_PCAP,
    CAPABILITY_CODING,
    CAPABILITY_BROWSER,
]


@lru_cache(maxsize=1)
def get_default_capability_registry() -> CapabilityRegistry:
    """Return the process-wide default CapabilityRegistry.

    Cached so every consumer (ModuleRegistry, SkillRegistry,
    ToolRegistry, RuntimeSnapshot) sees the SAME registry instance.
    """
    reg = CapabilityRegistry(BUILTIN_CAPABILITIES)
    # Sanity: assert the expected entries exist.
    # config_translation is now handled via capability-first routing (CapabilityPackage).
    expected = {"knowledge", "artifact_management", "review_flow",
                "topology", "inspection", "cmdb", "network_device",
                "pcap_analysis", "coding", "browser"}
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
