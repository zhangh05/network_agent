"""v2.3 capability actions used by the intelligent planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tool_runtime.tool_governance import is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE, get_namespace_entry


@dataclass(frozen=True)
class CapabilityAction:
    action_id: str
    category: str
    group: str
    preferred_tools: tuple[str, ...]
    fallback_tools: tuple[str, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "category": self.category,
            "group": self.group,
            "preferred_tools": list(self.preferred_tools),
            "fallback_tools": list(self.fallback_tools),
            "reason": self.reason,
        }


def _action(
    action_id: str,
    category: str,
    group: str,
    preferred: tuple[str, ...],
    fallback: tuple[str, ...] = (),
    reason: str = "",
) -> CapabilityAction:
    return CapabilityAction(action_id, category, group, preferred, fallback, reason)


EXPLICIT_CAPABILITY_ACTIONS: dict[str, CapabilityAction] = {
    "workspace.file.read": _action(
        "workspace.file.read", "workspace", "file",
        ("workspace.file.read", "workspace.file.preview"),
        ("workspace.file.list",),
        "Read or preview workspace files before analysis.",
    ),
    "workspace.file.manage": _action(
        "workspace.file.manage", "workspace", "file",
        ("workspace.file.list", "workspace.file.exists", "workspace.file.edit", "workspace.file.patch"),
        (),
        "List, check, edit, or patch workspace files.",
    ),
    "workspace.artifact.manage": _action(
        "workspace.artifact.manage", "workspace", "artifact",
        ("workspace.artifact.list", "workspace.artifact.search", "workspace.artifact.read", "workspace.artifact.save"),
        ("workspace.artifact.diff", "workspace.artifact.export", "workspace.artifact.tag", "workspace.artifact.delete_soft"),
        "Work with workspace artifact metadata and safe content.",
    ),
    "network.config.analyze": _action(
        "network.config.analyze", "network", "config",
        ("network.config.parse", "network.interface.extract", "network.route.extract"),
        (),
        "Offline network configuration analysis.",
    ),
    "network.config.translate": _action(
        "network.config.translate", "network", "config",
        ("network.config.translate",),
        (),
        "Offline network configuration translation.",
    ),
    "web.official_docs.search": _action(
        "web.official_docs.search", "web", "docs",
        ("web.docs.official_search", "web.search", "web.page.summarize"),
        ("web.page.extract_links",),
        "Search official documentation and summarize public pages.",
    ),
    "knowledge.search_and_answer": _action(
        "knowledge.search_and_answer", "knowledge", "search",
        ("knowledge.query", "knowledge.search"),
        ("knowledge.chunk.read", "knowledge.source.read", "knowledge.parent.read"),
        "Search the knowledge base and answer from safe excerpts.",
    ),
    "host.environment.inspect": _action(
        "host.environment.inspect", "host", "shell",
        ("host.shell.exec", "host.powershell.exec", "host.python.exec", "runtime.health", "runtime.diagnostics"),
        (),
        "Inspect or operate on the current local host under approval policy.",
    ),
    "runtime.audit.inspect": _action(
        "runtime.audit.inspect", "runtime", "run",
        ("runtime.health", "runtime.diagnostics", "run.list", "run.summary.get", "session.list", "session.summary.get"),
        ("session.snapshot.list", "session.export"),
        "Inspect runtime, run, and session audit metadata.",
    ),
    "memory.profile.manage": _action(
        "memory.profile.manage", "memory", "profile",
        ("memory.search", "memory.list", "memory.profile.get", "memory.profile.set"),
        ("memory.create", "memory.confirm", "memory.update", "memory.delete_soft"),
        "Search and manage memory records and profile fields.",
    ),
    "report.create_and_save": _action(
        "report.create_and_save", "report_data", "report",
        ("report.markdown.render", "workspace.artifact.save"),
        ("data.table.render", "diagram.mermaid.render"),
        "Render a report and save it as a workspace artifact.",
    ),
    "data.text.process": _action(
        "data.text.process", "report_data", "text",
        ("text.redact", "text.diff", "text.keywords.extract"),
        ("data.json.validate", "data.yaml.validate", "data.csv.summarize", "data.table.extract", "data.table.render"),
        "Process structured data and safe text outputs.",
    ),
    "agent.team.coordinate": _action(
        "agent.team.coordinate", "agent", "subagent",
        ("agent.spawn", "agent.role.list", "agent.result.get"),
        ("agent.team.run", "skill.list", "skill.request_load", "skill.load", "skill.find", "skill.inspect", "skill.create"),
        "Coordinate skills and sub-agent work under runtime limits.",
    ),
}


def _default_action_for(canonical_id: str) -> CapabilityAction:
    entry = get_namespace_entry(canonical_id)
    action_id = canonical_id
    return CapabilityAction(
        action_id=action_id,
        category=entry.category,
        group=entry.group,
        preferred_tools=(canonical_id,),
        fallback_tools=(),
        reason="Direct canonical action for a stable, non-overlapping tool.",
    )


CAPABILITY_ACTIONS: dict[str, CapabilityAction] = dict(EXPLICIT_CAPABILITY_ACTIONS)
for _canonical_id in sorted(TOOL_NAMESPACE):
    if _canonical_id not in CAPABILITY_ACTIONS and is_planner_visible(_canonical_id):
        CAPABILITY_ACTIONS[_canonical_id] = _default_action_for(_canonical_id)


def action_exists(action_id: str) -> bool:
    return action_id in CAPABILITY_ACTIONS


def tools_for_action(action_id: str, *, include_fallback: bool = True, available: set[str] | None = None) -> list[str]:
    action = CAPABILITY_ACTIONS[action_id]
    tools = [*action.preferred_tools]
    if include_fallback:
        tools.extend(action.fallback_tools)
    result: list[str] = []
    for tool_id in tools:
        if tool_id not in TOOL_NAMESPACE:
            continue
        if available is not None and tool_id not in available:
            continue
        if not is_planner_visible(tool_id):
            continue
        if tool_id not in result:
            result.append(tool_id)
    return result


def action_for_tool_set(tool_ids: list[str]) -> str:
    tool_set = set(tool_ids)
    ranked = [
        "workspace.file.read",
        "web.official_docs.search",
        "network.config.analyze",
        "report.create_and_save",
        "host.environment.inspect",
        "knowledge.search_and_answer",
        "runtime.audit.inspect",
        "memory.profile.manage",
        "data.text.process",
        "agent.team.coordinate",
    ]
    for action_id in ranked:
        action_tools = set(tools_for_action(action_id, include_fallback=True))
        if action_tools and tool_set & action_tools:
            return action_id
    for tool_id in tool_ids:
        if tool_id in CAPABILITY_ACTIONS:
            return tool_id
    return "data.text.process"


def canonical_capability_coverage() -> dict[str, list[str]]:
    covered: set[str] = set()
    for action in CAPABILITY_ACTIONS.values():
        covered.update(t for t in action.preferred_tools if t in TOOL_NAMESPACE)
        covered.update(t for t in action.fallback_tools if t in TOOL_NAMESPACE)
    exempt = sorted(set(TOOL_NAMESPACE) - covered)
    return {
        "covered": sorted(covered),
        "exempt": exempt,
    }

