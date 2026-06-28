"""Rule-based v3.9.2 multi-category tool-chain router (22-tool Codex-style set).

The router narrows the LLM-visible catalog using canonical namespace ids.
All 22 tools are LLM-visible; routing here still surfaces scene-relevant
groups first via ``_CHAIN_ORDER`` and ``_build_tool_chain``.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.scene_decision import _mentions_sub_agent
from tool_runtime.tool_namespace import TOOL_NAMESPACE


# v3.9.2: order merged-tools first; lower = higher priority.
_CHAIN_ORDER = {
    "workspace.file": 10,
    "workspace.artifact": 12,
    "web.manage": 20,
    "config.manage": 30,
    "pcap.manage": 34,
    "knowledge.manage": 41,
    "exec.run": 50,
    "system.manage": 60,
    "memory.manage": 70,
    "report.manage": 80,
    "data.manage": 81,
    "text.analyze": 82,
    "git.manage": 90,
    "device.manage": 95,
    "browser.manage": 96,
    "code.search": 98,
    "agent.manage": 100,
    "skill.manage": 110,
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

    mentions_file = _contains(text, ("上传", "文件", "workspace", "工作区", "日志", "读取", "路径", "config file", "pcap", "pcapng", "报文", "抓包", "pdf"))
    mentions_file_implicit = (
        _contains(text, ("这个配置", "这份配置", "这个文件", "这份文件", "上面的配置", "之前的配置",
                         "那个配置", "那份配置", "刚才的配置", "已上传", "已导入",
                         "这个日志", "这份日志", "上面的日志", "帮我看", "帮我分析",
                         "看看这个", "看看这份", "看一下", "检查一下"))
    )
    mentions_image = _contains(text, ("图片", "图像", "截图", "照片", ".png", ".jpg", ".jpeg", ".gif", ".webp", "image.png", "image.jpg", "screenshot", "文件引用"))
    mentions_network_specific = _contains(text, ("华三", "h3c", "cisco", "huawei", "juniper", "接口", "路由", "ospf", "bgp", "acl", "vlan", "nat", "防火墙", "network config", "running-config"))
    mentions_network_analysis = _contains(text, ("分析", "检查", "有没有问题", "解析", "提取", "看看", "帮我看", "审查", "review", "analyze"))
    mentions_config_translate = _contains(text, ("翻译", "转换", "转成", "转为", "改成", "translate", "convert")) and _contains(text, ("配置", "config", "华三", "h3c", "cisco", "huawei", "juniper", "思科"))
    mentions_packet = _contains(text, ("pcap", "pcapng", "报文", "抓包", "数据包", "五元组", "tcp流", "tcp 流", "seq", "ack", "重传", "乱序", "丢包", "sequence gap", "wireshark"))
    mentions_knowledge = _contains(text, ("知识库", "knowledge", "rag", "资料库", "source", "chunk", "之前导入", "内部资料",
                                           "资料", "文档", "本地有", "有没有相关", "文件里", "导入的"))
    mentions_search = _contains(text, ("查一下", "搜索一下", "找找", "看看有没有", "有没有什么", "搜索", "检索"))
    mentions_host = _contains(text, ("本机", "localhost", "127.0.0.1", "ipconfig", "ifconfig", "route print",
                                     "netstat", "端口", "进程", "process", "shell", "powershell", "python", "os ",
                                     "ping", "traceroute", "nslookup", "dig", "curl", "wget", "system info",
                                     "系统信息", "系统状态", "磁盘", "内存", "cpu", "执行命令", "跑命令", "运行命令", "命令行", "终端"))
    mentions_computation = _contains(text, ("python", "计算", "算一下", "统计", "95 分位", "95分位", "percentile", "脚本", "数据处理"))
    is_definition_question = _contains(text, ("是什么", "什么是", "介绍", "解释", "说明", "what is", "define"))

    effective_mentions_file = mentions_file or mentions_file_implicit or bool(uploaded_files)

    signals = {
        "has_uploaded_files": bool(uploaded_files),
        "mentions_file": effective_mentions_file,
        "mentions_image": mentions_image,
        "mentions_network_config": (not mentions_config_translate) and (not mentions_knowledge) and (not mentions_computation) and ((mentions_network_specific and mentions_network_analysis) or ("配置" in lower and mentions_network_analysis and not lower.startswith("读取 workspace"))) and not is_definition_question,
        "mentions_config_translate": mentions_config_translate and not is_definition_question,
        "mentions_packet": mentions_packet,
        "mentions_report": _contains(text, ("报告", "整理", "输出", "markdown", "表格", "导出", "保存", "制品", "artifact")),
        "mentions_web": _contains(text, ("官方文档", "最新", "网页", "url", "http", "厂商文档", "手册", "docs", "documentation",
                                                                       "搜索引擎", "网上", "互联网", "上网", "查查",
                                                                       "新闻", "资讯", "最近发生", "热点")) or (mentions_search and not mentions_knowledge),
        "mentions_weather": _contains(text, ("天气", "weather", "气温", "温度", "降雨", "下雨", "湿度", "风力", "台风", "晴", "阴", "多云",
                                               "紫外线", "空气质量", "aqi", "预报", "forecast")),
        "mentions_knowledge": mentions_knowledge,
        "mentions_search": mentions_search,
        "mentions_host": mentions_host,
        "mentions_runtime": _contains(text, ("trace", "run", "session", "运行详情", "审计", "timeline", "checkpoint")),
        "mentions_memory": _contains(text, ("记住", "偏好", "profile", "remember", "memory", "记忆")) or bool(memory_hints),
        "mentions_sub_agent": _mentions_sub_agent(text),
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
        # v3.9.2: exec.run now has action=shell|python|slash; surface the merged tool
        # instead of separate exec.run / exec.run / exec.python.
        include("exec", "shell")
        include("system", "health")
        reasons.append("用户明确请求查看或操作当前本机环境")

    if signals["has_uploaded_files"] or signals["mentions_file"]:
        include("workspace", "file")
        reasons.append("用户涉及上传文件或 workspace 文件")

    if signals["mentions_network_config"] and not signals["mentions_knowledge"]:
        include("config", "config_analysis")
        include("workspace", "file")
        reasons.append("用户请求离线网络配置分析")

    if signals["mentions_config_translate"] and not signals["mentions_knowledge"]:
        include("config", "config_analysis")
        include("workspace", "file")
        reasons.append("用户请求离线网络配置翻译")

    if signals["mentions_packet"] and not signals["mentions_knowledge"]:
        include("pcap", "pcap_analysis")
        include("workspace", "file")
        reasons.append("用户请求离线报文/PCAP 分析")

    if signals["mentions_web"]:
        include("web", "web_search")
        reasons.append("用户请求官方文档或外部资料")

    if signals["mentions_weather"]:
        include("web", "web_search")
        reasons.append("用户请求天气信息")

    if signals["mentions_knowledge"]:
        include("knowledge", "kb")
        reasons.append("用户请求知识库资料")

    if signals["mentions_runtime"]:
        include("system", "health")
        reasons.append("用户请求运行审计或 session/run 信息")

    if signals["mentions_memory"]:
        include("memory", "record")
        reasons.append("用户请求记忆或 profile")

    if signals["mentions_report"]:
        include("data", "report")
        include("workspace", "artifact")
        reasons.append("用户请求整理输出、报告或保存制品")

    if signals["mentions_sub_agent"]:
        include("agent", "subagent")
        reasons.append("用户请求复杂/并行/委托式任务")

    if not categories and workspace_state:
        include("workspace", "file")
        reasons.append("上下文指向 workspace 操作")

    if not categories:
        include("web", "web_search")
        reasons.append("默认使用低风险检索能力")

    primary_category = _primary_category(signals, categories)
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
    }


def _primary_category(signals: dict[str, bool], categories: list[str]) -> str:
    if signals.get("mentions_knowledge") and "knowledge" in categories:
        return "knowledge"
    if (signals.get("mentions_packet") or signals.get("mentions_config_translate")) and "config" in categories:
        return "config"
    if signals.get("mentions_network_config") and "config" in categories:
        return "config"
    if signals.get("mentions_host") and "exec" in categories:
        return "exec"
    if signals.get("mentions_runtime") and "system" in categories:
        return "system"
    if signals.get("mentions_memory") and "memory" in categories:
        return "memory"
    if signals.get("mentions_report") and "data" in categories:
        return "data"
    return categories[0] if categories else "web"


def _primary_group(primary_category: str, groups: dict[str, list[str]]) -> str:
    preferred = {
        "exec": "shell",
        "workspace": "file",
        "config": "config_analysis",
        "pcap": "pcap_analysis",
        "web": "web_search",
        "knowledge": "kb",
        "system": "health",
        "memory": "record",
        "data": "report",
        "agent": "subagent",
    }
    group_ids = groups.get(primary_category, [])
    pref = preferred.get(primary_category)
    if pref in group_ids:
        return pref
    return group_ids[0] if group_ids else "general"


def _build_tool_chain(signals: dict[str, bool], candidates: set[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(purpose: str, tools: list[str]) -> None:
        # De-dupe while keeping order
        seen: set[str] = set()
        unique = []
        for tid in tools:
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
        preferred = [tid for tid in unique if tid in candidates]
        if preferred:
            steps.append({
                "step": len(steps) + 1,
                "purpose": purpose,
                "preferred_tools": preferred,
            })

    if signals.get("has_uploaded_files") or signals.get("mentions_file"):
        add("读取用户上传或 workspace 中的文件", [
            "workspace.file",
        ])

    if signals.get("mentions_image"):
        add("读取上传图片的尺寸和格式信息", [
            "workspace.file",
        ])

    if signals.get("mentions_web"):
        add("检索官方文档或外部资料", [
            "web.manage",
        ])

    if signals.get("mentions_weather"):
        add("查询天气信息", [
            "web.manage",
        ])

    if signals.get("mentions_knowledge"):
        add("查询知识库资料", [
            "knowledge.manage",
        ])

    if signals.get("mentions_network_config"):
        add("读取配置文件内容", [
            "workspace.file",
        ])
        add("离线分析网络配置", ["config.manage"])

    if signals.get("mentions_config_translate"):
        add("读取待翻译配置文件内容", [
            "workspace.file",
        ])
        add("离线翻译网络配置", ["config.manage"])

    if signals.get("mentions_packet"):
        add("读取 PCAP 报文文件", [
            "workspace.file",
        ])
        add("离线分析 PCAP 报文、连接和 TCP 序列", ["pcap.manage"])

    if signals.get("mentions_host"):
        add("查询或操作当前本机环境", [
            "exec.run",
            "system.manage",
        ])

    if signals.get("mentions_runtime"):
        add("读取运行审计、run 或 session 信息", [
            "system.manage",
        ])

    if signals.get("mentions_memory"):
        add("查询或更新记忆/profile", [
            "memory.manage",
        ])

    if signals.get("mentions_report"):
        add("输出分析报告并保存制品", [
            "report.manage",
            "workspace.artifact",
        ])

    if signals.get("mentions_sub_agent"):
        add("派生子代理并行处理复杂任务", [
            "agent.manage",
        ])

    if not steps:
        add("执行当前场景的首选工具", _sort_candidates(candidates)[:5])

    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps
