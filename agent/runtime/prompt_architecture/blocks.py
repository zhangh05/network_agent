# agent/runtime/prompt_architecture/blocks.py
"""Prompt block builders for the capability-first architecture.

Each builder produces a PromptBlock or None. The compiler assembles
them in priority order.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from typing import Any

from agent.runtime.prompt_architecture.models import PromptBlock


# ── Block builders ───────────────────────────────────────────────────

def build_environment_context_block(ctx) -> PromptBlock | None:
    """Build a compact dynamic environment block.

    This is execution context, not evidence. It gives the model the same basic
    orientation Codex/OpenCode-style agents rely on before choosing tools.
    """
    cwd = _safe_cwd()
    branch = _git_value(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    commit = _git_value(["git", "rev-parse", "--short", "HEAD"], cwd)
    dirty = _git_dirty_summary(cwd)
    shell = os.environ.get("SHELL", "") or "unknown"
    requested_by = getattr(ctx, "requested_by", "") or (getattr(ctx, "metadata", {}) or {}).get("requested_by", "")
    workspace_id = getattr(ctx, "workspace_id", "") or (getattr(ctx, "safe_context", {}) or {}).get("workspace_id", "")
    session_id = getattr(ctx, "session_id", "") or (getattr(ctx, "safe_context", {}) or {}).get("session_id", "")

    lines = [
        f"Working directory: {cwd}",
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Shell: {shell}",
        f"Git branch: {branch or 'unknown'}",
        f"Git commit: {commit or 'unknown'}",
        f"Git state: {dirty}",
        f"Workspace: {workspace_id or 'unspecified'}",
        f"Session: {session_id or 'unspecified'}",
        f"Requested by: {requested_by or 'unspecified'}",
        "Use this block as the source of truth for local execution assumptions.",
    ]
    return PromptBlock(
        block_id="environment_context",
        title="Environment Context",
        content="\n".join(lines),
        priority=10,
        token_budget=350,
    )

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


def build_skill_guidance_block(ctx) -> PromptBlock | None:
    """Build skill/capability guidance without inlining skill files."""
    snapshot = getattr(ctx, "runtime_snapshot", None) or {}
    metadata = getattr(ctx, "metadata", None) or {}
    selected = _string_list(
        metadata.get("selected_skills")
        or snapshot.get("selected_skills")
        or snapshot.get("selected_capabilities")
        or []
    )
    enabled = _string_list(
        snapshot.get("enabled_skills")
        or snapshot.get("enabled_capabilities")
        or []
    )
    if not selected and not enabled:
        return None

    lines = [
        "Load or consult a skill/capability when it directly matches the user's task.",
        "Do not inline full skill files into the answer. Use their guidance to choose workflow, tools, and output format.",
        "If no matching skill is visible, use visible discovery/catalog tools before guessing.",
    ]
    if selected:
        lines.append("Selected for this turn: " + ", ".join(selected[:8]))
    if enabled:
        lines.append("Available baseline: " + ", ".join(enabled[:12]))
    return PromptBlock(
        block_id="skill_guidance",
        title="Skill Guidance",
        content="\n".join(lines),
        priority=25,
        token_budget=350,
    )


def build_capability_context_block(ctx) -> PromptBlock | None:
    """Build a block describing the current capability/tool model."""
    safe = getattr(ctx, "safe_context", None) or {}
    tool_scene = safe.get("tool_scene") or {}
    selected_tools = list(
        getattr(ctx, "visible_tool_ids", None)
        or tool_scene.get("selected_visible_tools")
        or tool_scene.get("candidate_tools")
        or []
    )
    business_caps = safe.get("business_capabilities") or safe.get("capability_catalog") or []

    lines = [
        "Current execution model:",
        "- All 22 canonical tools are available through SSOT Runtime planning. No catalog search needed.",
        "- Each tool uses an `action` parameter to select sub-capabilities.",
        "- Do not call alias or removed tool ids.",
    ]

    if business_caps:
        lines.append("")
        lines.append("Business capability guidance:")
        lines.append(json.dumps(business_caps, ensure_ascii=False, default=str)[:2000])

    return PromptBlock(
        block_id="capability_context",
        title="Capability Context",
        content="\n".join(lines),
        priority=30,
        token_budget=600,
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
    from core.tools.tool_namespace import TOOL_NAMESPACE

    visible_tools = (
        getattr(ctx, "visible_tool_ids", None)
        or (getattr(ctx, "metadata", {}) or {}).get("visible_tools", [])
    )
    if not visible_tools:
        return None
    required_tools, optional_tools = _tool_recommendation_sets(ctx)

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
            label = _tool_recommendation_label(tid, required_tools, optional_tools)
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
                lines.append(f"  - {tid}{label}" + (f": {hint[:300]}" if hint else ""))
            else:
                lines.append(f"  - {tid}{label}")
        lines.append("")

    return PromptBlock(
        block_id="active_tool_contract",
        title="Tool Catalog",
        content="\n".join(lines),
        priority=50,
        token_budget=1200,
    )


def _safe_cwd() -> str:
    try:
        return os.getcwd()
    except Exception:
        return "unknown"


def _git_value(args: list[str], cwd: str) -> str:
    if not cwd or cwd == "unknown":
        return ""
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()[:120]
    except Exception:
        return ""
    return ""


def _git_dirty_summary(cwd: str) -> str:
    if not cwd or cwd == "unknown":
        return "unknown"
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode != 0:
            return "not_a_git_repo"
        lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        if not lines:
            return "clean"
        return f"dirty ({len(lines)} changed paths)"
    except Exception:
        return "unknown"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    seen = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _tool_recommendation_sets(ctx) -> tuple[set[str], set[str]]:
    metadata = getattr(ctx, "metadata", None) or {}
    decision = metadata.get("tool_planning_decision") or {}
    if not isinstance(decision, dict):
        decision = {}
    if not decision:
        safe = getattr(ctx, "safe_context", None) or {}
        scene = safe.get("tool_scene") if isinstance(safe, dict) else {}
        if isinstance(scene, dict):
            decision = scene.get("tool_planning_decision") or {}
    required = set(_string_list(decision.get("required_tools") or []))
    optional = set(_string_list(decision.get("optional_tools") or []))
    return required, optional


def _tool_recommendation_label(tool_id: str, required: set[str], optional: set[str]) -> str:
    if tool_id in required:
        return " [recommended]"
    if tool_id in optional:
        return " [optional]"
    return ""
