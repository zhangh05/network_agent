# agent/runtime/context_builder.py
"""ContextBuilder — builds TurnContext from session + turn + services.

The builder is intentionally an orchestration pipeline. Heavy responsibilities
are delegated to focused helpers:
- context_history.py     — in-memory/disk history window handling
- context_tools.py       — tool scene routing and per-turn visibility
- context_safe.py        — ContextBundle → SafeContext extraction and scans
- context_compaction.py  — token budget estimation and compaction decisions
"""

from __future__ import annotations

import uuid

from agent.core.turn_context import TurnContext
from agent.context.snapshot import build_runtime_snapshot
from agent.llm.config import resolve_provider_config
from agent.runtime.context_history import initial_history_window
from agent.runtime.context_safe import safe_context_from_bundle
from agent.runtime.context_tools import (
    build_base_tool_router,
    plan_tool_visibility,
    persist_tool_scene_to_session,
)


def build_turn_context(session, turn, services) -> TurnContext:
    """Build complete TurnContext for a turn execution.

    This function should remain mostly orchestration. Runtime behavior stays
    compatible with the previous implementation, while context concerns are
    split into independently testable helpers.
    """
    ctx = TurnContext(
        turn_id=turn.turn_id,
        session_id=session.session_id,
        workspace_id=session.workspace_id or "default",
        trace_id=str(uuid.uuid4()),
        user_input=turn.op.user_input if turn.op else "",
    )
    ctx.metadata["context_status"] = "building"

    if bool(getattr(session, "is_sub_agent", False)):
        ctx.metadata["is_sub_agent"] = True

    ctx.model_config = _resolve_model_config()
    ctx.history_window = initial_history_window(session, k=8)
    ctx.tool_router = build_base_tool_router(ctx, services)

    skill_snap = _snapshot_service(getattr(services, "skill_service", None), "skill")
    module_snap = _snapshot_service(getattr(services, "module_service", None), "module")
    ctx.skill_snapshot = skill_snap
    ctx.module_snapshot = module_snap

    cap_reg = getattr(services, "capability_registry", None) if services else None
    selector = getattr(services, "skill_selector", None) if services else None
    selected_skills, selector_warnings = _select_skills(selector, cap_reg, ctx.user_input, ctx)

    visibility = plan_tool_visibility(
        ctx,
        session,
        services,
        selected_skills=selected_skills,
    )
    selected_visible_tools = list(visibility.get("selected_visible_tools") or [])
    dynamic_visibility = bool(visibility.get("dynamic_visibility"))
    tool_scene = dict(visibility.get("tool_scene") or {})
    rule_tool_scene = dict(visibility.get("rule_tool_scene") or {})
    selector_warnings.extend(list(visibility.get("warnings") or []))

    visible_tools, all_tools_count = _tool_counts(ctx)
    base_enabled = _base_enabled_skills(services)
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
    snapshot.metadata = dict(getattr(snapshot, "metadata", None) or {})
    if selector_warnings:
        snapshot.metadata.setdefault("warnings", []).extend(selector_warnings)
    if tool_scene:
        snapshot.metadata["tool_scene"] = tool_scene
        snapshot.metadata["rule_tool_scene"] = rule_tool_scene
    ctx.runtime_snapshot = snapshot.to_dict()

    ctx.safe_context = _build_safe_context(ctx, turn, selected_skills)
    if tool_scene:
        ctx.safe_context["tool_scene"] = tool_scene
        ctx.safe_context["tool_plan"] = tool_scene.get("tool_plan", [])
        ctx.safe_context["rule_tool_scene"] = rule_tool_scene

    _inject_loaded_skills(ctx, session)
    _write_context_metadata(
        ctx=ctx,
        session=session,
        selected_skills=selected_skills,
        selected_visible_tools=selected_visible_tools,
        tool_scene=tool_scene,
        rule_tool_scene=rule_tool_scene,
    )

    # v3.3: Compute SceneDecision for downstream consumers
    _attach_scene_decision(ctx, session)

    ctx.metadata["context_status"] = "ok" if not ctx.metadata.get("context_errors") else "degraded"
    return ctx


def _resolve_model_config() -> dict:
    try:
        return resolve_provider_config()
    except Exception:
        return {"enabled": False, "provider_type": "disabled"}


def _snapshot_service(service, label: str) -> dict:
    if not service:
        return {}
    try:
        return service.snapshot()
    except Exception:
        return {}


def _select_skills(selector, cap_reg, user_msg: str, ctx=None) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    if selector is None or cap_reg is None:
        if ctx is not None:
            ctx.metadata["selector_status"] = "unavailable"
        return [], warnings
    try:
        selected = list(selector.select(user_msg or "", capability_registry=cap_reg))
        if ctx is not None:
            ctx.metadata["selector_status"] = "ok"
        return selected, warnings
    except Exception as exc:
        msg = f"skill_selector_error: {exc!r}"
        warnings.append(msg)
        if ctx is not None:
            ctx.metadata["selector_status"] = "failed"
            ctx.metadata.setdefault("selector_errors", []).append(str(exc)[:200])
        return [], warnings


