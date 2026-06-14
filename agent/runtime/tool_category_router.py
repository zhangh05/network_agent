"""Rule-based v2.2.1 multi-category tool-chain router.

The router narrows the LLM-visible catalog using canonical namespace ids.
It can return several categories/groups for multi-step work, while the
execution layer still resolves canonical ids to the stable 88 execution ids.
"""

from __future__ import annotations

from typing import Any

from tool_runtime.tool_namespace import TOOL_NAMESPACE


_CHAIN_ORDER = {
    "workspace.file.read": 10,
    "workspace.file.preview": 11,
    "workspace.file.list": 12,
    "workspace.file.exists": 13,
    "web.docs.official_search": 20,
    "web.search": 21,
    "web.page.summarize": 22,
    "web.page.extract_links": 23,
    "network.config.parse": 30,
    "network.interface.extract": 31,
    "network.route.extract": 32,
    "network.config.translate": 33,
    "knowledge.query": 40,
    "knowledge.search": 41,
    "knowledge.chunk.read": 42,
    "knowledge.source.read": 43,
    "host.shell.exec": 50,
    "host.powershell.exec": 51,
    "host.python.exec": 52,
    "runtime.health": 60,
    "runtime.diagnostics": 61,
    "run.list": 62,
    "run.summary.get": 63,
    "session.list": 64,
    "session.summary.get": 65,
    "memory.search": 70,
    "memory.profile.get": 71,
    "memory.profile.set": 72,
    "report.markdown.render": 80,
    "data.table.render": 81,
    "diagram.mermaid.render": 82,
    "workspace.artifact.save": 90,
    "workspace.artifact.search": 91,
}


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(n.lower() in lower for n in needles)


def _canonical_exists(tool_id: str) -> bool:
    return tool_id in TOOL_NAMESPACE


def _tools_for_group(category: str, group: str) -> list[str]:
    return sorted(
        entry.canonical_tool_id
        for entry in TOOL_NAMESPACE.values()
        if entry.category == category and entry.group == group
    )


