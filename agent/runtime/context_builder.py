# agent/runtime/context_builder.py
"""ContextBuilder — builds TurnContext from session + turn + services."""

import uuid
from agent.core.turn_context import TurnContext
from agent.context.snapshot import RuntimeSnapshot
from agent.llm.config import resolve_provider_config


def build_turn_context(session, turn, services) -> TurnContext:
    """Build complete TurnContext for a turn execution."""
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
    if ctx.tool_router:
        try:
            visible_tools = ctx.tool_router.model_visible_tools()
        except Exception:
            pass

    snapshot = RuntimeSnapshot(
        tool_count=len(visible_tools),
        visible_tool_count=len(visible_tools),
        enabled_skills=[s.get("skill_id", s.get("name", "")) for s in skill_snap.get("enabled", [])],
        planned_skills=[s.get("skill_id", s.get("name", "")) for s in skill_snap.get("planned", [])],
        enabled_modules=[m.get("module_id", m.get("name", "")) for m in module_snap.get("enabled", [])],
        planned_modules=[m.get("module_id", m.get("name", "")) for m in module_snap.get("planned", [])],
        workspace_id=ctx.workspace_id,
        session_id=ctx.session_id,
        model=ctx.model_config.get("model", ""),
    )
    ctx.runtime_snapshot = snapshot.to_dict()

    # 7. Build safe_context
    ctx.safe_context = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}

    return ctx