def _tool_counts(ctx) -> tuple[list, int]:
    visible_tools = []
    all_tools_count = 0
    if ctx.tool_router:
        try:
            visible_tools = ctx.tool_router.model_visible_tools()
        except Exception:
            visible_tools = []
        try:
            if ctx.tool_router.registry:
                all_tools_count = len(ctx.tool_router.registry.list_all())
        except Exception:
            all_tools_count = len(visible_tools)
    return visible_tools, all_tools_count


def _base_enabled_skills(services) -> list[str]:
    base_enabled = []
    if services and getattr(services, "skill_service", None):
        try:
            base_enabled = [
                s.skill_id
                for s in services.skill_service.list_enabled_skills()
                if s.skill_id == "assistant_chat"
            ]
        except Exception:
            base_enabled = []
    return base_enabled


def _build_safe_context(ctx, turn, selected_skills: list[str]) -> dict:
    from context.builder import build_context_bundle
    from context.schemas import ContextBudget

    try:
        derived_intent = ctx.metadata.get("intent", "")
        if not derived_intent and selected_skills:
            for s in selected_skills:
                if s not in ("assistant_chat", "capability_discovery"):
                    derived_intent = s
                    break
        derived_cap = ctx.metadata.get("capability_id", "") or derived_intent
        bundle = build_context_bundle(
            workspace_id=ctx.workspace_id,
            user_input=ctx.user_input or "",
            intent=derived_intent,
            capability_id=derived_cap,
            budget=ContextBudget(),
            run_id=turn.turn_id if turn else "",
            trace_id=ctx.trace_id,
        )
        ctx.metadata["safe_context_status"] = "ok"
        return safe_context_from_bundle(bundle, ctx)
    except Exception as e:
        ctx.metadata["safe_context_status"] = "failed"
        ctx.metadata.setdefault("context_errors", []).append(str(e)[:200])
        return {"workspace_id": ctx.workspace_id, "session_id": ctx.session_id}


def _inject_loaded_skills(ctx, session) -> None:
    session_loaded = getattr(session, "metadata", {}) or {}
    loaded_skills = (session_loaded.get("loaded_skills") or ctx.metadata.get("loaded_skills") or {})
    if not loaded_skills:
        return

    skill_lines = ["## Loaded Skills", ""]
    for skill_name, skill_info in loaded_skills.items():
        prompt = skill_info.get("skill_prompt", "")[:3000] if isinstance(skill_info, dict) else ""
        if prompt:
            skill_lines.append(f"### {skill_name}")
            skill_lines.append(prompt)
            skill_lines.append("")
    if len(skill_lines) > 2:
        ctx.safe_context["loaded_skills_section"] = "\n".join(skill_lines)


def _write_context_metadata(
    *,
    ctx,
    session,
    selected_skills: list[str],
    selected_visible_tools: list[str],
    tool_scene: dict,
    rule_tool_scene: dict,
) -> None:
    ctx.metadata["selected_skills"] = selected_skills
    ctx.metadata["visible_tools"] = selected_visible_tools
    ctx.visible_tool_ids = selected_visible_tools
    if tool_scene:
        ctx.metadata["tool_scene"] = tool_scene
        ctx.metadata["rule_tool_scene"] = rule_tool_scene
        ctx.metadata["tool_planner"] = tool_scene.get("tool_planner", {})
        if tool_scene.get("visibility"):
            ctx.metadata["tool_visibility"] = tool_scene.get("visibility")
        persist_tool_scene_to_session(session, tool_scene, rule_tool_scene)


def _attach_scene_decision(ctx, session) -> None:
    """Compute and attach SceneDecision + EvidenceBundle to ctx."""
    try:
        from agent.runtime.cognition.scene_decision import decide_scene

        session_meta = getattr(session, "metadata", None) or {}
        previous_scene = session_meta.get("last_tool_scene") if isinstance(session_meta, dict) else None
        previous_rule_scene = session_meta.get("last_rule_tool_scene") if isinstance(session_meta, dict) else None

        ctx.scene_decision = decide_scene(
            ctx.user_input or "",
            session_context=session_meta if isinstance(session_meta, dict) else {},
            previous_scene=previous_scene,
            previous_rule_scene=previous_rule_scene,
            intent=ctx.metadata.get("intent", ""),
        )
        ctx.metadata["scene_decision_status"] = "ok"
    except Exception as e:
        ctx.metadata["scene_decision_status"] = "failed"
        ctx.metadata.setdefault("context_errors", []).append(f"scene_decision: {e!s}"[:200])