def _candidate_tools_for_groups(groups: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    found: set[str] = set()
    for category, group_ids in groups.items():
        for group in group_ids:
            group_tools = _tools_for_group(category, group)
            if not group_tools:
                warnings.append(f"no_tools_for_group:{category}.{group}")
            found.update(group_tools)
    return _sort_candidates(found), warnings


def _sort_candidates(tool_ids: set[str] | list[str]) -> list[str]:
    return sorted(set(tool_ids), key=lambda tid: (_CHAIN_ORDER.get(tid, 500), tid))


def _select_preferred(*tool_ids: str, candidates: set[str]) -> list[str]:
    return [tid for tid in tool_ids if tid in candidates and _canonical_exists(tid)]


def _add_group(groups: dict[str, list[str]], category: str, group: str) -> None:
    groups.setdefault(category, [])
    if group not in groups[category]:
        groups[category].append(group)


def _add_category(categories: list[str], category: str) -> None:
    if category not in categories:
        categories.append(category)


def route_tool_scene(
    user_input: str,
    session_context: dict[str, Any] | None = None,
    available_categories: list[str] | None = None,
    uploaded_files: list[Any] | None = None,
    workspace_state: dict[str, Any] | None = None,
    memory_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return multi-category tool routing metadata for a user request."""
    text = user_input or ""
    available = set(available_categories or [])
    lower = text.lower()
    session_context = session_context or {}

    mentions_file = _contains(text, ("上传", "文件", "workspace", "工作区", "日志", "读取", "路径", "config file", "pcap", "pdf"))
    mentions_network_specific = _contains(text, ("华三", "h3c", "cisco", "huawei", "juniper", "接口", "路由", "ospf", "bgp", "acl", "vlan", "nat", "防火墙", "network config", "running-config"))
    mentions_network_analysis = _contains(text, ("分析", "检查", "有没有问题", "解析", "提取"))

    signals = {
        "has_uploaded_files": bool(uploaded_files),
        "mentions_file": mentions_file,
        "mentions_network_config": mentions_network_specific or ("配置" in lower and mentions_network_analysis and not lower.startswith("读取 workspace")),
        "mentions_report": _contains(text, ("报告", "整理", "输出", "markdown", "表格", "导出", "保存", "制品", "artifact")),
        "mentions_web": _contains(text, ("官方文档", "最新", "网页", "url", "http", "厂商文档", "手册", "docs", "documentation")),
        "mentions_knowledge": _contains(text, ("知识库", "knowledge", "rag", "资料库", "source", "chunk", "之前导入", "内部资料")),
        "mentions_host": _contains(text, ("本机", "localhost", "127.0.0.1", "ipconfig", "ifconfig", "route print", "netstat", "端口", "进程", "process", "shell", "powershell", "python", "os ")),
        "mentions_runtime": _contains(text, ("trace", "run", "session", "运行详情", "审计", "timeline", "checkpoint")),
        "mentions_memory": _contains(text, ("记住", "偏好", "profile", "remember", "memory", "记忆")) or bool(memory_hints),
    }

    categories: list[str] = []
    groups: dict[str, list[str]] = {}
    reasons: list[str] = []

    def include(category: str, *group_ids: str) -> None:
        if available and category not in available:
            return
        _add_category(categories, category)
        for group_id in group_ids:
            _add_group(groups, category, group_id)

    if signals["mentions_host"]:
        include("host", "shell", "powershell", "python")
        include("runtime", "health")
        reasons.append("用户请求查看或操作当前本机环境")

    if signals["has_uploaded_files"] or signals["mentions_file"]:
        include("workspace", "file")
        reasons.append("用户涉及上传文件或 workspace 文件")

    if signals["mentions_network_config"]:
        include("network", "config", "interface", "route")
        if signals["has_uploaded_files"] or signals["mentions_file"] or "上传" in text:
            include("workspace", "file")
        reasons.append("用户请求离线网络配置分析")

    if signals["mentions_web"]:
        include("web", "docs", "search", "page")
        reasons.append("用户请求官方文档或外部资料")

    if signals["mentions_knowledge"]:
        include("knowledge", "query", "search", "chunk", "source")
        reasons.append("用户请求知识库资料")

    if signals["mentions_runtime"]:
        include("runtime", "run", "session", "diagnostics")
        reasons.append("用户请求运行审计或 session/run 信息")

    if signals["mentions_memory"]:
        include("memory", "memory", "profile")
        reasons.append("用户请求记忆或 profile")

    if signals["mentions_report"]:
        include("report_data", "report", "table", "diagram")
        include("workspace", "artifact")
        reasons.append("用户请求整理输出、报告或保存制品")

    if not categories and (session_context or workspace_state):
        include("workspace", "file")
        reasons.append("上下文指向 workspace 操作")

    if not categories:
        include("web", "search")
        reasons.append("默认使用低风险检索能力")

    primary_category = _primary_category(signals, categories)
    primary_group = _primary_group(primary_category, groups)
    candidates, warnings = _candidate_tools_for_groups(groups)
    candidate_set = set(candidates)
    tool_chain = _build_tool_chain(signals, candidate_set)

    return {
        "primary_category": primary_category,
        "categories": categories,
        "groups": groups,
        "candidate_tools": candidates,
        "tool_chain": tool_chain,
        "reason": "；".join(reasons) if reasons else "根据用户输入选择工具链",
        "warnings": warnings,
        "signals": signals,
        # Backward-compatible fields.
        "category": primary_category,
        "group": primary_group,
    }


def _primary_category(signals: dict[str, bool], categories: list[str]) -> str:
    if signals.get("mentions_knowledge") and "knowledge" in categories:
        return "knowledge"
    if signals.get("mentions_network_config") and "network" in categories:
        return "network"
    if signals.get("mentions_host") and "host" in categories:
        return "host"
    if signals.get("mentions_runtime") and "runtime" in categories:
        return "runtime"
    if signals.get("mentions_memory") and "memory" in categories:
        return "memory"
    if signals.get("mentions_report") and "report_data" in categories:
        return "report_data"
    return categories[0] if categories else "web"


def _primary_group(primary_category: str, groups: dict[str, list[str]]) -> str:
    preferred = {
        "host": "shell",
        "workspace": "file",
        "network": "config",
        "web": "docs",
        "knowledge": "query",
        "runtime": "run",
        "memory": "profile",
        "report_data": "report",
        "agent": "agent",
    }
    group_ids = groups.get(primary_category, [])
    pref = preferred.get(primary_category)
    if pref in group_ids:
        return pref
    return group_ids[0] if group_ids else "general"


def _build_tool_chain(signals: dict[str, bool], candidates: set[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(purpose: str, tools: list[str]) -> None:
        preferred = [tid for tid in tools if tid in candidates]
        if preferred:
            steps.append({
                "step": len(steps) + 1,
                "purpose": purpose,
                "preferred_tools": preferred,
            })

    if signals.get("has_uploaded_files") or signals.get("mentions_file"):
        add("读取用户上传或 workspace 中的文件", [
            "workspace.file.read",
            "workspace.file.preview",
            "workspace.file.list",
        ])

    if signals.get("mentions_web"):
        add("检索官方文档或外部资料", [
            "web.docs.official_search",
            "web.search",
            "web.page.summarize",
        ])

    if signals.get("mentions_network_config"):
        add("离线解析网络配置", ["network.config.parse"])
        add("提取接口与路由信息", [
            "network.interface.extract",
            "network.route.extract",
        ])

    if signals.get("mentions_knowledge"):
        add("查询知识库资料", [
            "knowledge.query",
            "knowledge.search",
            "knowledge.chunk.read",
        ])

    if signals.get("mentions_host"):
        add("查询或操作当前本机环境", [
            "host.shell.exec",
            "host.powershell.exec",
            "host.python.exec",
            "runtime.health",
            "runtime.diagnostics",
        ])

    if signals.get("mentions_runtime"):
        add("读取运行审计、run 或 session 信息", [
            "run.summary.get",
            "run.list",
            "runtime.diagnostics",
            "session.summary.get",
        ])

    if signals.get("mentions_memory"):
        add("查询或更新记忆/profile", [
            "memory.search",
            "memory.profile.get",
            "memory.profile.set",
        ])

    if signals.get("mentions_report"):
        add("输出分析报告并保存制品", [
            "report.markdown.render",
            "workspace.artifact.save",
        ])

    if not steps:
        add("执行当前场景的首选工具", _sort_candidates(candidates)[:5])

    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps
