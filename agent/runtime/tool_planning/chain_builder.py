# agent/runtime/tool_planning/chain_builder.py
"""Chain builder — builds tool_chain from SceneDecision signals.

Also contains deterministic chain helpers migrated from tool_planner.py:
- _SIGNAL_DISPATCH table
- tool_chain_from_plan
- categories_groups_from_tools
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from core.tools.tool_namespace import get_namespace_entry


@lru_cache(maxsize=128)
def _cached_namespace_entry(tool_id: str):
    try:
        return get_namespace_entry(tool_id)
    except Exception:
        return None


# ─── Signal dispatch table ─────────────────────────────────────────────

# Map signal keywords to (capability_action_id, goal_template)
SIGNAL_DISPATCH = [
    # v3.9.3: capability_actions module removed. The third tuple element
    # used to be a high-level capability_action; it is now a canonical
    # tool_id directly. tools_for_action() inlines the 1:1 mapping.
    (("has_uploaded_files", "mentions_file"), "workspace.file", "读取上传或 workspace 中的文本文件"),
    (("has_uploaded_files", "mentions_image"), "workspace.file", "读取上传图片的尺寸/格式元数据"),
    (("mentions_web",), "web.manage", "检索官方文档或外部资料"),
    (("mentions_weather",), "web.manage", "查询天气信息"),
    (("mentions_knowledge",), "knowledge.manage", "检索知识库并基于安全摘录回答"),
    (("mentions_config_translate",), "config.manage", "离线翻译网络配置"),
    (("mentions_packet",), "pcap.manage", "离线分析 PCAP 报文、连接和 TCP 序列"),
    (("mentions_network_config",), "config.manage", "离线分析网络配置"),
    (("mentions_report",), "report.manage", "生成报告并保存制品"),
    (("mentions_host",), "exec.run", "查询或操作当前本机环境"),
    (("mentions_runtime",), "system.manage", "查看运行、trace、session 或审计信息"),
    (("mentions_memory",), "memory.manage", "搜索或维护记忆/profile"),
    (("mentions_sub_agent",), "spawn_network_diag_agent", "派生网络诊断子代理并行处理复杂网络任务"),
]


# ─── Deterministic chain helpers ───────────────────────────────────────


def tool_chain_from_plan(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": step.get("step"),
            "purpose": step.get("goal", ""),
            "preferred_tools": list(step.get("tool_candidates") or []),
        }
        for step in steps
    ]


def categories_groups_from_tools(
    candidate_tools: list[str], rule_scene: dict,
) -> tuple[list[str], dict[str, list[str]]]:
    """Build categories and groups from candidate tools using cached lookups."""
    categories: list[str] = []
    groups: dict[str, list[str]] = {}
    for tool_id in candidate_tools:
        entry = _cached_namespace_entry(tool_id)
        if entry is None:
            continue
        if entry.category not in categories:
            categories.append(entry.category)
        groups.setdefault(entry.category, [])
        if entry.group not in groups[entry.category]:
            groups[entry.category].append(entry.group)
    for category in rule_scene.get("categories") or []:
        if category in groups and category not in categories:
            categories.append(category)
    return categories, groups


# ─── Signal-based chain builder ────────────────────────────────────────


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
            "workspace.file", "workspace.file",
            "workspace.file", "workspace.file",
        ])

    if signals.get("mentions_image"):
        add("读取上传图片的尺寸和格式信息", [
            "workspace.file", "workspace.file",
        ])

    if signals.get("mentions_web"):
        add("检索官方文档或外部资料", [
            "web.manage", "web.manage",
        ])

    if signals.get("mentions_weather"):
        add("查询天气信息", [
            "web.manage", "web.manage",
        ])

    if signals.get("mentions_knowledge"):
        add("查询知识库资料", [
            "knowledge.manage", "knowledge.manage",
        ])

    if signals.get("mentions_network_config"):
        add("读取配置文件内容", [
            "workspace.file", "workspace.file", "workspace.file",
        ])
        add("离线分析网络配置", ["config.manage"])

    if signals.get("mentions_config_translate"):
        add("读取待翻译配置文件内容", [
            "workspace.file", "workspace.file", "workspace.file",
        ])
        add("离线翻译网络配置", ["config.manage"])

    if signals.get("mentions_packet"):
        add("读取 PCAP 报文文件", [
            "workspace.file", "workspace.file",
        ])
        add("离线分析 PCAP 报文、连接和 TCP 序列", ["pcap.manage"])

    if signals.get("mentions_host"):
        add("查询或操作当前本机环境", [
            "exec.run", "exec.run",
            "system.manage",
        ])

    if signals.get("mentions_runtime"):
        add("读取运行审计、run 或 session 信息", [
            "system.manage", "system.manage",
            "system.manage", "system.manage",
        ])

    if signals.get("mentions_memory"):
        add("查询或更新记忆/profile", [
            "memory.manage",
        ])

    if signals.get("mentions_report"):
        add("输出分析报告并保存制品", [
            "report.manage", "workspace.artifact",
        ])

    if signals.get("mentions_sub_agent"):
        add("派生子代理并行处理复杂任务", [
            "agent.manage", "agent.manage", "agent.manage",
        ])

    if not steps:
        sorted_candidates = sorted(candidates, key=lambda tid: tid)[:5]
        add("执行当前场景的首选工具", sorted_candidates)

    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps
