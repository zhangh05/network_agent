"""Skill tool handlers — v3.9.3 inline business metadata.

v3.9.2: Skills were CapabilityPackages in capability_routing/manifests.py.
v3.9.3: capability_routing/ removed. Business metadata is inlined here
as a plain dict so the LLM-visible skill.manage tool can still answer
list/find/load/inspect without depending on the routing layer.

Each entry mirrors the old CapabilityPackage fields: display_name,
description, intent_keywords, module_ids, tool_ids, prompt_hints,
safety_notes, output_kinds, priority.
"""

from __future__ import annotations

from tool_runtime.schemas import ToolInvocation
from workspace.ids import validate_workspace_id

from tool_runtime.general_tools.shared import _caller_workspace, _contract, _error, _error_inv, _ok, _result, _unavailable, _workspace_path


# v3.9.3 inlined from capability_routing/manifests.py
SKILL_PACKAGES: tuple[dict, ...] = (
    {
        "capability_id": "workspace_read",
        "display_name": "Workspace Read",
        "description": "Read or inspect workspace files and artifacts.",
        "intent_keywords": ("file", "workspace", "artifact", "文件", "制品", "读取", "查看"),
        "module_ids": ("workspace",),
        "tool_ids": ("workspace.file", "workspace.artifact"),
        "prompt_hints": ("Read workspace files before parsing domain content.",),
        "output_kinds": ("text",),
        "safety_notes": (),
        "priority": 10,
    },
    {
        "capability_id": "knowledge_qa",
        "display_name": "Knowledge QA",
        "description": "Search and read indexed knowledge.",
        "intent_keywords": ("knowledge", "docs", "文档", "知识", "资料", "手册", "查询"),
        "module_ids": ("knowledge",),
        "tool_ids": ("knowledge.manage",),
        "prompt_hints": (),
        "output_kinds": ("summary",),
        "safety_notes": (),
        "priority": 20,
    },
    {
        "capability_id": "memory_lookup",
        "display_name": "Memory Lookup",
        "description": "Search or inspect memory and profile facts.",
        "intent_keywords": ("memory", "remember", "记忆", "偏好", "画像", "之前"),
        "module_ids": ("memory",),
        "tool_ids": ("memory.manage",),
        "prompt_hints": (),
        "output_kinds": (),
        "safety_notes": (),
        "priority": 30,
    },
    {
        "capability_id": "config_translation",
        "display_name": "Config Translation",
        "description": "Parse, translate, compare and summarize network configuration text.",
        "intent_keywords": ("config", "configuration", "translate", "配置", "翻译", "转换", "厂商", "h3c", "cisco", "huawei"),
        "module_ids": ("config_analysis", "workspace"),
        "tool_ids": ("workspace.file", "config.manage"),
        "prompt_hints": ("Translated config is analysis output, not deployable configuration.",),
        "output_kinds": ("markdown", "translated_config"),
        "safety_notes": ("Do not claim translated configuration is production-ready.",),
        "priority": 5,
    },
    {
        "capability_id": "pcap_analysis",
        "display_name": "PCAP Analysis",
        "description": "Parse and inspect packet capture files.",
        "intent_keywords": ("pcap", "pcapng", "packet", "抓包", "报文", "五元组", "tcp", "重传"),
        "module_ids": ("pcap", "workspace"),
        "tool_ids": ("workspace.file", "pcap.manage"),
        "prompt_hints": (),
        "output_kinds": ("summary", "table"),
        "safety_notes": (),
        "priority": 6,
    },
    {
        "capability_id": "report_drafting",
        "display_name": "Report Drafting",
        "description": "Render reports and save report artifacts.",
        "intent_keywords": ("report", "markdown", "总结", "报告", "整理", "导出"),
        "module_ids": ("workspace",),
        "tool_ids": ("report.manage", "workspace.artifact"),
        "prompt_hints": (),
        "output_kinds": ("markdown", "artifact"),
        "safety_notes": (),
        "priority": 40,
    },
    {
        "capability_id": "runtime_diagnostics",
        "display_name": "Runtime Diagnostics",
        "description": "Inspect runtime health and diagnostics.",
        "intent_keywords": ("runtime", "diagnostic", "health", "运行", "诊断", "健康", "自检"),
        "module_ids": ("runtime",),
        "tool_ids": ("system.manage",),
        "prompt_hints": (),
        "output_kinds": (),
        "safety_notes": (),
        "priority": 50,
    },
    {
        "capability_id": "agent_delegation",
        "display_name": "Agent 子任务派发",
        "description": "派发子 Agent、列出 Agent 角色、运行 Agent 团队并读取子任务结果。",
        "intent_keywords": ("子agent", "子 agent", "subagent", "派发", "委派", "agent",
                          "多agent", "多 agent", "团队", "team", "spawn", "delegate",
                          "让它搜索", "让它检查", "让它分析"),
        "module_ids": ("runtime",),
        "tool_ids": ("agent.manage",),
        "prompt_hints": (),
        "output_kinds": ("task", "summary"),
        "safety_notes": ("子 Agent 必须继承 workspace/session 边界。", "读取结果需通过 agent.result.get。"),
        "priority": 8,
    },
    {
        "capability_id": "cmdb",
        "display_name": "CMDB 设备资产",
        "description": "查询、添加、删除网络设备资产。每个资产记录名称、类型、厂商、型号、IP、连接方式。",
        "intent_keywords": ("cmdb", "设备", "资产", "添加设备", "录入设备", "新增设备",
                          "删除设备", "有哪些设备", "查设备", "看设备", "设备资产",
                          "资产管理", "设备清单", "设备列表", "设备名",
                          "多少设备", "几个设备", "添加", "新增", "录入", "asset"),
        "module_ids": ("cmdb",),
        "tool_ids": ("device.manage",),
        "prompt_hints": (),
        "output_kinds": ("table", "summary"),
        "safety_notes": ("不可声明 CMDB 中存在未从工具返回的设备。", "添加/删除操作需确认。"),
        "priority": 7,
    },
    {
        "capability_id": "network_device",
        "display_name": "Network 设备 SSH/Telnet",
        "description": "SSH / Telnet 连接网络设备并执行命令。先通过 CMDB 获取设备信息，再调用连接工具。",
        "intent_keywords": ("ssh", "telnet", "连接", "登录设备", "display", "show run",
                          "执行命令", "show version", "display version"),
        "module_ids": ("cmdb",),
        "tool_ids": ("device.manage", "exec.run"),
        "prompt_hints": (),
        "output_kinds": ("text",),
        "safety_notes": ("真实设备访问，需审批。", "危险命令（reload/erase/format）自动拦截。"),
        "priority": 6,
    },
    {
        "capability_id": "browser",
        "display_name": "Browser 浏览器自动化",
        "description": "使用 Playwright 浏览器导航网页、提取内容、截图、点击交互。",
        "intent_keywords": ("browser", "浏览器", "网页", "打开链接", "截图", "提取内容",
                          "navigate", "screenshot", "scrape", "访问网站", "查看网页",
                          "打开网页", "页面内容", "抓取"),
        "module_ids": ("browser",),
        "tool_ids": ("browser.manage",),
        "prompt_hints": ("Browser provides real-time web page content. Always prefer browser over web.page.process when interactive browsing is needed.",),
        "output_kinds": ("text", "image"),
        "safety_notes": ("浏览器内容来自外部网站，可能不准确。禁止访问内网/需登录页面。",),
        "priority": 8,
    },
)


def _pkg_as_dict(pkg: dict) -> dict:
    """Skill dict (v3.9.3 inline)."""
    return {
        "skill_id": pkg["capability_id"],
        "display_name": pkg["display_name"],
        "description": pkg["description"],
        "status": "active",
        "capability_ids": (pkg["capability_id"],),
        "module_ids": tuple(pkg["module_ids"]),
        "tool_ids": tuple(pkg["tool_ids"]),
        "prompt_hints": tuple(pkg["prompt_hints"]),
        "safety_notes": tuple(pkg["safety_notes"]),
        "output_kinds": tuple(pkg["output_kinds"]),
        "source": "skill_package",
    }


def _search_packages(query: str, limit: int = 10) -> list[dict]:
    """Keyword search in SKILL_PACKAGES."""
    q = (query or "").lower().strip()
    if not q:
        return []
    matches = []
    for pkg in SKILL_PACKAGES:
        haystack = " ".join([
            pkg["capability_id"], pkg["display_name"], pkg["description"],
            " ".join(pkg["intent_keywords"]),
            " ".join(pkg["module_ids"]), " ".join(pkg["tool_ids"]),
        ]).lower()
        if q in haystack:
            matches.append(_pkg_as_dict(pkg))
    return matches[:max(1, min(limit, 20))]


