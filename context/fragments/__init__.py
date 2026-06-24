# context/fragments/__init__.py
"""Composable context fragments — modular, capped, priority-ordered context injection.

Usage:
    from context.fragments import collect_context

    state = collect_context(state)  # replaces context_loader's 5 ad-hoc blocks

Or manually:
    from context.fragments.registry import FragmentRegistry
    from context.fragments.workspace import WorkspaceStateFragment
    from context.fragments.memory import MemoryHitsFragment
    from context.fragments.registries import ModuleRegistryFragment, SkillRegistryFragment
    from context.fragments.context_bundle import ContextBundleFragment

    registry = FragmentRegistry()
    registry.register(WorkspaceStateFragment())
    registry.register(MemoryHitsFragment())
    registry.register(ModuleRegistryFragment())
    registry.register(SkillRegistryFragment())
    registry.register(ContextBundleFragment())
    collected = registry.collect(state)
"""

from .base import ContextFragment, FragmentPriority
from .registry import FragmentRegistry
from .workspace import WorkspaceStateFragment
from .memory import MemoryHitsFragment
from .registries import ModuleRegistryFragment, SkillRegistryFragment
from .context_bundle import ContextBundleFragment


def get_default_registry() -> FragmentRegistry:
    """Return a pre-configured FragmentRegistry with all standard fragments."""
    registry = FragmentRegistry()
    registry.register(WorkspaceStateFragment())
    registry.register(MemoryHitsFragment())
    registry.register(ModuleRegistryFragment())
    registry.register(SkillRegistryFragment())
    registry.register(ContextBundleFragment())
    return registry


def collect_context(state) -> "NetworkAgentState":
    """Convenience function: collect all standard context fragments.

    Replaces the 5 ad-hoc try/except blocks in agent/nodes/context_loader.py.
    Updates state.context with collected results.

    Returns state (mutated in place).
    """
    registry = get_default_registry()
    collected = registry.collect(state)

    # Inject into state.context
    state.context.setdefault("fragments", {})
    state.context["fragments"] = {
        "results": collected["fragments"],
        "render_order": collected["render_order"],
        "total_tokens_used": collected["total_tokens_used"],
        "failed": collected["failed"],
        "skipped": collected["skipped"],
    }

    # Propagate ContextBundle data (special case — no string render)
    bundle_data = collected["fragments"].get("ContextBundleFragment", {})
    if bundle_data.get("bundle_available"):
        state.context["context_bundle"] = {
            "safe_llm_context": bundle_data.get("safe_llm_context", {}),
            "execution_context": bundle_data.get("execution_context", {}),
            "citations": bundle_data.get("citations", []),
        }
        state.context["safe_llm_context"] = bundle_data.get("safe_llm_context", {})
        state.context["execution_context"] = bundle_data.get("execution_context", {})
        state.context["citations"] = bundle_data.get("citations", [])

    # Propagate flat data
    ws_data = collected["fragments"].get("WorkspaceStateFragment", {})
    if "last_result" in ws_data:
        state.context["last_result"] = ws_data["last_result"]
        state.context["workspace_state"] = ws_data

    mem_data = collected["fragments"].get("MemoryHitsFragment", {})
    if "hits" in mem_data:
        state.context["memory_hits"] = mem_data["hits"]

    mod_data = collected["fragments"].get("module_registry", {})
    if "modules" in mod_data:
        state.context["modules"] = mod_data["modules"]

    cap_data = collected["fragments"].get("capability_registry", {})
    if "capabilities" in cap_data:
        state.context["capabilities"] = cap_data["capabilities"]

    return state


__all__ = [
    "ContextFragment",
    "FragmentPriority",
    "FragmentRegistry",
    "WorkspaceStateFragment",
    "MemoryHitsFragment",
    "ModuleRegistryFragment",
    "SkillRegistryFragment",
    "ContextBundleFragment",
    "get_default_registry",
    "collect_context",
]
