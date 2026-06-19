# agent/runtime/context_tools.py
"""Tool visibility and planning helpers for TurnContext construction.

v3.4: plan_tool_visibility removed — replaced by ToolPlannerV2 in context_builder.
is_tool_followup canonical location: cognition/scene_decision.py.
"""

from __future__ import annotations


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


def persist_tool_scene_to_session(session, tool_scene: dict, rule_tool_scene: dict) -> None:
    if not tool_scene or not hasattr(session, "metadata"):
        return
    if session.metadata is None:
        session.metadata = {}
    session.metadata["last_tool_scene"] = tool_scene
    session.metadata["last_rule_tool_scene"] = rule_tool_scene
