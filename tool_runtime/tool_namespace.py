"""v2.2 Tool namespace and alias resolution."""

from dataclasses import dataclass
from typing import Any

from tool_runtime.tool_namespace_data import NS_DATA


@dataclass(frozen=True)
class ToolNamespaceEntry:
    canonical_tool_id: str
    execution_tool_id: str
    legacy_tool_ids: tuple[str, ...]
    category: str
    group: str
    action: str
    display_name: str
    short_label: str
    usage_hint: str
    not_for: str

    def metadata(self) -> dict[str, Any]:
        return {
            "canonical_tool_id": self.canonical_tool_id,
            "execution_tool_id": self.execution_tool_id,
            "legacy_tool_ids": list(self.legacy_tool_ids),
            "category": self.category,
            "group": self.group,
            "action": self.action,
            "display_name": self.display_name,
            "short_label": self.short_label,
            "usage_hint": self.usage_hint,
            "not_for": self.not_for,
        }


CATEGORY_DEFS: dict[str, dict[str, str]] = {
    "host": {"name": "Host 本机环境", "description": "当前运行机器上的本机 OS、Shell、PowerShell、Python 工具"},
    "workspace": {"name": "Workspace 工作区", "description": "工作区文件、Artifact 制品和 workspace 元数据"},
    "knowledge": {"name": "Knowledge 知识库", "description": "知识库问答、检索、导入和索引管理"},
    "network": {"name": "Network 网络分析", "description": "离线网络配置解析、接口/路由提取和配置翻译"},
    "web": {"name": "Web 外部资料", "description": "公开 Web、官方文档、新闻、天气和网页摘要"},
    "runtime": {"name": "Runtime 运行审计", "description": "运行状态、session、run、review 和审计信息"},
    "memory": {"name": "Memory 记忆", "description": "记忆搜索、创建、确认、profile 和更新"},
    "report_data": {"name": "Report/Data/Text 输出处理", "description": "报告、表格、文本、JSON/YAML/CSV 和图表处理"},
    "agent": {"name": "Agent 多 Agent", "description": "技能、子 Agent、角色、团队和结果读取"},
}


TOOL_NAMESPACE: dict[str, ToolNamespaceEntry] = {
    row[0]: ToolNamespaceEntry(
        canonical_tool_id=row[0],
        execution_tool_id=row[1],
        legacy_tool_ids=tuple(row[2]),
        category=row[3],
        group=row[4],
        action=row[5],
        display_name=row[6],
        short_label=row[7],
        usage_hint=row[8],
        not_for=row[9],
    )
    for row in NS_DATA
}

EXECUTION_TO_CANONICAL: dict[str, str] = {
    entry.execution_tool_id: entry.canonical_tool_id
    for entry in TOOL_NAMESPACE.values()
}

CANONICAL_TO_EXECUTION: dict[str, str] = {
    entry.canonical_tool_id: entry.execution_tool_id
    for entry in TOOL_NAMESPACE.values()
}

LEGACY_TO_CANONICAL: dict[str, str] = {}
LEGACY_TO_EXECUTION: dict[str, str] = {}
for entry in TOOL_NAMESPACE.values():
    for alias in entry.legacy_tool_ids:
        LEGACY_TO_CANONICAL.setdefault(alias, entry.canonical_tool_id)
        LEGACY_TO_EXECUTION.setdefault(alias, entry.execution_tool_id)

CANONICAL_TO_LEGACY: dict[str, list[str]] = {
    entry.canonical_tool_id: list(entry.legacy_tool_ids)
    for entry in TOOL_NAMESPACE.values()
}


def canonical_tool_ids() -> list[str]:
    return sorted(TOOL_NAMESPACE)


def execution_tool_ids() -> list[str]:
    return sorted(EXECUTION_TO_CANONICAL)


def legacy_aliases() -> list[str]:
    return sorted(LEGACY_TO_CANONICAL)


