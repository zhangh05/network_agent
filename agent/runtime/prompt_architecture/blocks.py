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
    """Build a block describing the current capability/tool model."""
    safe = getattr(ctx, "safe_context", None) or {}
    tool_scene = safe.get("tool_scene") or {}
    capability_routing = (
        tool_scene.get("capability_routing")
        or tool_scene.get("tool_planner", {}).get("capability_routing")
        or {}
    )

    lines = [
        "Current execution model (capability-first):",
        "- Capability = business intent (routed by keywords) → exposes Tools",
        "- Tool = callable adapter; use tool.catalog.search to discover outside current route.",
        "- Module = implementation service, not directly called by the LLM.",
        "",
        "Capability routing for this turn:",
    ]

    if capability_routing:
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
    """Build a block listing visible tools with enriched descriptions.

    Uses Anthropic-style tool guidance: each tool gets [use when] + [avoid when]
    hints to improve selection accuracy and reduce incorrect tool calls.
    """
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    visible_tools = (
        getattr(ctx, "visible_tool_ids", None)
        or (getattr(ctx, "metadata", {}) or {}).get("visible_tools", [])
    )
    if not visible_tools:
        return None

    # Group by namespace prefix
    categories: dict[str, list[str]] = {}
    for tid in visible_tools:
        parts = tid.split(".")
        cat = parts[0] if parts else "other"
        categories.setdefault(cat, []).append(tid)

    lines = [
        "Visible tools for this turn (grouped by catalog):",
        "  Use only the tools listed below. Do not call any tool outside this list.",
        "  [✓ use] = when to use this tool.  [✗ avoid] = when NOT to use this tool.",
        "",
    ]
    for cat in sorted(categories):
        tools = categories[cat]
        lines.append(f"[{cat}] ({len(tools)} tools)")
        for tid in sorted(tools):
            entry = TOOL_NAMESPACE.get(tid)
            if entry:
                usage = entry.usage_hint or ""
                not_for = entry.not_for or ""
                parts = []
                if usage:
                    parts.append(f"[✓ use] {usage}")
                if not_for:
                    parts.append(f"[✗ avoid] {not_for}")
                hint = " | ".join(parts) if parts else ""
                lines.append(f"  - {tid}" + (f": {hint[:300]}" if hint else ""))
            else:
                lines.append(f"  - {tid}")
        lines.append("")

    return PromptBlock(
        block_id="active_tool_contract",
        title="Tool Catalog",
        content="\n".join(lines),
        priority=50,
        token_budget=1200,
    )
