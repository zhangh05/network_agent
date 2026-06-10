# agent/context/snapshot.py
"""RuntimeSnapshot — injected into every LLM turn as system context.

v0.8: when a CapabilityRegistry is attached, RuntimeSnapshot summarizes
the registry's view (enabled / planned capabilities, visible business
tools, safety contract). The registry is the truth-source.

Falls back to legacy enabled_* / planned_* lists when no registry is
attached; metadata.warnings records the fallback.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class RuntimeSnapshot:
    tool_count: int = 0
    visible_tool_count: int = 0
    enabled_skills: List[str] = field(default_factory=list)
    planned_skills: List[str] = field(default_factory=list)
    enabled_modules: List[str] = field(default_factory=list)
    planned_modules: List[str] = field(default_factory=list)
    workspace_id: str = ""
    session_id: str = ""
    model: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # v0.8 additions
    capability_baseline: dict = field(default_factory=dict)
    visible_business_tools: List[str] = field(default_factory=list)
    safety_baseline: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    # v0.8.1 additions (per-turn)
    selected_skills: List[str] = field(default_factory=list)
    selected_visible_tools: List[str] = field(default_factory=list)
    dynamic_tool_visibility: bool = False

    def to_prompt_text(self) -> str:
        lines = ["[RUNTIME SNAPSHOT]"]
        lines.append(f"Workspace: {self.workspace_id}")
        lines.append(f"Model: {self.model}")
        lines.append("")

        # Capability baseline (v0.8 — comes from CapabilityRegistry)
        if self.capability_baseline:
            enabled_caps = self.capability_baseline.get("enabled_capabilities", [])
            planned_caps = self.capability_baseline.get("planned_capabilities", [])

            lines.append("Current Capability Baseline:")
            if enabled_caps:
                lines.append("- Enabled capabilities:")
                for c in enabled_caps:
                    lines.append(f"  - {c.get('capability_id', '')}")
            if planned_caps:
                lines.append("- Planned capabilities:")
                for c in planned_caps:
                    lines.append(f"  - {c.get('capability_id', '')}")
                lines.append("  Note: planned capabilities are NOT callable.")
            lines.append("")

            lines.append("Enabled skills:")
            for s in self.enabled_skills:
                lines.append(f"  - {s}")
            lines.append("")

            if self.visible_business_tools:
                lines.append("Visible business tools:")
                for t in self.visible_business_tools:
                    lines.append(f"  - {t}")
                lines.append("")

            lines.append("Tool count:")
            lines.append(f"  total: {self.tool_count}")
            lines.append(f"  visible: {self.visible_tool_count}")
            lines.append("")

            if self.safety_baseline:
                lines.append("Safety:")
                lines.append("  - No real device access")
                lines.append("  - config.push forbidden")
                lines.append("  - translated_config is not deployable_config")
                lines.append("  - knowledge sources must not be fabricated")

            # v0.8.1: per-turn dynamic skill/tool visibility
            if self.dynamic_tool_visibility:
                lines.append("")
                lines.append("Selected skills for this turn:")
                for s in self.selected_skills:
                    lines.append(f"  - {s}")
                lines.append("")
                lines.append(f"Visible tools for this turn ({len(self.selected_visible_tools)}):")
                for t in self.selected_visible_tools:
                    lines.append(f"  - {t}")
                lines.append("")
                lines.append("Planned capabilities are NOT callable.")
            else:
                lines.append("")
                lines.append("(v0.8 fallback: per-turn skill selection not active; "
                             "all enabled capability skills are shown.)")
        else:
            # Legacy fallback (no capability registry available).
            if self.metadata.get("capability_registry_fallback"):
                lines.append("[WARN] CapabilityRegistry not attached — "
                             "falling back to legacy enabled_* / planned_* lists.")
                lines.append("")
            lines.append("Current Tools (available NOW):")
            lines.append(f"  Total: {self.tool_count} tools in catalog, "
                         f"{self.visible_tool_count} visible to LLM")
            lines.append("")

            lines.append("Enabled Skills:")
            for s in self.enabled_skills:
                lines.append(f"  ✅ {s}")
            if self.planned_skills:
                lines.append("Planned Skills (NOT yet available):")
                for s in self.planned_skills:
                    lines.append(f"  🔧 {s} — planned, not callable")

            lines.append("")
            lines.append("Enabled Modules:")
            for m in self.enabled_modules:
                lines.append(f"  ✅ {m}")
            if self.planned_modules:
                lines.append("Planned Modules (NOT yet available):")
                for m in self.planned_modules:
                    lines.append(f"  🔧 {m} — planned, not callable")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "tool_count": self.tool_count,
            "visible_tool_count": self.visible_tool_count,
            "enabled_skills": self.enabled_skills,
            "planned_skills": self.planned_skills,
            "enabled_modules": self.enabled_modules,
            "planned_modules": self.planned_modules,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "model": self.model,
            "generated_at": self.generated_at,
            "capability_baseline": self.capability_baseline,
            "visible_business_tools": self.visible_business_tools,
            "safety_baseline": self.safety_baseline,
            "metadata": self.metadata,
            "selected_skills": self.selected_skills,
            "selected_visible_tools": self.selected_visible_tools,
            "dynamic_tool_visibility": self.dynamic_tool_visibility,
        }


def build_runtime_snapshot(
    *,
    tool_count: int,
    visible_tool_count: int,
    workspace_id: str = "",
    session_id: str = "",
    model: str = "",
    capability_registry=None,
    skill_snap: Optional[dict] = None,
    module_snap: Optional[dict] = None,
    base_enabled_skills: Optional[list] = None,
    selected_skills: Optional[list] = None,
    selected_visible_tools: Optional[list] = None,
    dynamic_tool_visibility: bool = False,
) -> RuntimeSnapshot:
    """Build a RuntimeSnapshot. If capability_registry is given, summarize
    from it. Otherwise, fall back to the legacy skill/module snapshots
    and record a fallback warning in metadata.

    `base_enabled_skills` is the list of system / base skill ids that
    are NOT carried by a Capability (e.g. `assistant_chat`). They are
    added to the enabled-skill list so the prompt still reflects them.

    v0.8.1: per-turn `selected_skills` / `selected_visible_tools` /
    `dynamic_tool_visibility` are projected into the snapshot.
    """
    snap = RuntimeSnapshot(
        tool_count=tool_count,
        visible_tool_count=visible_tool_count,
        workspace_id=workspace_id,
        session_id=session_id,
        model=model,
    )
    if capability_registry is not None:
        snap.capability_baseline = capability_registry.to_snapshot_dict()
        snap.visible_business_tools = list(capability_registry.visible_tool_ids())
        snap.safety_baseline = capability_registry.safety_summary()
        # Mirror enabled/planned modules + skills from the registry so
        # downstream consumers (legacy APIs) keep working.
        cap_enabled = [s["skill_id"] for s in capability_registry.enabled_skills()]
        if base_enabled_skills:
            # Preserve order: base skills first, capability skills after,
            # dedup.
            seen = set()
            merged = []
            for s in base_enabled_skills + cap_enabled:
                if s and s not in seen:
                    merged.append(s)
                    seen.add(s)
            snap.enabled_skills = merged
        else:
            snap.enabled_skills = cap_enabled
        snap.planned_skills = [s["skill_id"] for s in capability_registry.planned_skills()]
        snap.enabled_modules = [m["module_id"] for m in capability_registry.enabled_modules()]
        snap.planned_modules = [m["module_id"] for m in capability_registry.planned_modules()]
    else:
        snap.metadata = {"capability_registry_fallback": True}
        if skill_snap:
            snap.enabled_skills = [s.get("skill_id", "") for s in skill_snap.get("enabled", [])]
            snap.planned_skills = [s.get("skill_id", "") for s in skill_snap.get("planned", [])]
        if module_snap:
            snap.enabled_modules = [m.get("module_id", "") for m in module_snap.get("enabled", [])]
            snap.planned_modules = [m.get("module_id", "") for m in module_snap.get("planned", [])]
    # v0.8.1 per-turn projection
    snap.selected_skills = list(selected_skills or [])
    snap.selected_visible_tools = list(selected_visible_tools or [])
    snap.dynamic_tool_visibility = bool(dynamic_tool_visibility)
    return snap
