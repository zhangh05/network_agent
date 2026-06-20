# agent/runtime/prompt_architecture/blocks.py
"""Prompt block builders for the capability-first architecture.

Each builder produces a PromptBlock or None. The compiler assembles
them in priority order.
"""

from __future__ import annotations

import json
from typing import Any

from agent.runtime.prompt_architecture.models import PromptBlock


# ── Block builders ───────────────────────────────────────────────────

def build_runtime_state_block(ctx) -> PromptBlock | None:
    """Build a block from RuntimeStateSnapshot."""
    snapshot = getattr(ctx, "runtime_snapshot", None) or {}
    if not snapshot:
        return None
    return PromptBlock(
        block_id="runtime_state",
        title="Runtime State",
        content=json.dumps(snapshot, ensure_ascii=False, default=str)[:3000],
        priority=20,
        token_budget=800,
    )


def build_capability_context_block(ctx) -> PromptBlock | None:
    """Build a block describing the current capability/skill/module/tool model."""
    safe = getattr(ctx, "safe_context", None) or {}
    tool_scene = safe.get("tool_scene") or {}
    capability_routing = (
        tool_scene.get("capability_routing")
        or tool_scene.get("tool_planner", {}).get("capability_routing")
        or {}
    )

    meta = getattr(ctx, "metadata", {}) or {}
    selected_skills = meta.get("selected_skills", [])
    visible_tools = meta.get("visible_tools", [])

    lines = [
        "Current execution model:",
        "- Skill = capability manifest / business entry.",
        "- Module = implementation service, not directly called by the LLM.",
        "- Tool = callable adapter, preferably directory-level.",
        "",
        f"selected_skills: {selected_skills}",
        f"visible_tools: {visible_tools}",
    ]

    contracts = safe.get("loaded_skill_contracts") or []
    if contracts:
        clean_contracts = [
            {k: v for k, v in c.items() if k != "skill_prompt"}
            for c in contracts if isinstance(c, dict)
        ]
        lines.append("")
        lines.append("loaded_skill_contracts:")
        lines.append(json.dumps(clean_contracts, ensure_ascii=False, default=str)[:2000])

    if capability_routing:
        lines.append("")
        lines.append("capability_routing:")
        lines.append(json.dumps(capability_routing, ensure_ascii=False, default=str)[:2000])

    return PromptBlock(
        block_id="capability_context",
        title="Capability Context",
        content="\n".join(lines),
        priority=30,
        token_budget=900,
    )


def build_evidence_context_block(ctx) -> PromptBlock | None:
    """Build a block from safe_context evidence (knowledge, memory, artifacts)."""
    safe = getattr(ctx, "safe_context", None) or {}
    keep: dict[str, Any] = {}
    for key in (
        "workspace_id",
        "session_id",
        "knowledge_hits",
        "memory_hits",
        "artifact_refs",
        "tool_plan",
        "output_summary",
    ):
        if key in safe:
            keep[key] = safe[key]
    if not keep:
        return None
    return PromptBlock(
        block_id="evidence_context",
        title="Evidence Context",
        content=json.dumps(keep, ensure_ascii=False, default=str)[:4000],
        priority=40,
        token_budget=1200,
    )


def build_active_tool_contract_block(ctx) -> PromptBlock | None:
    """Build a block listing only the currently visible tools."""
    visible_tools = (
        getattr(ctx, "visible_tool_ids", None)
        or (getattr(ctx, "metadata", {}) or {}).get("visible_tools", [])
    )
    if not visible_tools:
        return None

    lines = [
        "Only the following tools are visible for this turn:",
        *[f"- {tool_id}" for tool_id in visible_tools],
        "",
        "Do not call internal or hidden tools.",
        "",
        "Business tool rules:",
        "- Use config.analysis.run for config parse/translate/interface/route/diff/summarize actions.",
        "- Use pcap.analysis.run for pcap parse/session/filter/align actions.",
    ]
    return PromptBlock(
        block_id="active_tool_contract",
        title="Active Tool Contract",
        content="\n".join(lines),
        priority=50,
        token_budget=700,
    )
