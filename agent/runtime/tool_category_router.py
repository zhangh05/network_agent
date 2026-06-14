"""Rule-based v2.2 tool category router.

This router is intentionally lightweight: it narrows the visible tool
catalog before the LLM sees function definitions, while the execution
layer still resolves canonical ids to the stable 88 execution ids.
"""

from __future__ import annotations

from typing import Any

from tool_runtime.tool_namespace import TOOL_NAMESPACE


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(n.lower() in lower for n in needles)


def _candidate_tools(category: str, group: str | None = None) -> list[str]:
    tools = [
        entry.canonical_tool_id
        for entry in TOOL_NAMESPACE.values()
        if entry.category == category and (group is None or entry.group == group)
    ]
    return sorted(tools)


def route_tool_scene(
    user_input: str,
    session_context: dict[str, Any] | None = None,
    available_categories: list[str] | None = None,
    uploaded_files: list[Any] | None = None,
    workspace_state: dict[str, Any] | None = None,
    memory_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a category/group/tool shortlist for the current user request."""
    text = user_input or ""
    available = set(available_categories or [])

    def choose(category: str, group: str, reason: str) -> dict[str, Any]:
        if available and category not in available:
            category = sorted(available)[0]
            group = "general"
        return {
            "category": category,
            "group": group,
            "candidate_tools": _candidate_tools(category, None if group == "general" else group),
            "reason": reason,
        }

    if _contains(text, ("本机", "localhost", "127.0.0.1", "端口", "进程", "process", "shell", "powershell", "python", "os ")):
        return choose("host", "shell", "用户请求查看或操作当前运行机器")

    if uploaded_files or _contains(text, ("workspace", "工作区", "文件", "日志", "上传", "读取", "read file", "path")):
        return choose("workspace", "file", "用户请求读取或管理工作区文件")

    if _contains(text, ("知识库", "knowledge", "rag", "资料库", "source", "chunk")):
        return choose("knowledge", "query", "用户请求查询本地知识库")

    if _contains(text, ("cisco", "huawei", "juniper", "配置", "接口", "路由", "ospf", "bgp", "acl", "vlan", "network config")):
        return choose("network", "config", "用户请求离线分析网络设备配置或网络文本")

    if _contains(text, ("官方文档", "最新", "网页", "网址", "url", "http", "news", "新闻", "weather", "天气")):
        group = "docs" if _contains(text, ("官方文档", "docs", "documentation")) else "search"
        return choose("web", group, "用户请求外部资料或最新公开信息")

    if _contains(text, ("记住", "记忆", "偏好", "remember", "preference", "profile")) or memory_hints:
        return choose("memory", "profile" if _contains(text, ("profile", "偏好")) else "memory", "用户请求使用或更新记忆")

    if _contains(text, ("trace", "run", "session", "运行", "审计", "timeline", "checkpoint")):
        return choose("runtime", "run" if _contains(text, ("run", "trace")) else "session", "用户请求运行、会话或审计信息")

    if _contains(text, ("报告", "表格", "diagram", "markdown", "json", "yaml", "csv", "diff", "脱敏")):
        return choose("report_data", "report", "用户请求生成或处理结构化输出")

    if session_context or workspace_state:
        return choose("workspace", "file", "上下文指向工作区操作")

    return choose("web", "search", "默认使用低风险检索能力")
