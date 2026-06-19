# agent/runtime/output/collector.py
"""ResultCollector — gathers OutputSources from action trace and evidence updates."""

from __future__ import annotations

import uuid
from typing import Any

from agent.runtime.output.models import OutputSource


class ResultCollector:
    """Collect raw outputs from ctx.metadata into typed OutputSource items."""

    def collect(self, ctx) -> list[OutputSource]:
        sources: list[OutputSource] = []
        sources.extend(self._from_action_trace(ctx))
        sources.extend(self._from_evidence_updates(ctx))
        return sources

    def _from_action_trace(self, ctx) -> list[OutputSource]:
        sources: list[OutputSource] = []
        trace = (ctx.metadata.get("action_trace") or []) if ctx else []
        for entry in trace:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") != "result":
                continue
            src = OutputSource(
                source_id=f"src_{uuid.uuid4().hex[:8]}",
                source_type="action_result",
                action_id=entry.get("action_id", ""),
                tool_id=entry.get("tool_id", ""),
                content_type=self._infer_content_type(entry.get("result")),
                content=entry.get("result"),
                summary=str(entry.get("summary", ""))[:500],
                metadata={"status": entry.get("status", "")},
            )
            sources.append(src)
        return sources

    def _from_evidence_updates(self, ctx) -> list[OutputSource]:
        sources: list[OutputSource] = []
        updates = (ctx.metadata.get("action_evidence_updates") or []) if ctx else []
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            src = OutputSource(
                source_id=f"src_{uuid.uuid4().hex[:8]}",
                source_type="action_result",
                tool_id=upd.get("tool_id", ""),
                content_type="text",
                content=upd.get("summary", ""),
                summary=str(upd.get("summary", ""))[:500],
                metadata={"from": "evidence_update"},
            )
            sources.append(src)
        return sources

    @staticmethod
    def _infer_content_type(content: Any) -> str:
        if content is None:
            return "unknown"
        if isinstance(content, dict):
            return "json"
        if isinstance(content, list):
            return "table"
        if isinstance(content, str):
            if content.strip().startswith("{") or content.strip().startswith("["):
                return "json"
            return "text"
        return "unknown"
