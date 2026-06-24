# agent/runtime/services.py
"""RuntimeServices — dependency injection container for all runtime capabilities."""

from dataclasses import dataclass, field


@dataclass
class RuntimeServices:
    model_service: object = None      # LLM Runtime
    tool_service: object = None       # ToolRouter/Registry
    module_service: object = None     # ModuleRegistry
    artifact_service: object = None   # ArtifactStore
    knowledge_service: object = None  # Knowledge/RAG
    workspace_service: object = None  # Workspace state
    audit_service: object = None      # EventRecorder + TraceRecorder
    # v3.3: CapabilityRegistry is the single source of truth for all
    # capabilities — intent routing, tool visibility, safety baselines.
    # Replaces the deprecated SkillRegistry / SkillSelector.
    capability_registry: object = None  # CapabilityRegistry | None


def default_runtime_services() -> RuntimeServices:
    """Create default RuntimeServices with all subsystems wired."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.modules.registry import ModuleRegistry
    from agent.audit.events import EventRecorder
    from agent.audit.trace import TraceRecorder
    from agent.audit.rollout import RolloutRecorder
    from agent.capabilities import get_default_capability_registry

    # CapabilityRegistry is the single source of truth.
    cap_reg = get_default_capability_registry()

    tool_registry = _build_default_registry(cap_reg)
    tool_router = ToolRouter.for_turn(tool_registry)
    module_reg = ModuleRegistry.from_capabilities(cap_reg)

    svc = RuntimeServices(
        tool_service=tool_router,
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
    """Build ToolRegistry from the real ToolRuntime catalog + capability tools."""
    from agent.tools.registry import ToolRegistry
    import logging
    _log = logging.getLogger(__name__)
    reg = ToolRegistry()
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        reg = ToolRegistry.from_runtime_client(client)
    except Exception as exc:
        _log.exception(
            "_build_default_registry: ToolRuntimeClient init FAILED — %s", exc
        )
    if capability_registry is not None:
        reg.register_capability_tools(capability_registry)
    return reg
