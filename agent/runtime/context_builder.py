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

    v0.8.1: per-turn SkillSelector + Dynamic Tool Visibility.
    - SkillSelector.select() decides which skills to inject this turn
    - Selected skills' related_tools → candidate tool_ids
    - ToolRouter.apply_dynamic_visibility() intersects with the registry's
      safety filter (forbidden / planned / disabled are still excluded)
    - On any error from the selector, fall back to v0.8 behavior
      (all enabled skills, no dynamic visibility) and record a warning
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

    # 6. v0.8.1 SkillSelector: per-turn skills + per-turn tool visibility
    cap_reg = getattr(services, "capability_registry", None) if services else None
    selector = getattr(services, "skill_selector", None) if services else None
    user_msg = ctx.user_input or ""

    selected_skills: list[str] = []
    selected_visible_tools: list[str] = []
    dynamic_visibility = False
    selector_warnings: list[str] = []

    if selector is not None and cap_reg is not None:
        try:
            selected_skills = list(selector.select(user_msg, capability_registry=cap_reg))
            # Collect candidate tools from selected skills' related_tools.
            # assistant_chat has empty related_tools — that's fine, it
            # contributes no business tools.
            candidates: set[str] = set()
            for sk_id in selected_skills:
                if sk_id == "assistant_chat":
                    continue
                if sk_id == "capability_discovery":
                    continue
                cap = cap_reg.get(sk_id)
                if cap is None:
                    # skill_id may match a skill (not capability_id);
                    # walk skills list to find related_tools.
                    for c in cap_reg.list_all():
                        for s in c.skills:
                            if s.skill_id == sk_id:
                                candidates.update(s.related_tools)
                                break
                else:
                    # Direct capability match
                    for s in cap.skills:
                        if s.skill_id == sk_id:
                            candidates.update(s.related_tools)
                            break
            # Apply dynamic visibility on the router
            if ctx.tool_router is not None and candidates:
                ctx.tool_router.apply_dynamic_visibility(candidates)
                dynamic_visibility = True
                # Reflect the actual visible set (after safety filter).
                selected_visible_tools = sorted({
                    t["function"]["name"].replace("__", ".", 1)
                    for t in ctx.tool_router.model_visible_tools()
                })
            elif ctx.tool_router is not None and not candidates:
                # Pure chat / discovery → keep the registry's default
                # visible set, but record "no business tools" so the
                # snapshot can describe the situation.
                ctx.tool_router.apply_dynamic_visibility([])  # disable
                selected_visible_tools = []
                dynamic_visibility = False
        except Exception as e:
            # v0.8.1: never crash. Fall back to v0.8 behavior.
            selector_warnings.append(f"skill_selector_error: {e!r}")
            dynamic_visibility = False
            if ctx.tool_router is not None:
                try:
                    ctx.tool_router.apply_dynamic_visibility([])  # disable
                except Exception:
                    pass

    # 7. Build RuntimeSnapshot
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
        selected_skills=selected_skills,
        selected_visible_tools=selected_visible_tools,
        dynamic_tool_visibility=dynamic_visibility,
    )
    if selector_warnings:
        snapshot.metadata = dict(snapshot.metadata or {})
        snapshot.metadata.setdefault("warnings", []).extend(selector_warnings)
    ctx.runtime_snapshot = snapshot.to_dict()

    # 8. Build safe_context
    ctx.safe_context = {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}

    return ctx
