# agent/runtime/context_tools.py
"""Tool visibility and planning helpers for TurnContext construction.

v3.3: is_tool_followup moved to cognition/scene_decision.py.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.scene_decision import is_tool_followup


def build_base_tool_router(ctx, services):
    """Build a fresh per-turn ToolRouter from the shared service router."""
    if not (services and getattr(services, "tool_service", None)):
        return None
    from agent.tools.router import ToolRouter

    router = services.tool_service
    if isinstance(router, ToolRouter):
        per_turn = ToolRouter.for_turn(router.registry)
        per_turn.dispatch_delegate = router.dispatch
        return per_turn
    return router


def plan_tool_visibility(ctx, session, services, *, selected_skills: list[str]) -> dict[str, Any]:
    """Apply scene routing + deterministic planner and return visibility metadata.

    Returns a dict with selected_visible_tools, dynamic_visibility, tool_scene,
    rule_tool_scene, and warnings. The function mutates ctx.tool_router when a
    per-turn allowlist is resolved.
    """
    result = {
        "selected_visible_tools": [],
        "dynamic_visibility": False,
        "tool_scene": {},
        "rule_tool_scene": {},
        "warnings": [],
    }
    cap_reg = getattr(services, "capability_registry", None) if services else None
    selector = getattr(services, "skill_selector", None) if services else None
    if selector is None or cap_reg is None or ctx.tool_router is None:
        return result

    try:
        from agent.tools.router import ToolRouter
        from agent.llm.tool_adapter import from_llm_tool_name
        from agent.runtime.tool_category_router import route_tool_scene
        from agent.runtime.tool_planner import plan_tools
        from tool_runtime.tool_namespace import TOOL_NAMESPACE

        base_reg = getattr(ctx.tool_router, "registry", None) or (
            ctx.tool_router if hasattr(ctx.tool_router, "list_model_visible") else None
        )
        if base_reg is None:
            return result

        user_msg = ctx.user_input or ""
        session_meta = getattr(session, "metadata", None) or {}
        previous_scene = session_meta.get("last_tool_scene") if isinstance(session_meta, dict) else None
        previous_rule_scene = session_meta.get("last_rule_tool_scene") if isinstance(session_meta, dict) else None
        if is_tool_followup(user_msg) and isinstance(previous_scene, dict):
            rule_scene = dict(previous_rule_scene or previous_scene)
            rule_scene["reason"] = (
                str(rule_scene.get("reason") or "")
                + "；follow-up 继承上一轮工具场景"
            ).strip("；")
            rule_scene["followup_inherited"] = True
        else:
            rule_scene = route_tool_scene(
                user_input=user_msg,
                session_context={
                    **session_meta,
                    "workspace_id": ctx.workspace_id,
                    "selected_skills": selected_skills,
                },
            )

        tool_scene = plan_tools(
            user_input=user_msg,
            safe_context={},
            rule_scene=rule_scene,
            available_catalog={"tools": list(TOOL_NAMESPACE)},
            model_config=ctx.model_config,
        )
        allowed_tools = list(tool_scene.get("candidate_tools") or [])
        ctx.tool_router = ToolRouter.for_turn(base_reg, allowed_tool_ids=allowed_tools)
        if services and getattr(services, "tool_service", None) and hasattr(services.tool_service, "dispatch"):
            ctx.tool_router.dispatch_delegate = services.tool_service.dispatch

        visible_tools = sorted({
            from_llm_tool_name(t["function"]["name"])
            for t in ctx.tool_router.model_visible_tools()
        })
        ctx.visible_tool_ids = visible_tools
        result.update({
            "selected_visible_tools": visible_tools,
            "dynamic_visibility": True,
            "tool_scene": tool_scene,
            "rule_tool_scene": rule_scene,
        })
    except Exception as e:
        result["warnings"].append(f"skill_selector_error: {e!r}")
    return result


def persist_tool_scene_to_session(session, tool_scene: dict, rule_tool_scene: dict) -> None:
    if not tool_scene or not hasattr(session, "metadata"):
        return
    if session.metadata is None:
        session.metadata = {}
    session.metadata["last_tool_scene"] = tool_scene
    session.metadata["last_rule_tool_scene"] = rule_tool_scene
