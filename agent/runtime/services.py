# agent/runtime/services.py
"""RuntimeServices — dependency injection container for all runtime capabilities."""

from dataclasses import dataclass, field


@dataclass
class RuntimeServices:
    model_service: object = None      # LLM Runtime
    tool_service: object = None       # ToolRouter/Registry
    skill_service: object = None      # SkillRegistry
    module_service: object = None     # ModuleRegistry
    artifact_service: object = None   # ArtifactStore
    knowledge_service: object = None  # Knowledge/RAG
    workspace_service: object = None  # Workspace state
    audit_service: object = None      # EventRecorder + TraceRecorder
    # v0.8: CapabilityRegistry is the truth-source for capabilities.
    # None means "fall back to legacy default registries".
    capability_registry: object = None  # CapabilityRegistry | None


def default_runtime_services() -> RuntimeServices:
    """Create default RuntimeServices with all subsystems wired."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.skills.registry import SkillRegistry
    from agent.modules.registry import ModuleRegistry
    from agent.audit.events import EventRecorder
    from agent.audit.trace import TraceRecorder
    from agent.audit.rollout import RolloutRecorder
    from agent.capabilities import get_default_capability_registry

    # CapabilityRegistry is the single source of truth (v0.8).
    cap_reg = get_default_capability_registry()

    # Build tool router from real ToolRuntime catalog
    tool_registry = _build_default_registry(cap_reg)
    tool_router = ToolRouter(registry=tool_registry)

    # Module/Skill registries derived from CapabilityRegistry (legacy API
    # preserved; consumers can keep calling .snapshot(), .list_enabled_*() etc.)
    module_reg = ModuleRegistry.from_capabilities(cap_reg)
    skill_reg = SkillRegistry.from_capabilities(cap_reg, base_skill_registry=SkillRegistry())

    svc = RuntimeServices(
        tool_service=tool_router,
        skill_service=skill_reg,
        module_service=module_reg,
        audit_service={
            "events": EventRecorder(),
            "trace": TraceRecorder(),
            "rollout": RolloutRecorder(),
        },
        capability_registry=cap_reg,
    )
    return svc


def _build_default_registry(capability_registry=None) -> "ToolRegistry":
    """Build ToolRegistry from the real ToolRuntime catalog + capability tools.

    v0.8: capability tools are registered via ToolRegistry.register_capability_tools
    which consumes the CapabilityRegistry (truth-source). The legacy
    `_register_capability_tools` is kept as a fallback for direct injection.
    """
    from agent.tools.registry import ToolRegistry
    reg = ToolRegistry()
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        reg = ToolRegistry.from_runtime_client(client)
    except Exception:
        pass
    # Register capability-layer tools
    if capability_registry is not None:
        reg.register_capability_tools(capability_registry)
    else:
        _register_capability_tools(reg)
    return reg


def _register_capability_tools(registry: "ToolRegistry"):
    """Legacy fallback: register config_translation and knowledge tools directly.

    Kept for backward compatibility — when CapabilityRegistry is not
    available, this still wires the two known capability tools. The
    CapabilityRegistry path is the preferred truth-source path.
    """
    from agent.modules.config_translation.tools import TOOL_CONFIG_TRANSLATION, tool_handler as config_handler
    from agent.modules.knowledge.tools import TOOL_KNOWLEDGE_QUERY, tool_handler as knowledge_handler

    for spec, handler in [
        (TOOL_CONFIG_TRANSLATION, config_handler),
        (TOOL_KNOWLEDGE_QUERY, knowledge_handler),
    ]:
        if spec.tool_id not in registry._specs:
            registry._specs[spec.tool_id] = spec
            if not hasattr(registry, '_handlers'):
                registry._handlers = {}
            registry._handlers[spec.tool_id] = handler
