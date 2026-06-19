# agent/runtime/tool_planning/chain_builder.py
"""Chain builder — builds tool_chain from SceneDecision signals.

Extracted from tool_category_router.py::_build_tool_chain.
"""

from __future__ import annotations

from typing import Any


def build_tool_chain(signals: dict[str, bool], candidates: set[str]) -> list[dict[str, Any]]:
    """Build an ordered tool chain from signals and available candidates."""
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
            "workspace.file.read", "workspace.file.read_image",
            "workspace.file.preview", "workspace.file.list",
        ])

    if signals.get("mentions_image"):
        add("读取上传图片的尺寸和格式信息", [
            "workspace.file.read_image", "workspace.file.list",
        ])

    if signals.get("mentions_web"):
        add("检索官方文档或外部资料", [
            "web.docs.official_search", "web.search", "web.page.summarize",
        ])

    if signals.get("mentions_weather"):
        add("查询天气信息", [
            "web.weather.current", "web.weather.forecast",
        ])

    if signals.get("mentions_knowledge"):
        add("查询知识库资料", [
            "knowledge.search", "knowledge.chunk.read",
        ])

    if signals.get("mentions_network_config"):
        add("读取配置文件内容", [
            "workspace.file.read", "workspace.file.list", "workspace.file.preview",
        ])
        add("离线解析网络配置", ["network.config.parse"])
        add("提取接口与路由信息", [
            "network.interface.extract", "network.route.extract",
        ])

    if signals.get("mentions_config_translate"):
        add("读取待翻译配置文件内容", [
            "workspace.file.read", "workspace.file.list", "workspace.file.preview",
        ])
        add("离线翻译网络配置", ["network.config.translate"])

    if signals.get("mentions_packet"):
        add("读取并解析 PCAP 报文文件", [
            "workspace.file.read", "workspace.file.list", "network.pcap.parse",
        ])
        add("查看报文连接与流量分组", [
            "network.pcap.session", "network.pcap.filter",
        ])
        add("分析 TCP 序列、重传、乱序和 gap", ["network.pcap.align"])

    if signals.get("mentions_host"):
        add("查询或操作当前本机环境", [
            "host.shell.exec", "host.powershell.exec", "host.python.exec",
            "runtime.health", "runtime.diagnostics",
        ])

    if signals.get("mentions_runtime"):
        add("读取运行审计、run 或 session 信息", [
            "run.summary.get", "run.list",
            "runtime.diagnostics", "session.summary.get",
        ])

    if signals.get("mentions_memory"):
        add("查询或更新记忆/profile", [
            "memory.search", "memory.profile.get", "memory.profile.set",
        ])

    if signals.get("mentions_report"):
        add("输出分析报告并保存制品", [
            "report.markdown.render", "workspace.artifact.save",
        ])

    if signals.get("mentions_sub_agent"):
        add("派生子代理并行处理复杂任务", [
            "agent.spawn", "agent.role.list", "agent.result.get",
        ])

    if not steps:
        sorted_candidates = sorted(candidates, key=lambda tid: tid)[:5]
        add("执行当前场景的首选工具", sorted_candidates)

    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps
