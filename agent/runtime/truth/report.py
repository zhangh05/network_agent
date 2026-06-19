# agent/runtime/truth/report.py
"""TruthReport — unified truth report combining version, config, and capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.runtime.truth.capabilities import CapabilityTruth
from agent.runtime.truth.config import ConfigTruth
from agent.runtime.truth.version import VersionTruth


@dataclass
class TruthReport:
    version: str = ""
    runtime_mode: str = ""
    model_provider: str = ""
    tool_count: int = 0
    visible_tool_count: int = 0
    enabled_skills: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TruthReporter:
    """Generate a TruthReport and write to ctx.metadata."""

    def report(self, ctx) -> TruthReport:
        ver = VersionTruth()
        cfg = ConfigTruth().snapshot(ctx)
        cap = CapabilityTruth().snapshot(ctx)

        warnings: list[str] = []
        if not cfg.model_provider:
            warnings.append("model_provider not configured")
        if cap.tool_count == 0:
            warnings.append("no tools registered")

        report = TruthReport(
            version=ver.full(),
            runtime_mode=cfg.runtime_mode,
            model_provider=cfg.model_provider,
            tool_count=cap.tool_count,
            visible_tool_count=cap.visible_tool_count,
            enabled_skills=list(cap.enabled_skills),
            warnings=warnings,
            metadata={
                "module_status": cap.module_status,
                "model_name": cfg.model_name,
                "workspace_id": cfg.workspace_id,
            },
        )

        ctx.metadata["truth_report"] = {
            "version": report.version,
            "runtime_mode": report.runtime_mode,
            "model_provider": report.model_provider,
            "tool_count": report.tool_count,
            "visible_tool_count": report.visible_tool_count,
            "enabled_skills": report.enabled_skills,
            "warnings": report.warnings,
        }
        return report
