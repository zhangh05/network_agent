# agent/runtime/truth/capabilities.py
"""CapabilityTruth — snapshot of available tools, skills, and module status."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CapabilitySnapshot:
    tool_count: int = 0
    visible_tool_count: int = 0
    enabled_skills: list[str] = field(default_factory=list)
    module_status: dict[str, str] = field(default_factory=dict)


class CapabilityTruth:
    """Extract capability truth from ctx."""

    def snapshot(self, ctx) -> CapabilitySnapshot:
        visible = ctx.metadata.get("visible_tools") or []
        tool_count = 0
        if hasattr(ctx, "tool_router") and ctx.tool_router:
            try:
                reg = getattr(ctx.tool_router, "registry", None)
                if reg and hasattr(reg, "list_all"):
                    tool_count = len(reg.list_all())
            except Exception:
                tool_count = len(visible)
        else:
            tool_count = len(visible)

        skills = ctx.metadata.get("selected_skills") or []
        module_status = {}
        for key in ("context_status", "scene_decision_status", "runtime_state_status", "selector_status"):
            val = ctx.metadata.get(key)
            if val:
                module_status[key] = val

        return CapabilitySnapshot(
            tool_count=tool_count,
            visible_tool_count=len(visible),
            enabled_skills=list(skills),
            module_status=module_status,
        )
