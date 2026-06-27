#!/usr/bin/env python3
"""Build the v3.0 canonical-only tool catalog (JSON + Markdown).

Sources (in priority order):
  1. tool_runtime.tool_namespace / TOOL_NAMESPACE (canonical IDs only)
  2. tool_runtime.tool_governance / TOOL_GOVERNANCE (active / disabled / internal / forbidden)
  3. tool_runtime.canonical_registry / CANONICAL_REGISTRY (canonical -> handler_id)
  4. tool_runtime.capability_actions / CAPABILITY_ACTIONS (planner verbs)

Outputs:
  reports/tool_catalog.json
  docs/TOOL_CATALOG.md
  reports/TOOL_CATALOG.md
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
    "host": ("Host 本机环境", "当前运行机器上的本机 OS、Shell、PowerShell、Python 工具。"),
    "workspace": ("Workspace 工作区", "工作区文件、Artifact 制品和 workspace 元数据。"),
    "knowledge": ("Knowledge 知识库", "知识库问答、检索、导入和索引管理。"),
    "network": ("Network 网络分析", "离线网络配置解析、接口 / 路由提取和配置翻译。"),
    "web": ("Web 外部资料", "公开 Web、官方文档、新闻、天气和网页摘要。"),
    "runtime": ("Runtime 运行审计", "运行状态、session、run、review 和审计信息。"),
    "memory": ("Memory 记忆", "记忆搜索、创建、确认、profile 和更新。"),
    "report_data": ("Report / Data / Text 输出处理", "报告、表格、文本、JSON / YAML / CSV 和图表处理。"),
    "agent": ("Agent 多 Agent", "技能、子 Agent、角色、团队和结果读取。"),
}


CATEGORY_TYPICAL_USE = {
    "host": "本机 shell / powershell / python 执行、slash 命令、运行诊断。",
    "workspace": "工作区文件列表 / 读取 / 编辑、artifact 元数据、安全摘要读写。",
    "knowledge": "知识库检索、chunk/source 维护、导入文件 / 文档。",
    "network": "网络配置离线分析 / SSH / Telnet 远程设备命令执行。",
    "web": "公开 Web 搜索、厂商官方文档、新闻、天气查询。",
    "runtime": "运行健康 / 诊断、session / run / review 审计。",
    "memory": "用户偏好与历史记忆的搜索、写入、确认、profile。",
    "report_data": "报告 / 表格 / 图表 / JSON / YAML / CSV / 文本处理输出。",
    "agent": "子 Agent、技能、角色、团队任务编排。",
}


CATEGORY_NOT_FOR = {
    "host": "不用于网络设备 SSH / Telnet / SNMP / 真实设备访问；不用于解析配置文本。",
    "workspace": "不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径。",
    "knowledge": "不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体。",
    "network": "不执行危险命令（reload/erase/format）；不下发配置；translated_config ≠ deployable_config。",
    "web": "不抓私网 / 本地 / 登录墙 URL；weather 仅在明确天气需求时使用。",
    "runtime": "不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物。",
    "memory": "不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认。",
    "report_data": "不包含原始敏感配置作为最终输出；text.analyze 用于脱敏；validate 不执行代码。",
    "agent": "agent.spawn 受 max_turns≤3 限制；skill.load 不加载未经审查的技能。",
}


def _build_tools() -> list[dict[str, Any]]:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS, capability_actions_for
    from tool_runtime.manifest_registry import get_manifest

    tools: list[dict[str, Any]] = []
    for canonical_id in sorted(TOOL_NAMESPACE):
        ns_entry = TOOL_NAMESPACE[canonical_id]
        gov_entry = TOOL_GOVERNANCE[canonical_id]
        cr_entry = CANONICAL_REGISTRY.get(canonical_id)
        manifest = get_manifest(canonical_id)
        tool = {
            "canonical_tool_id": canonical_id,
            "category": ns_entry.category,
            "group": ns_entry.group,
            "action": ns_entry.action,
            "display_name": ns_entry.display_name,
            "short_label": ns_entry.short_label,
            "usage_hint": ns_entry.usage_hint,
            "not_for": ns_entry.not_for,
            "governance_status": gov_entry.status,
            "planner_visible": gov_entry.planner_visible,
            "governance_reason": gov_entry.reason,
            "capability_actions": capability_actions_for(canonical_id),
            "input_schema": cr_entry.input_schema if cr_entry else {},
            "risk_level": manifest.risk_level if manifest else (cr_entry.risk_level if cr_entry else "low"),
            "requires_approval": manifest.requires_approval if manifest else (cr_entry.requires_approval if cr_entry else False),
        }
        tools.append(tool)
    return tools


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
    return [
        {**by_category[cid], "groups": [by_category[cid]["groups"][gid] for gid in sorted(by_category[cid]["groups"])]}
        for cid in sorted(by_category)
    ]


def _build_capability_actions() -> list[dict[str, Any]]:
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    rows: list[dict[str, Any]] = []
    for action_id in sorted(CAPABILITY_ACTIONS):
        action = CAPABILITY_ACTIONS[action_id]
        rows.append({
            "capability_action": action_id,
            "category": action.category,
            "group": action.group,
            "preferred_tools": list(action.preferred_tools),
            "fallback_tools": list(action.fallback_tools),
            "reason": action.reason,
        })
    return rows


def build_catalog_payload() -> dict[str, Any]:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import governance_summary, planner_visible_tool_ids
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY

    tools = _build_tools()
    summary = {
        "canonical_count": len(TOOL_NAMESPACE),
        "handler_count": len(CANONICAL_REGISTRY),
        "planner_visible_count": len(planner_visible_tool_ids()),
        "governance_summary": governance_summary(),
        "capability_action_count": len(CAPABILITY_ACTIONS),
        "category_count": len({t["category"] for t in tools}),
    }
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
    lines.append("# Network Agent Tool Catalog (v3.0 canonical-only)")
    lines.append("")
    lines.append(
        "> Single source: `tool_runtime/tool_namespace.py` + "
        "`tool_runtime/tool_governance.py` + "
        "`tool_runtime/canonical_registry.py` + "
        "`tool_runtime/capability_actions.py`."
    )
    lines.append("")
    lines.append(
        "Machine-readable mirror: `reports/tool_catalog.json`. "
        "Verifier: `scripts/verify_tool_catalog_doc.py`."
    )
    lines.append("")
    lines.append("## 1. Identity Contract")
    lines.append("")
    lines.append(
        "v3.0 tool IDs are canonical-only. Tools outside the active public "
        "surface are represented by governance_status `forbidden`."
    )
    lines.append("")
    lines.append("- **canonical_tool_id**: the public tool ID used by the "
                 "LLM, frontend, planner, API, docs, and trace.")
    lines.append("- **handler_id**: an internal implementation key. It "
                 "never appears in the public catalog, LLM prompt, "
                 "frontend default view, or docs main tables.")
    lines.append("- **capability_action**: a high-level planner verb that "
                 "expands to one or more canonical_tool_ids.")
    lines.append("- **governance_status**: one of `active | disabled | "
                 "internal | forbidden`.")
    lines.append("")
    lines.append("## 2. Summary")
    lines.append("")
    lines.append(f"- **canonical_count**: {summary['canonical_count']}")
    lines.append(f"- **handler_count**: {summary['handler_count']}")
    lines.append(f"- **planner_visible_count**: {summary['planner_visible_count']}")
    lines.append(f"- **capability_action_count**: {summary['capability_action_count']}")
    lines.append(f"- **category_count**: {summary['category_count']}")
    lines.append("")
    lines.append("### 2.1 Governance Summary")
    lines.append("")
    lines.append("| status | count | meaning |")
    lines.append("|---|---|---|")
    lines.append(
        f"| active | {governance_summary['active']} | planner default candidate |"
    )
    lines.append(
        f"| disabled | {governance_summary['disabled']} | not available right now |"
    )
    lines.append(
        f"| internal | {governance_summary['internal']} | runtime-only, never exposed |"
    )
    lines.append(
        f"| forbidden | {governance_summary['forbidden']} | refused by registry |"
    )
    lines.append("")
    lines.append("## 3. Capability Domains")
    lines.append("")
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
    lines.append(
        "| Domain | Description | Typical use | Not for | Groups | Tools | Planner visible |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for cat in categories:
        stats = by_cat[cat["id"]]
        lines.append(
            f"| **{cat['name']}** (`{cat['id']}`) | {cat['description']} | "
            f"{cat['typical_use']} | {cat['not_for']} | "
            f"{len(cat['groups'])} | {stats['total']} | {stats['keep']} |"
        )
    lines.append("")

    lines.append("## 4. Capability Actions")
    lines.append("")
    lines.append("```text")
    lines.append("user request")
    lines.append("→ capability_action plan")
    lines.append("→ canonical tools (preferred + fallback)")
    lines.append("→ governance filter (status == active)")
    lines.append("→ candidate_tools")
    lines.append("→ ToolRouter")
    lines.append("→ handler_id dispatch")
    lines.append("```")
    lines.append("")
    lines.append(
        "| capability_action | category | group | preferred_tools | fallback_tools | reason |"
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

    lines.append("## 5. Full Tool Listing")
    lines.append("")
    by_category = defaultdict(list)
    for tool in tools:
        by_category[tool["category"]].append(tool)

    for cat in categories:
        lines.append(f"### 5.{categories.index(cat) + 1}. {cat['name']} (`{cat['id']}`)")
        lines.append("")
        lines.append(f"**Description**: {cat['description']}")
        lines.append("")
        lines.append(f"**Typical use**: {cat['typical_use']}")
        lines.append("")
        lines.append(f"**Not for**: {cat['not_for']}")
        lines.append("")
        lines.append(
            f"**Groups**: `{', '.join(g['id'] for g in cat['groups'])}`"
        )
        lines.append("")
        lines.append(f"**Canonical tools**: {cat['count']}")
        lines.append("")
        for tool in by_category[cat["id"]]:
            lines.extend(_render_tool(tool))
    lines.append("")

    lines.append("## 6. Governance Summary")
    lines.append("")
    lines.append(
        f"active={governance_summary['active']} "
        f"disabled={governance_summary['disabled']} "
        f"internal={governance_summary['internal']} "
        f"forbidden={governance_summary['forbidden']}"
    )
    lines.append("")

    lines.append("## 7. Disabled / Internal / Forbidden")
    lines.append("")
    lines.append(
        "| canonical_tool_id | governance_status | reason |"
    )
    lines.append("|---|---|---|")
    for tool in tools:
        if tool["governance_status"] == "active":
            continue
        lines.append(
            f"| `{tool['canonical_tool_id']}` | `{tool['governance_status']}` | "
            f"{tool['governance_reason']} |"
        )
    lines.append("")

    lines.append("## 8. Planner Visible Tools")
    lines.append("")
    keep_lines = [f"- `{tool['canonical_tool_id']}`" for tool in tools if tool["planner_visible"]]
    lines.extend(keep_lines)
    lines.append("")

    lines.append("## 9. Internal Handler Map (Runtime Only)")
    lines.append("")
    lines.append(
        "`handler_id` is internal-only and is NOT part of the public "
        "catalog. The dispatch table lives in "
        "`tool_runtime/canonical_registry.py` and is not surfaced in "
        "this document."
    )
    lines.append("")

    lines.append("## 10. Boundaries")
    lines.append("")
    lines.append("- canonical_tool_id is the only public tool ID.")
    lines.append("- handler_id is internal-only.")
    lines.append("- capability_action is a planner verb, never a tool ID.")
    lines.append("- governance_status values are active / disabled / "
                 "internal / forbidden only.")
    lines.append("- The public surface has no transition / retirement "
                 "fields.")
    lines.append("")
    return "\n".join(lines)


def _render_tool(tool: dict[str, Any]) -> list[str]:
    block: list[str] = []
    block.append(f"### `{tool['canonical_tool_id']}`")
    block.append("")
    block.append(f"- **display_name**: {tool['display_name']}")
    block.append(f"- **category / group / action**: {tool['category']} / "
                 f"{tool['group']} / {tool['action']}")
    if tool["capability_actions"]:
        actions = ", ".join(f"`{a}`" for a in tool["capability_actions"])
        block.append(f"- **capability_actions**: {actions}")
    else:
        block.append(
            "- **capability_actions**: none\n"
            "  reason: internal-only"
        )
    block.append(f"- **governance_status**: `{tool['governance_status']}`")
    if tool["governance_status"] != "active":
        block.append(
            f"- **governance_reason**: {tool['governance_reason']}"
        )
    block.append(f"- **planner_visible**: {str(tool['planner_visible']).lower()}")
    block.append(f"- **risk_level**: {tool['risk_level']}")
    block.append(f"- **requires_approval**: {str(tool['requires_approval']).lower()}")
    block.append(f"- **usage**: {tool['usage_hint']}")
    block.append(f"- **boundary**: {tool['not_for']}")
    block.append("")
    return block


def main() -> int:
    payload = build_catalog_payload()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "tool_catalog.json"
    md_path = REPORT_DIR / "TOOL_CATALOG.md"
    docs_md_path = DOCS_DIR / "TOOL_CATALOG.md"

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
    print(f"handler_count: {summary['handler_count']}")
    print(f"planner_visible_count: {summary['planner_visible_count']}")
    print(f"capability_action_count: {summary['capability_action_count']}")
    print(f"governance: {summary['governance_summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
