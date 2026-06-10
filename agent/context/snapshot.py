# agent/context/snapshot.py
"""RuntimeSnapshot — injected into every LLM turn as system context."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List


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

    def to_prompt_text(self) -> str:
        lines = ["[RUNTIME SNAPSHOT]"]
        lines.append(f"Workspace: {self.workspace_id}")
        lines.append(f"Model: {self.model}")
        lines.append("")

        lines.append("Current Tools (available NOW):")
        if self.visible_tool_count > 0:
            lines.append(f"  {self.visible_tool_count} tools visible to LLM")
        else:
            lines.append("  (no tools available)")

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
        }