# ── tool handlers ──

def handle_skill_list(inv: ToolInvocation) -> dict:
    """List all skill packages."""
    try:
        results = [_pkg_as_dict(p) for p in SKILL_PACKAGES]
        return _ok(inv, "", {"results": results, "count": len(results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_skill_request_load(inv: ToolInvocation) -> dict:
    return handle_skill_load(inv)


def handle_skill_load(inv: ToolInvocation) -> dict:
    """Load a skill by capability_id; returns tool_ids, prompt_hints, etc."""
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    # Direct lookup
    for pkg in SKILL_PACKAGES:
        if pkg["capability_id"] == skill_name:
            return _ok(inv, "", {
                "skill_id": pkg["capability_id"],
                "status": "active",
                "capability_ids": [pkg["capability_id"]],
                "module_ids": list(pkg["module_ids"]),
                "tool_ids": list(pkg["tool_ids"]),
                "prompt_hints": list(pkg["prompt_hints"]),
                "safety_notes": list(pkg["safety_notes"]),
                "message": "skill loaded",
                "skill_record": {
                    "skill_id": pkg["capability_id"],
                    "status": "active",
                    "capability_ids": [pkg["capability_id"]],
                    "module_ids": list(pkg["module_ids"]),
                    "tool_ids": list(pkg["tool_ids"]),
                    "prompt_hints": list(pkg["prompt_hints"]),
                    "safety_notes": list(pkg["safety_notes"]),
                },
            })

    # Fuzzy match
    lower = skill_name.lower()
    for pkg in SKILL_PACKAGES:
        if lower in pkg["capability_id"].lower() or lower in pkg["display_name"].lower():
            return _ok(inv, "", {
                "skill_id": pkg["capability_id"],
                "status": "active",
                "capability_ids": [pkg["capability_id"]],
                "module_ids": list(pkg["module_ids"]),
                "tool_ids": list(pkg["tool_ids"]),
                "prompt_hints": list(pkg["prompt_hints"]),
                "safety_notes": list(pkg["safety_notes"]),
                "message": "skill loaded (fuzzy match)",
                "skill_record": {
                    "skill_id": pkg["capability_id"],
                    "status": "active",
                    "capability_ids": [pkg["capability_id"]],
                    "module_ids": list(pkg["module_ids"]),
                    "tool_ids": list(pkg["tool_ids"]),
                },
            })

    return _error_inv(inv, f"skill '{skill_name}' not found. Available: {[p['capability_id'] for p in SKILL_PACKAGES]}")


def handle_skill_find(inv: ToolInvocation) -> dict:
    """Search skills by keyword."""
    args = inv.arguments or {}
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10))
    if not query:
        return _error_inv(inv, "query is required")
    try:
        results = _search_packages(query, limit=limit)
        return _ok(inv, "", {"results": results, "count": len(results), "query": query})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_skill_create(inv: ToolInvocation) -> dict:
    """Skill creation is disabled."""
    return {
        "ok": False,
        "tool_id": inv.tool_id,
        "status": "blocked",
        "summary": "Skill creation is disabled; use an existing capability.",
        "errors": ["skill_create_disabled"],
    }


def handle_skill_install(inv: ToolInvocation) -> dict:
    return {
        "ok": False,
        "tool_id": inv.tool_id,
        "status": "blocked",
        "summary": "Skill installation is disabled; use an existing capability.",
        "errors": ["skill_install_disabled"],
    }


def handle_skill_inspect(inv: ToolInvocation) -> dict:
    """Return skill details."""
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    for pkg in SKILL_PACKAGES:
        if pkg["capability_id"] == skill_name:
            return _ok(inv, "", _pkg_as_dict(pkg))

    return _error_inv(inv, f"skill '{skill_name}' not found")


__all__ = [
    "handle_skill_list",
    "handle_skill_request_load",
    "handle_skill_load",
    "handle_skill_find",
    "handle_skill_create",
    "handle_skill_install",
    "handle_skill_inspect",
    "SKILL_PACKAGES",
]
