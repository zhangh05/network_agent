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
    # None means "fall back to default registries".
    capability_registry: object = None  # CapabilityRegistry | None
    # v0.8.1: SkillSelector decides per-turn skills; if None, the
    # ContextBuilder falls back to v0.8 behavior (all enabled skills).
    skill_selector: object = None       # SkillSelector | None


def default_runtime_services() -> RuntimeServices:
    """Create default RuntimeServices with all subsystems wired."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.skills.registry import SkillRegistry
    from agent.modules.registry import ModuleRegistry
    from agent.skills.selector import SkillSelector
    from agent.audit.events import EventRecorder
    from agent.audit.trace import TraceRecorder
    from agent.audit.rollout import RolloutRecorder
    from agent.capabilities import get_default_capability_registry

    # CapabilityRegistry is the single source of truth (v0.8).
    cap_reg = get_default_capability_registry()

    # Build the shared ToolRegistry from real ToolRuntime catalog + capability
    # tools. The ToolRegistry is immutable-once-built and safe to share.
    # Per-turn ToolRouter instances are built in context_builder.py; this
    # shared instance MUST NOT be used directly by any turn.
    tool_registry = _build_default_registry(cap_reg)
    # Use for_turn() to signify this is NOT a turn-capable router.
    # The context_builder must build a fresh ToolRouter per turn.
    tool_router = ToolRouter.for_turn(tool_registry)

    # Module/Skill registries derived from CapabilityRegistry (compat API
    # preserved; consumers can keep calling .snapshot(), .list_enabled_*() etc.)
    module_reg = ModuleRegistry.from_capabilities(cap_reg)
    skill_reg = SkillRegistry.from_capabilities(cap_reg)

    # v0.8.1: SkillSelector driven by CapabilityRegistry.
    skill_sel = SkillSelector(capability_registry=cap_reg)

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
        skill_selector=skill_sel,
    )
    return svc


def _build_default_registry(capability_registry=None) -> "ToolRegistry":
    """Build ToolRegistry from the real ToolRuntime catalog + capability tools.

    v0.8: capability tools are registered via ToolRegistry.register_capability_tools
    which consumes the CapabilityRegistry (truth-source).

    v2.3.3: All tool_ids are now canonical (non-canonical IDs are
    filtered out). Capability tools provide the actual handler implementations
    for knowledge.search, workspace.artifact.*, review.*, network.config.translate.
    """
    from agent.tools.registry import ToolRegistry
    reg = ToolRegistry()
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        reg = ToolRegistry.from_runtime_client(client)
    except Exception:
        pass
    # Register capability-layer tools (these provide the REAL implementations)
    if capability_registry is not None:
        reg.register_capability_tools(capability_registry)
    return reg
