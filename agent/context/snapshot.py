# agent/context/snapshot.py
"""RuntimeSnapshot — injected into every LLM turn as system context.

v0.8: when a CapabilityRegistry is attached, RuntimeSnapshot summarizes
the registry's view (enabled / planned capabilities, visible business
tools, safety contract). The registry is the truth-source.

Falls back to enabled_* / planned_* lists when no registry is
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

            lines.append("Enabled capabilities:")
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
                if self.safety_baseline.get("real_device_access"):
                    lines.append("  - Real device access ENABLED (SSH/Telnet allowed; dangerous commands blocked)")
                else:
                    lines.append("  - No real device access")
                if self.safety_baseline.get("allows_config_push"):
                    lines.append("  - Config push ALLOWED (requires approval)")
                else:
                    lines.append("  - Config push forbidden")
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
            # Compatibility fallback (no capability registry available).
            if self.metadata.get("capability_registry_fallback"):
                lines.append("[WARN] CapabilityRegistry not attached — "
                             "falling back to enabled_* / planned_* lists.")
                lines.append("")
            lines.append("Current Tools (available NOW):")
            lines.append(f"  Total: {self.tool_count} tools in catalog, "
                         f"{self.visible_tool_count} visible to LLM")
            lines.append("")

            lines.append("Enabled Capabilities:")
            for s in self.enabled_skills:
                lines.append(f"  ✅ {s}")
            if self.planned_skills:
                lines.append("Planned Capabilities (NOT yet available):")
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
            "enabled_capabilities": self.enabled_skills,
            "planned_capabilities": self.planned_skills,
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
            "selected_capabilities": self.selected_skills,
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
    capability_catalog: Optional[list] = None,
    skill_snap: Optional[dict] = None,
    module_snap: Optional[dict] = None,
    base_enabled_skills: Optional[list] = None,
    selected_skills: Optional[list] = None,
    selected_visible_tools: Optional[list] = None,
    dynamic_tool_visibility: bool = False,
) -> RuntimeSnapshot:
    """Build a RuntimeSnapshot.

    v3.9.4: `capability_catalog` is a frozen list-of-dicts snapshot
    of the business capability catalog. We derive every summary field
    (visible tools, safety baseline, enabled/planned skills + modules)
    from that snapshot without re-reading the live catalog module. This
    keeps the snapshot picklable and stage-local.
    """
    snap = RuntimeSnapshot(
        tool_count=tool_count,
        visible_tool_count=visible_tool_count,
        workspace_id=workspace_id,
        session_id=session_id,
        model=model,
    )
    if capability_catalog:
        enabled = [c for c in capability_catalog if c.get("status") == "enabled"]
        planned = [c for c in capability_catalog if c.get("status") == "planned"]

        # Compact view of all capabilities (capability_id + status + modules).
        snap.capability_baseline = {
            "total": len(capability_catalog),
            "enabled": len(enabled),
            "planned": len(planned),
            "capabilities": [
                {
                    "capability_id": c.get("capability_id"),
                    "status": c.get("status"),
                    "module_ids": list(c.get("module_ids") or ()),
                    "recommended_tool_ids": list(c.get("recommended_tool_ids") or ()),
                }
                for c in capability_catalog
            ],
        }

        # Visible business tools: union of recommended_tool_ids for enabled
        # capabilities (or per-turn projection if dynamic visibility is on).
        if dynamic_tool_visibility and selected_visible_tools:
            snap.visible_business_tools = list(selected_visible_tools)
        else:
            visible_set = []
            seen = set()
            for c in enabled:
                for tid in c.get("recommended_tool_ids") or ():
                    if tid and tid not in seen:
                        visible_set.append(tid)
                        seen.add(tid)
            snap.visible_business_tools = visible_set

        # Safety baseline: merged safety_notes from enabled capabilities.
        safety_notes: list[str] = []
        for c in enabled:
            for note in c.get("safety_notes") or ():
                if note and note not in safety_notes:
                    safety_notes.append(note)
        snap.safety_baseline = {"notes": safety_notes, "count": len(safety_notes)}

        # Enabled / planned skills mirror the capability ids.
        cap_enabled = [c.get("capability_id", "") for c in enabled if c.get("capability_id")]
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
        snap.planned_skills = [c.get("capability_id", "") for c in planned if c.get("capability_id")]

        # Modules projected from capability module_ids.
        enabled_modules: list[str] = []
        planned_modules: list[str] = []
        seen = set()
        for c in enabled:
            for mid in c.get("module_ids") or ():
                if mid and mid not in seen:
                    enabled_modules.append(mid)
                    seen.add(mid)
        seen = set()
        for c in planned:
            for mid in c.get("module_ids") or ():
                if mid and mid not in seen:
                    planned_modules.append(mid)
                    seen.add(mid)
        snap.enabled_modules = enabled_modules
        snap.planned_modules = planned_modules
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
