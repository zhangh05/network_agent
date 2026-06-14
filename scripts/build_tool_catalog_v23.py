#!/usr/bin/env python3
"""Generate v2.3 tool catalog artifacts (JSON + Markdown mirror).

Data sources (read-only, in priority order):
  1. tool_runtime.tool_namespace / TOOL_NAMESPACE (88 canonical)
  2. tool_runtime.tool_governance / TOOL_GOVERNANCE (per-canonical governance)
  3. tool_runtime.capability_actions / CAPABILITY_ACTIONS (planner action plans)
  4. tool_runtime.tool_governance.governance_summary() (status counts)
  5. agent.runtime.services.default_runtime_services() (risk_level /
     requires_approval / description / overlap_group cross-check)

Outputs:
  reports/tool_catalog_v23.json     machine-readable catalog
  reports/TOOL_CATALOG_V2.3.md      mirror of docs/TOOL_CATALOG_V2.3.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"


CATEGORY_ZH = {
    "host": ("Host 本机环境", "当前运行机器上的本机 OS、Shell、PowerShell、Python 工具"),
    "workspace": ("Workspace 工作区", "工作区文件、Artifact 制品和 workspace 元数据"),
    "knowledge": ("Knowledge 知识库", "知识库问答、检索、导入和索引管理"),
    "network": ("Network 网络分析", "离线网络配置解析、接口/路由提取和配置翻译"),
    "web": ("Web 外部资料", "公开 Web、官方文档、新闻、天气和网页摘要"),
    "runtime": ("Runtime 运行审计", "运行状态、session、run、review 和审计信息"),
    "memory": ("Memory 记忆", "记忆搜索、创建、确认、profile 和更新"),
    "report_data": ("Report/Data/Text 输出处理", "报告、表格、文本、JSON/YAML/CSV 和图表处理"),
    "agent": ("Agent 多 Agent", "技能、子 Agent、角色、团队和结果读取"),
}


CATEGORY_TYPICAL_USE = {
    "host": "本机 shell/powershell/python 执行、slash 命令、运行诊断",
    "workspace": "工作区文件列表/读取/编辑、artifact 元数据、安全摘要读写",
    "knowledge": "知识库检索、chunk/source 维护、导入文件/文档",
    "network": "解析/翻译/接口提取/路由提取等离线分析",
    "web": "公开 Web 搜索、厂商官方文档、新闻、天气查询",
    "runtime": "运行健康/诊断、session/run/review 审计",
    "memory": "用户偏好与历史记忆的搜索、写入、确认、profile",
    "report_data": "报告/表格/图表/JSON/YAML/CSV/文本处理输出",
    "agent": "子 Agent、技能、角色、团队任务编排",
}


CATEGORY_NOT_FOR = {
    "host": "不用于网络设备 SSH/Telnet/SNMP/真实设备访问；不用于解析配置文本",
    "workspace": "不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径",
    "knowledge": "不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体",
    "network": "不登录真实设备；不下发配置；translated_config 不等于 deployable_config",
    "web": "不抓私网/本地/登录墙 URL；weather 仅在明确天气需求时使用",
    "runtime": "不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物",
    "memory": "不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认",
    "report_data": "不包含原始敏感配置作为最终输出；text.redact 用于脱敏；validate 不执行代码",
    "agent": "agent.spawn 受 max_turns≤3 限制；skill.create 不自动启用未经审查技能",
}


def _build_tools_payload() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import (
        TOOL_GOVERNANCE,
        governance_summary,
        planner_visible_tool_ids,
    )
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS

    services = _services()
    agent_registry = services.tool_service.registry
    by_execution = {
        spec.tool_id: spec for spec in agent_registry.list_all()
    }

    tools: list[dict[str, Any]] = []
    for canonical_id in sorted(TOOL_NAMESPACE):
        entry = TOOL_NAMESPACE[canonical_id]
        governance = TOOL_GOVERNANCE[canonical_id]
        spec = by_execution.get(entry.execution_tool_id)
        capability_actions = _capability_actions_for(canonical_id, CAPABILITY_ACTIONS)
        tool = {
            "canonical_tool_id": canonical_id,
            "execution_tool_id": entry.execution_tool_id,
            "legacy_aliases": list(entry.legacy_tool_ids),
            "category": entry.category,
            "group": entry.group,
            "action": entry.action,
            "display_name": entry.display_name,
            "short_label": entry.short_label,
            "usage_hint": entry.usage_hint,
            "not_for": entry.not_for,
            "governance_status": governance.status,
            "replacement": governance.replacement,
            "deprecate_after": governance.deprecate_after,
            "overlap_group": governance.overlap_group,
            "governance_reason": governance.reason,
            "migration_notes": governance.migration_notes,
            "planner_visible": governance.status == "keep",
            "capability_actions": capability_actions,
            "risk_level": _safe_attr(spec, "risk_level", "low"),
            "requires_approval": bool(_safe_attr(spec, "requires_approval", False)),
            "permission_action": _safe_attr(spec, "permission_action", ""),
            "callable_by_llm": bool(_safe_attr(spec, "callable_by_llm", True)),
            "enabled": bool(_safe_attr(spec, "enabled", True)),
        }
        tools.append(tool)

    summary = {
        "canonical_count": len(TOOL_NAMESPACE),
        "execution_count": len({t["execution_tool_id"] for t in tools}),
        "legacy_alias_count": len({a for t in tools for a in t["legacy_aliases"]}),
        "planner_visible_count": len(planner_visible_tool_ids()),
        "model_visible_count": len(agent_registry.list_model_visible()),
        "governance_summary": governance_summary(),
        "capability_action_count": len(CAPABILITY_ACTIONS),
        "category_count": len({t["category"] for t in tools}),
    }
    return summary, tools


def _capability_actions_for(
    canonical_id: str,
    actions: dict[str, Any],
) -> list[str]:
    hits: list[str] = []
    for action_id, action in actions.items():
        if canonical_id in action.preferred_tools or canonical_id in action.fallback_tools:
            hits.append(action_id)
    return sorted(hits)


def _safe_attr(spec: Any, name: str, default: Any) -> Any:
    if spec is None:
        return default
    value = getattr(spec, name, None)
    return default if value is None else value


def _services() -> Any:
    from agent.runtime.services import default_runtime_services
    return default_runtime_services()


def _build_categories(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_category: dict[str, dict[str, Any]] = {}
    for tool in tools:
        cat = by_category.setdefault(tool["category"], {
            "id": tool["category"],
            "name": CATEGORY_ZH.get(tool["category"], (tool["category"], ""))[0],
            "description": CATEGORY_ZH.get(tool["category"], (tool["category"], ""))[1],
            "typical_use": CATEGORY_TYPICAL_USE.get(tool["category"], ""),
            "not_for": CATEGORY_NOT_FOR.get(tool["category"], ""),
            "count": 0,
            "groups": {},
        })
        grp = cat["groups"].setdefault(tool["group"], {
            "id": tool["group"],
            "name": tool["group"].replace("_", " ").title(),
            "count": 0,
            "tools": [],
        })
        grp["tools"].append(tool["canonical_tool_id"])
        grp["count"] += 1
        cat["count"] += 1
    categories = []
    for cid in sorted(by_category):
        c = by_category[cid]
        c["groups"] = [c["groups"][gid] for gid in sorted(c["groups"])]
        categories.append(c)
    return categories


def _build_capability_actions() -> list[dict[str, Any]]:
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    rows: list[dict[str, Any]] = []
    for action_id in sorted(CAPABILITY_ACTIONS):
        a = CAPABILITY_ACTIONS[action_id]
        rows.append({
            "capability_action": action_id,
            "category": a.category,
            "group": a.group,
            "preferred_tools": list(a.preferred_tools),
            "fallback_tools": list(a.fallback_tools),
            "reason": a.reason,
        })
    return rows


def build_catalog_payload() -> dict[str, Any]:
    summary, tools = _build_tools_payload()
    return {
        "summary": summary,
        "categories": _build_categories(tools),
        "capability_actions": _build_capability_actions(),
        "tools": tools,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    categories = payload["categories"]
    capability_actions = payload["capability_actions"]
    tools = payload["tools"]
    governance_summary = summary["governance_summary"]

    lines: list[str] = []
    lines.append("# Network Agent Tool Catalog v2.3")
    lines.append("")
    lines.append(
        "> 单一口径来源：`tool_runtime/tool_namespace.py` + "
        "`tool_runtime/tool_governance.py` + `tool_runtime/capability_actions.py`。"
        "本目录由 `scripts/build_tool_catalog_v23.py` 生成；不手工拼接。"
    )
    lines.append("")
    lines.append(
        "机器可读版本：`reports/tool_catalog_v23.json`。"
        "校验脚本：`scripts/verify_tool_catalog_doc.py`。"
    )
    lines.append("")
    lines.append("## 1. 口径说明")
    lines.append("")
    lines.append("v2.3 工具命名是五层模型，本目录统一使用下列口径：")
    lines.append("")
    lines.append(
        "- **canonical_tool_id**：LLM / 前端 / planner 使用的正式工具名。"
        " 三级标题一律使用 canonical id。"
    )
    lines.append(
        "- **execution_tool_id**：底层 handler 调用的稳定 ID，"
        "保留兼容与 trace 可读性，不作为新文档主标题。"
    )
    lines.append(
        "- **legacy_aliases**：历史入口；不可作为新文档主口径，"
        "Planner 不会主动选它们。"
    )
    lines.append(
        "- **capability_action**：planner 选择的高层能力动作；"
        "一个动作可以包含多个 preferred / fallback canonical tools。"
    )
    lines.append(
        "- **governance_status**：治理状态，取值 "
        "`keep / alias / merged / deprecated / removed_candidate`。"
        "仅 `keep` 在 planner 默认候选里。"
    )
    lines.append("")
    lines.append("## 2. 总览统计")
    lines.append("")
    lines.append("以下数字全部来自 runtime registry 与 governance 层，未在文档中估算。")
    lines.append("")
    lines.append(f"- **execution_count**：{summary['execution_count']}")
    lines.append(f"- **canonical_count**：{summary['canonical_count']}")
    lines.append(f"- **model_visible_count**：{summary['model_visible_count']}")
    lines.append(f"- **planner_visible_count**：{summary['planner_visible_count']}")
    lines.append(f"- **legacy_alias_count**：{summary['legacy_alias_count']}")
    lines.append(f"- **capability_action_count**：{summary['capability_action_count']}")
    lines.append(f"- **category_count**：{summary['category_count']}")
    lines.append("")
    lines.append("### 2.1 Governance Summary")
    lines.append("")
    lines.append("| status | count | 说明 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| keep | {governance_summary['keep']} | 稳定可见，是 planner 默认候选 |"
    )
    lines.append(
        f"| alias | {governance_summary['alias']} | 兼容别名，planner 重定向到 replacement |"
    )
    lines.append(
        f"| merged | {governance_summary['merged']} | 已合并，planner 重定向到 replacement |"
    )
    lines.append(
        f"| deprecated | {governance_summary['deprecated']} | 不再进入 planner，legacy 调用仍可执行 |"
    )
    lines.append(
        f"| removed_candidate | {governance_summary['removed_candidate']} | v2.4 起在文档中加 deprecate_after，下一 major 之前不会真删 |"
    )
    lines.append("")

    lines.append("## 3. 能力域目录")
    lines.append("")
    lines.append("按 v2.3 category 分组。下表是 planner 默认可见的 `keep` 工具分布。")
    lines.append("")
    lines.append(
        "| 能力域 | 说明 | 典型场景 | 不适用场景 | groups | tools | planner 默认可见 |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    by_cat: dict[str, dict[str, Any]] = {}
    for tool in tools:
        c = by_cat.setdefault(tool["category"], {
            "total": 0,
            "keep": 0,
            "groups": set(),
        })
        c["total"] += 1
        c["groups"].add(tool["group"])
        if tool["planner_visible"]:
            c["keep"] += 1
    for cat in categories:
        stats = by_cat[cat["id"]]
        zh_name = cat["name"]
        lines.append(
            f"| **{zh_name}** (`{cat['id']}`) | {cat['description']} | "
            f"{cat['typical_use']} | {cat['not_for']} | "
            f"{len(cat['groups'])} | {stats['total']} | {stats['keep']} |"
        )
    lines.append("")

    lines.append("## 4. Capability Actions")
    lines.append("")
    lines.append(
        "Planner 在 v2.2.1 rule_scene 之上，再走 capability_action 计划，"
        "把动作展开成 preferred / fallback 工具集后再走 governance 过滤。"
    )
    lines.append("")
    lines.append("```text")
    lines.append("用户请求")
    lines.append("→ capability_action plan")
    lines.append("→ canonical tools")
    lines.append("→ governance filter (keep only)")
    lines.append("→ candidate_tools")
    lines.append("→ ToolRouter")
    lines.append("→ execution_tool_id")
    lines.append("```")
    lines.append("")
    lines.append(
        "| capability_action | category | group | preferred_tools | fallback_tools | 用途 |"
    )
    lines.append("|---|---|---|---|---|---|")
    for action in capability_actions:
        preferred = ", ".join(f"`{t}`" for t in action["preferred_tools"]) or "—"
        fallback = ", ".join(f"`{t}`" for t in action["fallback_tools"]) or "—"
        lines.append(
            f"| `{action['capability_action']}` | {action['category']} | "
            f"{action['group']} | {preferred} | {fallback} | {action['reason']} |"
        )
    lines.append("")

    lines.append("## 5. 完整工具清单")
    lines.append("")
    lines.append(
        "本节按能力域排序，每个 canonical tool 一节，"
        "格式严格统一：**canonical id 为三级标题**，execution / legacy 为兼容字段。"
    )
    lines.append("")

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tool in tools:
        by_category[tool["category"]].append(tool)

    for cat in categories:
        lines.append(f"### 5.{categories.index(cat) + 1}. {cat['name']} (`{cat['id']}`)")
        lines.append("")
        lines.append(f"**说明**：{cat['description']}")
        lines.append("")
        lines.append(f"**典型场景**：{cat['typical_use']}")
        lines.append("")
        lines.append(f"**不适用场景**：{cat['not_for']}")
        lines.append("")
        lines.append(f"**包含 groups**：`{', '.join(g['id'] for g in cat['groups'])}`")
        lines.append("")
        lines.append(f"**canonical tools 数**：{cat['count']}")
        lines.append("")
        for tool in by_category[cat["id"]]:
            lines.extend(_render_tool(tool))
    lines.append("")

    lines.append("## 6. Governance Summary")
    lines.append("")
    lines.append("详见 §2.1 与 §7；此处汇总非 keep 工具的统计：")
    lines.append("")
    lines.append(
        f"- alias: {governance_summary['alias']}"
        f"，merged: {governance_summary['merged']}"
        f"，deprecated: {governance_summary['deprecated']}"
        f"，removed_candidate: {governance_summary['removed_candidate']}"
    )
    lines.append("")

    lines.append("## 7. Deprecated / Alias / Merged / Removed Candidate")
    lines.append("")
    lines.append(
        "| canonical_tool_id | governance_status | replacement | reason | migration_notes |"
    )
    lines.append("|---|---|---|---|---|")
    for tool in tools:
        if tool["governance_status"] == "keep":
            continue
        replacement = tool["replacement"] or "—"
        lines.append(
            f"| `{tool['canonical_tool_id']}` | `{tool['governance_status']}` | "
            f"`{replacement}` | {tool['governance_reason']} | "
            f"{tool['migration_notes']} |"
        )
    lines.append("")

    lines.append("## 8. Planner 可见工具")
    lines.append("")
    lines.append(
        f"`planner_visible_count = {summary['planner_visible_count']}`，"
        "等于 `governance.keep`。下面 88 个工具中，"
        f"{summary['canonical_count'] - summary['planner_visible_count']} 个不进 planner 候选。"
    )
    lines.append("")
    lines.append("### 8.1 planner 可见（keep）")
    lines.append("")
    keep_lines = [f"- `{tool['canonical_tool_id']}`" for tool in tools if tool["planner_visible"]]
    lines.extend(keep_lines)
    lines.append("")
    lines.append("### 8.2 planner 不可见（非 keep）")
    lines.append("")
    non_keep_lines = [
        f"- `{tool['canonical_tool_id']}` — `{tool['governance_status']}`"
        f"{' → ' + tool['replacement'] if tool['replacement'] else ''}"
        for tool in tools
        if not tool["planner_visible"]
    ]
    lines.extend(non_keep_lines)
    lines.append("")

    lines.append("## 9. Legacy Compatibility")
    lines.append("")
    lines.append(
        f"legacy_alias_count = {summary['legacy_alias_count']}，"
        "所有 legacy 别名都映射到 canonical id。"
    )
    lines.append("")
    lines.append("| legacy_alias | execution_tool_id | canonical_tool_id | governance_status |")
    lines.append("|---|---|---|---|")
    for tool in tools:
        for alias in tool["legacy_aliases"]:
            lines.append(
                f"| `{alias}` | `{tool['execution_tool_id']}` | "
                f"`{tool['canonical_tool_id']}` | `{tool['governance_status']}` |"
            )
    lines.append("")

    lines.append("## 10. 注意边界")
    lines.append("")
    lines.append("- **不再以旧 execution id 为主标题**：三级标题一律为 canonical_tool_id。")
    lines.append(
        "- **不再只列 execution_tool_id**：每个工具都同时给出 "
        "execution / legacy / governance / planner_visible / capability_actions。"
    )
    lines.append(
        "- **文档统计与 audit json 必须一致**：本文档由 "
        "`scripts/build_tool_catalog_v23.py` 生成，与 "
        "`reports/tool_architecture_audit.json` 的 summary 对齐。"
    )
    lines.append(
        "- **planner 不选非 keep 工具**：deprecated / removed_candidate 仅保留为 "
        "兼容调用通道，rule_scene / capability_action 不会把它们加入候选。"
    )
    lines.append(
        "- **host.* 高风险**：shell / powershell / python.exec 仅在本机执行，"
        "需要 approval_id，绝不用于网络设备 SSH/Telnet/SNMP。"
    )
    lines.append(
        "- **network.* 离线**：解析/翻译/接口/路由全部离线，"
        "不登录真实设备，不生成 deployable_config。"
    )
    lines.append(
        "- **artifact.read_safe 不再独立**：v2.3 起 "
        "`workspace.artifact.read` 是统一入口，安全语义由 policy + metadata "
        "承担；`workspace.artifact.read_safe` 不再独立维护。"
    )
    lines.append(
        "- **memory 不写 secret**：memory.create / profile.set 不写入 secret；"
        "confirm 留给用户决定是否升级为长期记忆。"
    )
    lines.append(
        "- **web 公开 URL**：web.* 只访问公开 URL，"
        "私网/本地/登录墙 URL 被路径安全层直接拒绝。"
    )
    lines.append("")
    return "\n".join(lines)


def _render_tool(tool: dict[str, Any]) -> list[str]:
    block: list[str] = []
    block.append(f"### `{tool['canonical_tool_id']}`")
    block.append("")
    block.append(f"- **display_name**: {tool['display_name']}")
    block.append(f"- **execution_tool_id**: `{tool['execution_tool_id']}`")
    legacy = ", ".join(f"`{a}`" for a in tool["legacy_aliases"]) or "—"
    block.append(f"- **legacy_aliases**: {legacy}")
    block.append(
        f"- **category / group / action**: {tool['category']} / "
        f"{tool['group']} / {tool['action']}"
    )
    if tool["capability_actions"]:
        actions = ", ".join(f"`{a}`" for a in tool["capability_actions"])
        block.append(f"- **capability_actions**: {actions}")
    else:
        block.append(
            "- **capability_actions**: none  \n"
            "  reason: internal/helper/manual-only"
        )
    block.append(f"- **governance_status**: `{tool['governance_status']}`")
    if tool["governance_status"] != "keep":
        replacement = tool["replacement"] or "—"
        block.append(
            f"- **replacement**: `{replacement}`  "
            f"\n  **migration_notes**: {tool['migration_notes']}"
        )
    block.append(f"- **planner_visible**: {str(tool['planner_visible']).lower()}")
    block.append(f"- **risk_level**: {tool['risk_level']}")
    block.append(f"- **requires_approval**: {str(tool['requires_approval']).lower()}")
    block.append(f"- **用途**: {tool['usage_hint']}")
    block.append(f"- **边界**: {tool['not_for']}")
    block.append("")
    return block


def main() -> int:
    payload = build_catalog_payload()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "tool_catalog_v23.json"
    md_path = REPORT_DIR / "TOOL_CATALOG_V2.3.md"
    docs_md_path = DOCS_DIR / "TOOL_CATALOG_V2.3.md"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = render_markdown(payload)
    md_path.write_text(md, encoding="utf-8")
    docs_md_path.write_text(md, encoding="utf-8")

    summary = payload["summary"]
    print(f"wrote {json_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(f"wrote {docs_md_path.relative_to(ROOT)}")
    print(f"canonical_count: {summary['canonical_count']}")
    print(f"execution_count: {summary['execution_count']}")
    print(f"planner_visible_count: {summary['planner_visible_count']}")
    print(f"legacy_alias_count: {summary['legacy_alias_count']}")
    print(f"capability_action_count: {summary['capability_action_count']}")
    print(f"governance_summary: {summary['governance_summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
