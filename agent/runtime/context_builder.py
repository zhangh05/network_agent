# agent/runtime/context_builder.py
"""ContextBuilder — builds TurnContext from session + turn + services."""

import uuid
from agent.core.turn_context import TurnContext
from agent.context.snapshot import RuntimeSnapshot, build_runtime_snapshot
from agent.llm.config import resolve_provider_config


def build_turn_context(session, turn, services) -> TurnContext:
    """Build complete TurnContext for a turn execution.

    v0.8: when services.capability_registry is available, RuntimeSnapshot
    is built from the CapabilityRegistry (truth-source). Otherwise, falls
    back to the legacy skill/module snapshots and tags the snapshot with
    a fallback warning.
    """
    ctx = TurnContext(
        turn_id=turn.turn_id,
        session_id=session.session_id,
        workspace_id=session.workspace_id or "default",
        trace_id=str(uuid.uuid4()),
        user_input=turn.op.user_input if turn.op else "",
    )

    # 1. Load model config
    try:
        cfg = resolve_provider_config()
        ctx.model_config = cfg
    except Exception:
        ctx.model_config = {"enabled": False, "provider_type": "disabled"}

    # 2. Load history window
    if hasattr(session, 'history') and session.history:
        ctx.history_window = list(session.history[-8:])

    # 3. Build ToolRouter
    if services and services.tool_service:
        ctx.tool_router = services.tool_service

    # 4. Build SkillRegistry snapshot
    skill_snap = {}
    if services and services.skill_service:
        try:
            skill_snap = services.skill_service.snapshot()
        except Exception:
            skill_snap = {}
    ctx.skill_snapshot = skill_snap

    # 5. Build ModuleRegistry snapshot
    module_snap = {}
    if services and services.module_service:
        try:
            module_snap = services.module_service.snapshot()
        except Exception:
            module_snap = {}
    ctx.module_snapshot = module_snap

    # 6. Build RuntimeSnapshot
    visible_tools = []
    all_tools_count = 0
    if ctx.tool_router:
        try:
            visible_tools = ctx.tool_router.model_visible_tools()
        except Exception:
            pass
        try:
            if ctx.tool_router.registry:
                all_tools_count = len(ctx.tool_router.registry.list_all())
        except Exception:
            all_tools_count = len(visible_tools)

    # v0.8: prefer CapabilityRegistry when available.
    cap_reg = getattr(services, "capability_registry", None) if services else None
    # Pull base / system skills (e.g. assistant_chat) from the legacy
    # SkillRegistry so the snapshot still lists them.
    base_enabled = []
    if services and services.skill_service:
        try:
            base_enabled = [s.skill_id for s in services.skill_service.list_enabled_skills()
                            if s.skill_id == "assistant_chat"]
        except Exception:
            base_enabled = []
    snapshot = build_runtime_snapshot(
        tool_count=all_tools_count,
        visible_tool_count=len(visible_tools),
        workspace_id=ctx.workspace_id,
        session_id=ctx.session_id,
        model=ctx.model_config.get("model", ""),
        capability_registry=cap_reg,
        skill_snap=skill_snap,
        module_snap=module_snap,
        base_enabled_skills=base_enabled,
    )
    ctx.runtime_snapshot = snapshot.to_dict()

    # 7. Build safe_context
    ctx.safe_context = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}

    return ctx
