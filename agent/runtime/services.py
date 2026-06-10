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


def default_runtime_services() -> RuntimeServices:
    """Create default RuntimeServices with all subsystems wired."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.skills.registry import SkillRegistry
    from agent.modules.registry import ModuleRegistry
    from agent.audit.events import EventRecorder
    from agent.audit.trace import TraceRecorder
    from agent.audit.rollout import RolloutRecorder

    # Build tool router from real ToolRuntime catalog
    tool_registry = _build_default_registry()
    tool_router = ToolRouter(registry=tool_registry)

    svc = RuntimeServices(
        tool_service=tool_router,
        skill_service=SkillRegistry(),
        module_service=ModuleRegistry(),
        audit_service={
            "events": EventRecorder(),
            "trace": TraceRecorder(),
            "rollout": RolloutRecorder(),
        },
    )
    return svc


def _build_default_registry() -> "ToolRegistry":
    """Build ToolRegistry from the real ToolRuntime catalog + capability tools."""
    from agent.tools.registry import ToolRegistry
    reg = ToolRegistry()
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        reg = ToolRegistry.from_runtime_client(client)
    except Exception:
        pass
    # Register capability-layer tools
    _register_capability_tools(reg)
    return reg


def _register_capability_tools(registry: "ToolRegistry"):
    """Register config_translation and knowledge tools in the registry."""
    from agent.tools.schemas import ToolSpec as AgentToolSpec
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