def get_namespace_entry(tool_id: str) -> ToolNamespaceEntry:
    canonical = get_canonical_tool_id(tool_id)
    entry = TOOL_NAMESPACE.get(canonical)
    if entry is None:
        raise KeyError(f"unknown tool namespace id: {tool_id}")
    return entry


def get_canonical_tool_id(tool_id: str) -> str:
    if tool_id in TOOL_NAMESPACE:
        return tool_id
    if tool_id in EXECUTION_TO_CANONICAL:
        return EXECUTION_TO_CANONICAL[tool_id]
    if tool_id in LEGACY_TO_CANONICAL:
        return LEGACY_TO_CANONICAL[tool_id]
    return tool_id


def get_execution_tool_id(tool_id: str) -> str:
    if tool_id in CANONICAL_TO_EXECUTION:
        return CANONICAL_TO_EXECUTION[tool_id]
    if tool_id in LEGACY_TO_EXECUTION:
        return LEGACY_TO_EXECUTION[tool_id]
    if tool_id in EXECUTION_TO_CANONICAL:
        return tool_id
    return tool_id


def resolve_tool_id(tool_id: str) -> str:
    return get_execution_tool_id(tool_id)


def metadata_for_tool(tool_id: str) -> dict[str, Any]:
    try:
        meta = get_namespace_entry(tool_id).metadata()
    except KeyError:
        meta = {
            "canonical_tool_id": tool_id,
            "execution_tool_id": tool_id,
            "legacy_tool_ids": [tool_id],
            "category": tool_id.split(".", 1)[0] if "." in tool_id else "runtime",
            "group": "misc",
            "action": "use",
            "display_name": tool_id,
            "short_label": tool_id,
            "usage_hint": f"Use {tool_id} when specifically needed.",
            "not_for": "Do not use outside its documented safety boundary.",
        }
    try:
        from tool_runtime.tool_governance import governance_metadata
        meta.update(governance_metadata(meta["canonical_tool_id"]))
    except Exception:
        pass
    return meta


def enrich_spec(spec):
    """Attach namespace metadata to either ToolSpec dataclass variant."""
    base = dict(getattr(spec, "metadata", {}) or {})
    base.update(metadata_for_tool(getattr(spec, "tool_id", "")))
    spec.metadata = base
    return spec


def category_tree_from_specs(specs: list) -> list[dict[str, Any]]:
    by_category: dict[str, dict[str, Any]] = {}
    for spec in specs:
        meta = metadata_for_tool(getattr(spec, "tool_id", ""))
        category_id = meta["category"]
        group_id = meta["group"]
        cat = by_category.setdefault(category_id, {
            "id": category_id,
            "name": CATEGORY_DEFS.get(category_id, {}).get("name", category_id),
            "description": CATEGORY_DEFS.get(category_id, {}).get("description", ""),
            "count": 0,
            "groups": {},
        })
        group = cat["groups"].setdefault(group_id, {
            "id": group_id,
            "name": group_id.replace("_", " ").title(),
            "count": 0,
            "tools": [],
        })
        tool = {
            **meta,
            "tool_id": getattr(spec, "tool_id", ""),
            "canonical_tool_id": meta["canonical_tool_id"],
            "execution_tool_id": meta["execution_tool_id"],
            "legacy_tool_ids": meta["legacy_tool_ids"],
            "risk_level": getattr(spec, "risk_level", "low"),
            "requires_approval": bool(getattr(spec, "requires_approval", False)),
            "permission_action": getattr(spec, "permission_action", ""),
            "enabled": bool(getattr(spec, "enabled", True)),
            "callable_by_llm": bool(getattr(spec, "callable_by_llm", True)),
            "description": getattr(spec, "description", ""),
        }
        group["tools"].append(tool)
        group["count"] += 1
        cat["count"] += 1

    categories = []
    for category_id in sorted(by_category):
        cat = by_category[category_id]
        groups = []
        for group_id in sorted(cat["groups"]):
            group = cat["groups"][group_id]
            group["tools"].sort(key=lambda t: t["canonical_tool_id"])
            groups.append(group)
        cat["groups"] = groups
        categories.append(cat)
    return categories
