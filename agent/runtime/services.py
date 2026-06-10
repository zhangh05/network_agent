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

    # Build tool registry from ToolRuntimeClient if available
    tool_registry = ToolRegistry()
    try:
        from tool_runtime.client import ToolRuntimeClient
        client = ToolRuntimeClient()
        tool_registry = ToolRegistry.from_runtime_client(client)
    except Exception:
        pass

    svc = RuntimeServices(
        tool_service=ToolRouter(registry=tool_registry),
        skill_service=SkillRegistry(),
        module_service=ModuleRegistry(),
        audit_service={
            "events": EventRecorder(),
            "trace": TraceRecorder(),
            "rollout": RolloutRecorder(),
        },
    )
    return svc
