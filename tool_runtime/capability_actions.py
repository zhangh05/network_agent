"""v3.0 canonical-only capability actions.

A capability_action is a high-level planner verb that maps to one or
more canonical_tool_ids. The planner resolves a user request into a
set of capability_actions, expands each action into its preferred /
fallback canonical tools, and then filters by governance (only
status == 'active' canonicals survive).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tool_runtime.tool_namespace import TOOL_NAMESPACE


@dataclass(frozen=True)
class CapabilityAction:
    capability_action: str
    category: str
    group: str
    preferred_tools: tuple[str, ...]
    fallback_tools: tuple[str, ...] = ()
    reason: str = ""

    def metadata(self) -> dict[str, Any]:
        return {
            "capability_action": self.capability_action,
            "category": self.category,
            "group": self.group,
            "preferred_tools": list(self.preferred_tools),
            "fallback_tools": list(self.fallback_tools),
            "reason": self.reason,
        }


EXPLICIT_CAPABILITY_ACTIONS: dict[str, CapabilityAction] = {
    # Host
    "host.environment.inspect": CapabilityAction(
        capability_action="host.environment.inspect",
        category="host",
        group="shell",
        preferred_tools=("host.shell.exec", "host.powershell.exec",
                         "host.python.exec", "runtime.health",
                         "runtime.diagnostics"),
        fallback_tools=("host.command.slash_run",),
        reason="Inspect or operate on the current local host under approval policy.",
    ),
    "host.shell.exec": CapabilityAction(
        capability_action="host.shell.exec", category="host", group="shell",
        preferred_tools=("host.shell.exec",), reason="Direct canonical action."),
    "host.powershell.exec": CapabilityAction(
        capability_action="host.powershell.exec", category="host", group="powershell",
        preferred_tools=("host.powershell.exec",), reason="Direct canonical action."),
    "host.python.exec": CapabilityAction(
        capability_action="host.python.exec", category="host", group="python",
        preferred_tools=("host.python.exec",), reason="Direct canonical action."),
    "host.command.slash_run": CapabilityAction(
        capability_action="host.command.slash_run", category="host", group="command",
        preferred_tools=("host.command.slash_run",), reason="Direct canonical action."),

    # Workspace
    "workspace.file.manage": CapabilityAction(
        capability_action="workspace.file.manage", category="workspace", group="file",
        preferred_tools=("workspace.file.list", "workspace.file.exists",
                         "workspace.file.edit", "workspace.file.patch"),
        fallback_tools=("workspace.file.read", "workspace.file.preview",
                        "workspace.file.write_artifact"),
        reason="Manage workspace files end-to-end.",
    ),
    "workspace.artifact.manage": CapabilityAction(
        capability_action="workspace.artifact.manage", category="workspace", group="artifact",
        preferred_tools=("workspace.artifact.list", "workspace.artifact.search",
                         "workspace.artifact.read", "workspace.artifact.save"),
        fallback_tools=("workspace.artifact.diff", "workspace.artifact.export",
                        "workspace.artifact.tag", "workspace.artifact.delete_soft"),
        reason="Work with workspace artifact metadata and safe content.",
    ),
    "workspace.document.pdf.extract_text": CapabilityAction(
        capability_action="workspace.document.pdf.extract_text",
        category="workspace", group="document",
        preferred_tools=("workspace.document.pdf.extract_text",),
        reason="Direct canonical action."),

    # Knowledge
    "knowledge.search_and_answer": CapabilityAction(
        capability_action="knowledge.search_and_answer",
        category="knowledge", group="search",
        preferred_tools=("knowledge.search",),
        fallback_tools=("knowledge.chunk.read", "knowledge.source.read",
                        "knowledge.parent.read"),
        reason="Search the knowledge base and answer from safe excerpts.",
    ),
    "knowledge.maintain": CapabilityAction(
        capability_action="knowledge.maintain",
        category="knowledge", group="import",
        preferred_tools=("knowledge.import.file", "knowledge.import.document",
                         "knowledge.import.artifact", "knowledge.source.reindex"),
        fallback_tools=("knowledge.source.reindex_all", "knowledge.source.disable",
                        "knowledge.source.delete"),
        reason="Maintain the knowledge base (import, reindex, retire).",
    ),

    # Network
    "config.analysis": CapabilityAction(
        capability_action="config.analysis",
        category="network", group="config_analysis",
        preferred_tools=("workspace.file.read", "config.analysis.run"),
        reason="Unified config analysis entrypoint.",
    ),
    "config.translation": CapabilityAction(
        capability_action="config.translation",
        category="network", group="config_analysis",
        preferred_tools=("workspace.file.read", "config.analysis.run"),
        reason="Unified config translation entrypoint.",
    ),
    "pcap.analysis": CapabilityAction(
        capability_action="pcap.analysis",
        category="network", group="pcap_analysis",
        preferred_tools=("workspace.file.read", "pcap.analysis.run"),
        reason="Unified PCAP analysis entrypoint.",
    ),

    # Web
    "web.official_docs.search": CapabilityAction(
        capability_action="web.official_docs.search",
        category="web", group="docs",
        preferred_tools=("web.docs.official_search", "web.search", "web.page.summarize"),
        fallback_tools=("web.page.extract_links",),
        reason="Search official documentation and summarize public pages.",
    ),
    "web.weather.read": CapabilityAction(
        capability_action="web.weather.read", category="web", group="weather",
        preferred_tools=("web.weather.current", "web.weather.forecast"),
        reason="Read weather for a public location."),

    # Runtime / Run / Session
    "runtime.audit.inspect": CapabilityAction(
        capability_action="runtime.audit.inspect",
        category="runtime", group="audit",
        preferred_tools=("runtime.health", "runtime.diagnostics",
                         "run.list", "run.summary.get",
                         "session.list", "session.summary.get"),
        fallback_tools=("session.snapshot.list", "session.export",
                        "runtime.selfcheck"),
        reason="Inspect runtime, run, and session audit metadata.",
    ),
    "runtime.review.manage": CapabilityAction(
        capability_action="runtime.review.manage",
        category="runtime", group="review",
        preferred_tools=("review.item.list", "review.item.update"),
        reason="List and update review items."),
    "runtime.session.manage": CapabilityAction(
        capability_action="runtime.session.manage",
        category="runtime", group="session",
        preferred_tools=("session.snapshot.create", "session.snapshot.list",
                         "session.checkpoint", "session.rewind",
                         "session.export"),
        reason="Manage session lifecycle and snapshots."),

    # Memory
    "memory.profile.manage": CapabilityAction(
        capability_action="memory.profile.manage",
        category="memory", group="profile",
        preferred_tools=("memory.search", "memory.list",
                         "memory.profile.get", "memory.profile.set"),
        fallback_tools=("memory.create", "memory.confirm",
                        "memory.update", "memory.delete_soft"),
        reason="Search and manage memory records and profile fields.",
    ),

    # Report / Data / Text
    "report.create_and_save": CapabilityAction(
        capability_action="report.create_and_save",
        category="report_data", group="report",
        preferred_tools=("report.markdown.render", "workspace.artifact.save"),
        fallback_tools=("data.table.render", "diagram.mermaid.render"),
        reason="Render a report and save it as a workspace artifact.",
    ),
    "data.text.process": CapabilityAction(
        capability_action="data.text.process",
        category="report_data", group="text",
        preferred_tools=("text.redact", "text.diff", "text.keywords.extract"),
        fallback_tools=("data.json.validate", "data.yaml.validate",
                        "data.csv.summarize", "data.table.extract",
                        "data.table.render"),
        reason="Process structured data and safe text outputs.",
    ),

    # Agent / Skill
    "agent.skill.manage": CapabilityAction(
        capability_action="agent.skill.manage",
        category="agent", group="skill",
        preferred_tools=("skill.list", "skill.find_skills", "skill.inspect",
                         "skill.load"),
        reason="Discover, inspect, load and unload skills."),
    "agent.team.coordinate": CapabilityAction(
        capability_action="agent.team.coordinate",
        category="agent", group="team",
        preferred_tools=("agent.spawn", "agent.role.list", "agent.result.get"),
        fallback_tools=("agent.team.run", "skill.list", "skill.load"),
        reason="Coordinate child-agent work under runtime limits.",
    ),
}


def _build_all_actions() -> dict[str, CapabilityAction]:
    actions = dict(EXPLICIT_CAPABILITY_ACTIONS)
    # Default: every planner-visible canonical tool gets a 1:1 action.
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import (
        TOOL_GOVERNANCE, planner_visible_tool_ids,
    )
    for canonical_id in planner_visible_tool_ids():
        if canonical_id in actions:
            continue
        entry = TOOL_NAMESPACE[canonical_id]
        gov = TOOL_GOVERNANCE[canonical_id]
        if gov.status != "active":
            continue
        actions[canonical_id] = CapabilityAction(
            capability_action=canonical_id,
            category=entry.category,
            group=entry.group,
            preferred_tools=(canonical_id,),
            reason="Direct canonical action.",
        )
    return actions


CAPABILITY_ACTIONS: dict[str, CapabilityAction] = _build_all_actions()


def action_exists(action_id: str) -> bool:
    """Check if a capability action id exists in the registry."""
    return action_id in CAPABILITY_ACTIONS


def tools_for_action(
    action_id: str,
    *,
    include_fallback: bool = False,
    available: set[str] | None = None,
    user_input: str = "",
    scene_context: dict | None = None,
) -> list[str]:
    """Expand a capability action into its preferred (and optionally fallback) tool ids.

    Returns only tools that are in ``available`` when ``available`` is provided.
    Falls back to returning [action_id] itself when the action_id is unknown
    but maps to a known canonical tool.

    v2.3.2: Fallback tools are filtered through action_class to prevent
    high-risk tools (mutate/execute/destructive) from entering the candidate list
    automatically.
    """
    action = CAPABILITY_ACTIONS.get(action_id)
    if action is None:
        # Unknown action: try returning the id as-is when it is a known tool.
        if available is not None and action_id in available:
            return [action_id]
        return []
    tools = list(action.preferred_tools)
    if include_fallback:
        from tool_runtime.action_class import classify_tool
        for ft in action.fallback_tools:
            entry = TOOL_NAMESPACE.get(ft)
            if entry is None:
                continue
            ac = classify_tool(ft, entry.category, entry.group, entry.action)
            # Only allow read-class fallback tools. write/mutate/execute/destructive
            # must be explicitly requested by the user, not auto-included.
            if ac.action_class == "read" and not ac.is_destructive:
                tools.append(ft)
    if available is not None:
        tools = [t for t in tools if t in available]
    return tools


def action_for_tool_set(tool_ids: list[str]) -> str:
    """Find the best capability action that covers the given set of tool ids.

    Returns the action whose preferred_tools best match the given tools,
    falling back to the first tool id itself when no action matches.
    """
    if not tool_ids:
        return ""
    best_action = ""
    best_score = 0
    tool_set = set(tool_ids)
    for action_id, action in CAPABILITY_ACTIONS.items():
        preferred_set = set(action.preferred_tools)
        overlap = len(tool_set & preferred_set)
        if overlap > best_score:
            best_score = overlap
            best_action = action_id
    return best_action or tool_ids[0]


def capability_actions_for(canonical_tool_id: str) -> list[str]:
    hits: list[str] = []
    for action_id, action in CAPABILITY_ACTIONS.items():
        if (canonical_tool_id in action.preferred_tools
                or canonical_tool_id in action.fallback_tools):
            hits.append(action_id)
    return sorted(hits)
