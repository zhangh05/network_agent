# agent/runtime/services.py
"""RuntimeServices — dependency injection container for all runtime capabilities.

v3.9.4: ToolRegistry is built ONLY from ToolRuntimeClient/canonical
registry. There is no CapabilityRegistry and no register_capability_tools
path. The business capability catalog (`agent.capabilities.catalog`)
is a thin read-only description layer; it does not register tools and
does not influence visibility.
"""

from dataclasses import dataclass, field


@dataclass
class RuntimeServices:
    model_service: object = None      # LLM Runtime
    tool_service: object = None       # ToolRouter/Registry
    module_service: object = None     # ModuleRegistry (projected from catalog)
    artifact_service: object = None   # ArtifactStore
    knowledge_service: object = None  # Knowledge/RAG
    workspace_service: object = None  # Workspace state
    audit_service: object = None      # EventRecorder + TraceRecorder
    # v3.9.4: capability_catalog holds a frozen snapshot (list[dict]) of the
    # business capability catalog. We do NOT store the catalog module here
    # because the turn runtime state is deepcopied for parallel tool calls
    # and modules are not picklable. The snapshot is the only state we need
    # to answer "which business capabilities are available".
    capability_catalog: list = field(default_factory=list)


def default_runtime_services() -> RuntimeServices:
    """Create default RuntimeServices with all subsystems wired."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.modules.registry import ModuleRegistry
    from agent.audit.events import EventRecorder
    from agent.audit.trace import TraceRecorder
    from agent.audit.rollout import RolloutRecorder
    from agent.capabilities import catalog as _catalog

    # v3.9.4: ToolRegistry is built solely from ToolRuntimeClient.
    # No capability-side tool registration.
    tool_registry = _build_default_registry()
    tool_router = ToolRouter.for_turn(tool_registry)
    module_reg = ModuleRegistry()

    svc = RuntimeServices(
        tool_service=tool_router,
        module_service=module_reg,
        audit_service={
            "events": EventRecorder(),
            "trace": TraceRecorder(),
            "rollout": RolloutRecorder(),
        },
        # Frozen snapshot — picklable, safe for state deepcopy.
        capability_catalog=list(_catalog.list_all()),
    )
    return svc


def _build_default_registry(*args, **kwargs) -> "ToolRegistry":
    """Build ToolRegistry from the canonical ToolRuntime catalog.

    The canonical registry is the single source of tool truth. Extra
    arguments are ignored because registry construction is no longer
    parameterized by caller-owned capability registries.
    """
    from agent.tools.registry import ToolRegistry
    import logging
    _log = logging.getLogger(__name__)
    try:
        from core.tools.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        return ToolRegistry.from_runtime_client(client)
    except Exception as exc:
        _log.exception(
            "_build_default_registry: ToolRuntimeClient init FAILED — %s", exc
        )
        return ToolRegistry()
