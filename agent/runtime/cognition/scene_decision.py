# agent/runtime/cognition/scene_decision.py
"""Unified scene decision — consolidates intent, greeting, signal detection, and follow-up logic.

Merges responsibility from:
- prompts.py::classify_intent
- message_builder.py::_is_pure_greeting, _looks_like_tool_query
- tool_category_router.py::route_tool_scene (signal detection)
- context_tools.py::is_tool_followup
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SceneDecision:
    user_input: str = ""
    intent: str = "chat"

    # Task type flags
    is_simple_chat: bool = False
    is_factual_query: bool = False
    is_network_task: bool = False
    is_translation_task: bool = False
    is_file_task: bool = False
    is_knowledge_task: bool = False
    is_memory_task: bool = False
    is_web_task: bool = False
    is_local_ops_task: bool = False
    is_runtime_task: bool = False
    is_report_task: bool = False
    is_sub_agent_task: bool = False

    # Needs flags
    needs_tool: bool = False
    needs_context: bool = False
    needs_memory: bool = False
    needs_knowledge: bool = False
    needs_file: bool = False
    needs_web: bool = False
    needs_local_ops: bool = False
    needs_sub_agent: bool = False
    needs_clarification: bool = False

    # Routing metadata
    primary_category: str = "chat"
    categories: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)
    signals: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    followup_inherited: bool = False


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(n.lower() in lower for n in needles)


# ── Sub-agent intent (v3.2.0 hardening) ─────────────────────────────────
# Robust detection across Chinese/English and verb+agent compound patterns.
# Replaces the brittle keyword list that missed "派发子agent", "让它", "delegate to", etc.
_SUB_AGENT_KEYWORDS: tuple[str, ...] = (
    # English literal
    "sub agent", "sub-agent", "subagent", "spawn", "delegate", "multi-agent",
    "multi agent", "agent.team", "agent.manage", "fork agent", "fork an agent",
    # Chinese literal
    "子代理", "子agent", "子 agent", "子任务", "分派", "调度", "派发",
    "并行", "同时", "分头", "委托", "各自", "分别",
    # Phrasal intents
    "研究一下", "全面看看", "都检查", "全部", "所有文件",
    "每一个", "都搜", "都查", "多 agent", "多agent",
)
# Verb + agent pattern: 派发/让/请/叫/叫一个 + agent|子代理|子任务
_SUB_AGENT_VERB_PATTERN = re.compile(
    r"(派发|派去|派一个|让|请|叫|叫一个|动用|发动|唤起|发起)"
    r".{0,4}?(agent|子代理|子 agent|子任务|sub\s?agent|spawn)",
    re.IGNORECASE,
)


def _mentions_sub_agent(text: str) -> bool:
    """Detect any mention of sub-agent / delegation intent.

    Three layers, ordered from cheap to expensive:
      1. Literal keywords (substring match)
      2. Verb+agent compound pattern (regex)
      3. Reject false positives like "agent 状态查询" by also checking
         that the matched "agent" is not in a read-only context.
    """
    if not text:
        return False
    lower = text.lower()
    if _contains(lower, _SUB_AGENT_KEYWORDS):
        return True
    if _SUB_AGENT_VERB_PATTERN.search(lower):
        return True
    return False


def is_pure_greeting(user_input: str) -> bool:
    """Return True if the message is a pure greeting/smalltalk with no task intent."""
    ui = user_input.strip().lower()
    pure = {
        "hello", "hi", "hey", "你好", "您好", "嗨", "在吗", "在不在",
        "thanks", "thank you", "谢谢", "ok", "好的", "嗯", "哦",
        "what's up", "whats up", "how are you", "howdy",
    }
    return ui in pure


def looks_like_tool_query(user_input: str) -> bool:
    """Check if the user message looks like it needs tool support."""
    keywords = (
        "translate", "config", "network", "ip", "port", "route", "vlan",
        "switch", "router", "firewall", "interface", "protocol", "ospf",
        "bgp", "hsrp", "vrrp", "stp", "lacp", "snmp", "syslog",
        "troubleshoot", "diagnose", "排查", "故障", "诊断",
        "knowledge", "search", "rag", "memory", "recall",
        "翻译", "配置", "网络", "设备", "接口", "路由",
        "查询", "搜索", "知识", "记忆", "文件", "制品",
        "weather", "天气", "新闻", "news", "预报", "forecast",
        "ping", "traceroute", "dns", "ssh", "telnet", "tcp", "udp",
        "dhcp", "nat", "vpn", "acl", "topology", "bandwidth", "latency",
        "检查", "查看", "分析", "扫描", "日志", "监控", "拓扑",
        "连通", "丢包", "延迟", "带宽",
    )
    ui = user_input.lower()
    return any(kw in ui for kw in keywords)


def is_tool_followup(user_msg: str) -> bool:
    text = (user_msg or "").strip().lower()
    if not text:
        return False
    markers = (
        "不对", "错了", "搞错", "调用有问题", "没调用", "没有调用",
        "继续", "再来", "重新", "重试", "有shell", "有 shell",
        "你肯定", "能显示", "刚才", "上一轮", "上一步",
        "wrong", "retry", "again", "continue", "use the tool",
        "用错了", "调错了", "不是这个工具", "换一个工具",
        "再试", "再调", "调用失败", "重来",
        "这个不行", "不行", "没有用", "没效果",
    )
    return any(marker in text for marker in markers)


def _detect_signals(text: str, session_context: dict | None = None) -> dict[str, bool]:
    """Detect user-intent signals from text. Extracted from tool_category_router.route_tool_scene."""
    lower = text.lower()
    session_context = session_context or {}

    mentions_file = _contains(text, (
        "上传", "文件", "workspace", "工作区", "日志", "读取", "路径",
        "config file", "pcap", "pcapng", "报文", "抓包", "pdf",
    ))
    mentions_file_implicit = _contains(text, (
        "这个配置", "这份配置", "这个文件", "这份文件", "上面的配置", "之前的配置",
        "那个配置", "那份配置", "刚才的配置", "已上传", "已导入",
        "这个日志", "这份日志", "上面的日志", "帮我看", "帮我分析",
        "看看这个", "看看这份", "看一下", "检查一下",
    ))
    mentions_image = _contains(text, (
        "图片", "图像", "截图", "照片", ".png", ".jpg", ".jpeg", ".gif", ".webp",
        "image.png", "image.jpg", "screenshot", "文件引用",
    ))
    mentions_network_specific = _contains(text, (
        "华三", "h3c", "cisco", "huawei", "juniper", "接口", "路由",
        "ospf", "bgp", "acl", "vlan", "nat", "防火墙",
        "network config", "running-config",
    ))
    mentions_network_analysis = _contains(text, (
        "分析", "检查", "有没有问题", "解析", "提取", "看看",
        "帮我看", "审查", "review", "analyze",
    ))
    mentions_config_translate = (
        _contains(text, ("翻译", "转换", "转成", "转为", "改成", "translate", "convert"))
        and _contains(text, ("配置", "config", "华三", "h3c", "cisco", "huawei", "juniper", "思科"))
    )
    mentions_packet = _contains(text, (
        "pcap", "pcapng", "报文", "抓包", "数据包", "五元组",
        "tcp流", "tcp 流", "seq", "ack", "重传", "乱序", "丢包",
        "sequence gap", "wireshark",
    ))
    mentions_knowledge = _contains(text, (
        "知识库", "knowledge", "rag", "资料库", "source", "chunk",
        "之前导入", "内部资料", "资料", "文档", "本地有", "有没有相关",
        "文件里", "导入的",
    ))
    mentions_search = _contains(text, (
        "查一下", "搜索一下", "找找", "看看有没有", "有没有什么", "搜索", "检索",
    ))
    mentions_host = _contains(text, (
        "本机", "localhost", "127.0.0.1", "ipconfig", "ifconfig", "route print",
        "netstat", "端口", "进程", "process", "shell", "powershell", "python", "os ",
        "ping", "traceroute", "nslookup", "dig", "curl", "wget", "system info",
        "系统信息", "系统状态", "磁盘", "内存", "cpu", "执行命令", "跑命令",
        "运行命令", "命令行", "终端",
    ))
    mentions_computation = _contains(text, (
        "python", "计算", "算一下", "统计", "95 分位", "95分位",
        "percentile", "脚本", "数据处理",
    ))
    is_definition_question = _contains(text, (
        "是什么", "什么是", "介绍", "解释", "说明", "what is", "define",
    ))

    effective_mentions_file = mentions_file or mentions_file_implicit

    return {
        "has_uploaded_files": False,
        "mentions_file": effective_mentions_file,
        "mentions_image": mentions_image,
        "mentions_network_config": (
            (not mentions_config_translate)
            and (not mentions_knowledge)
            and (not mentions_computation)
            and (
                (mentions_network_specific and mentions_network_analysis)
                or ("配置" in lower and mentions_network_analysis and not lower.startswith("读取 workspace"))
            )
            and not is_definition_question
        ),
        "mentions_config_translate": mentions_config_translate and not is_definition_question,
        "mentions_packet": mentions_packet,
        "mentions_report": _contains(text, (
            "报告", "整理", "输出", "markdown", "表格", "导出", "保存", "制品", "artifact",
        )),
        "mentions_web": (
            _contains(text, (
                "官方文档", "最新", "网页", "url", "http", "厂商文档", "手册",
                "docs", "documentation", "搜索引擎", "网上", "互联网", "上网", "查查",
                "新闻", "资讯", "最近发生", "热点",
            ))
            or (mentions_search and not mentions_knowledge)
        ),
        "mentions_weather": _contains(text, (
            "天气", "weather", "气温", "温度", "降雨", "下雨", "湿度",
            "风力", "台风", "晴", "阴", "多云", "紫外线", "空气质量",
            "aqi", "预报", "forecast",
        )),
        "mentions_knowledge": mentions_knowledge,
        "mentions_search": mentions_search,
        "mentions_host": mentions_host,
        "mentions_runtime": _contains(text, (
            "trace", "run", "session", "运行详情", "审计", "timeline", "checkpoint",
        )),
        "mentions_memory": (
            _contains(text, ("记住", "偏好", "profile", "remember", "memory", "记忆"))
        ),
        "mentions_sub_agent": _mentions_sub_agent(text),
    }


def classify_intent_profile(intent: str, user_input: str) -> dict:
    """Classify intent into profile flags (from prompts.py::classify_intent)."""
    profile = {
        "has_tools": False, "has_high_risk_tools": False,
        "has_knowledge": False, "is_network_task": False,
        "is_factual_query": False,
    }
    if not intent and not user_input:
        return profile

    combined = (intent + " " + user_input).lower()

    if intent in ("assistant_chat", "capability_discovery", "") and not any(
        kw in combined for kw in (
            "translate", "config", "network", "ip", "port", "device",
            "workspace", "file", "knowledge", "search", "rag", "memory",
            "diagnose", "troubleshoot", "排查", "翻译", "配置", "网络",
            "设备", "命令", "执行", "查询", "搜索", "知识", "文件",
            "检查", "查看", "分析", "扫描", "ping", "端口", "日志",
            "拓扑", "连通", "延迟", "proxy", "python", "shell",
            "pcap", "pcapng", "报文", "抓包", "重传", "乱序",
            "tool", "skill", "capability", "工具", "技能", "能力",
            "加载", "创建", "安装",
        )
    ):
        return profile

    if any(kw in combined for kw in (
        "ip", "os", "memory", "disk", "cpu", "version", "port", "route",
        "interface", "本机", "系统", "地址", "端口", "进程", "网卡",
    )):
        profile["is_factual_query"] = True

    if intent not in ("", "assistant_chat", "capability_discovery") or any(
        kw in combined for kw in (
            "translate", "config", "search", "workspace", "knowledge",
            "web", "memory", "artifact", "report", "shell", "python",
            "ip", "os", "port", "route", "interface", "version",
            "翻译", "搜索", "知识", "执行", "命令", "查询",
            "本机", "系统", "地址", "端口", "进程", "网卡", "report",
            "pcap", "pcapng", "报文", "抓包", "重传", "乱序",
            "tool", "skill", "capability", "工具", "技能", "能力",
            "加载", "创建", "安装",
        )
    ):
        profile["has_tools"] = True

    if any(kw in combined.split() for kw in (
        "shell", "python", "exec", "edit", "patch", "delete", "删除", "执行", "修改",
    )) or any(kw in combined for kw in ("本机", "系统", "命令", "端口", "进程")):
        profile["has_high_risk_tools"] = True

    if any(kw in combined for kw in (
        "knowledge", "search", "rag", "memory", "artifact",
        "workspace.file", "document", "知识", "搜索", "文件",
        "skill", "技能", "工具", "能力",
    )):
        profile["has_knowledge"] = True

    if any(kw in combined for kw in (
        "network", "config", "translate", "parser", "interface",
        "route", "vlan", "switch", "router", "firewall",
        "配置", "网络", "翻译", "路由", "接口",
        "pcap", "pcapng", "报文", "抓包",
    )):
        profile["is_network_task"] = True
        profile["has_tools"] = True

    return profile


def decide_scene(
    user_input: str,
    *,
    session_context: dict[str, Any] | None = None,
    previous_scene: dict[str, Any] | None = None,
    previous_rule_scene: dict[str, Any] | None = None,
    intent: str = "",
) -> SceneDecision:
    """Produce a unified SceneDecision for the current user turn.

    Consolidates greeting detection, tool-query detection, signal analysis,
    intent classification, and follow-up inheritance into a single decision
    object that downstream code can consume.
    """
    text = user_input or ""
    session_context = session_context or {}

    # ── Pure greeting / simple chat ───────────────────────────────
    if is_pure_greeting(text):
        return SceneDecision(
            user_input=text,
            intent="chat",
            is_simple_chat=True,
            needs_tool=False,
            primary_category="chat",
            reason="纯问候/寒暄，无需工具",
        )

    # ── Follow-up inheritance ─────────────────────────────────────
    followup_inherited = False
    if is_tool_followup(text) and isinstance(previous_scene, dict):
        followup_inherited = True

    # ── Signal detection ──────────────────────────────────────────
    signals = _detect_signals(text, session_context)

    # ── Intent profile (from classify_intent) ─────────────────────
    intent_profile = classify_intent_profile(intent, text)

    # ── Determine simple chat (no signals fired, no tool keywords) ─
    any_signal = any(v for k, v in signals.items() if k != "has_uploaded_files")
    is_tool_query = looks_like_tool_query(text)

    is_simple_chat = (
        not any_signal
        and not is_tool_query
        and not intent_profile["has_tools"]
        and not followup_inherited
    )

    if is_simple_chat:
        return SceneDecision(
            user_input=text,
            intent=intent or "chat",
            is_simple_chat=True,
            needs_tool=False,
            primary_category="chat",
            signals=signals,
            reason="简单聊天，无工具信号",
        )

    # ── Build categories and groups from signals ──────────────────
    categories: list[str] = []
    groups: dict[str, list[str]] = {}
    reasons: list[str] = []

    def _add_cat(cat: str):
        if cat not in categories:
            categories.append(cat)

    def _add_grp(cat: str, grp: str):
        _add_cat(cat)
        groups.setdefault(cat, [])
        if grp not in groups[cat]:
            groups[cat].append(grp)

    def include(cat: str, *grps: str):
        for g in grps:
            _add_grp(cat, g)

    if signals["mentions_host"]:
        include("host", "shell", "powershell", "python")
        include("runtime", "health")
        reasons.append("用户明确请求查看或操作当前本机环境")

    if signals["mentions_file"]:
        include("workspace", "file")
        reasons.append("用户涉及上传文件或 workspace 文件")

    if signals["mentions_network_config"] and not signals["mentions_knowledge"]:
        include("network", "config", "interface", "route")
        include("workspace", "file")
        reasons.append("用户请求离线网络配置分析")

    if signals["mentions_config_translate"] and not signals["mentions_knowledge"]:
        include("network", "config")
        include("workspace", "file")
        reasons.append("用户请求离线网络配置翻译")

    if signals["mentions_packet"] and not signals["mentions_knowledge"]:
        include("network", "pcap")
        include("workspace", "file")
        reasons.append("用户请求离线报文/PCAP 分析")

    if signals["mentions_web"]:
        include("web", "docs", "search", "page")
        reasons.append("用户请求官方文档或外部资料")

    if signals["mentions_weather"]:
        include("web", "weather")
        reasons.append("用户请求天气信息")

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

    if signals["mentions_sub_agent"]:
        include("agent", "subagent", "team", "role", "result")
        reasons.append("用户请求复杂/并行/委托式任务")

    # Default fallback: web.manage(action=search) ONLY if no categories detected
    # AND the user actually wants something tool-related.
    if not categories and (is_tool_query or intent_profile["has_tools"]):
        include("web", "search")
        reasons.append("默认使用低风险检索能力")

    # ── Primary category ──────────────────────────────────────────
    primary_category = _resolve_primary(signals, categories)

    # ── Task type flags ───────────────────────────────────────────
    decision = SceneDecision(
        user_input=text,
        intent=intent or ("chat" if is_simple_chat else primary_category),
        is_simple_chat=False,
        is_factual_query=intent_profile["is_factual_query"],
        is_network_task=intent_profile["is_network_task"] or signals.get("mentions_network_config", False) or signals.get("mentions_config_translate", False) or signals.get("mentions_packet", False),
        is_translation_task=signals.get("mentions_config_translate", False),
        is_file_task=signals.get("mentions_file", False),
        is_knowledge_task=signals.get("mentions_knowledge", False),
        is_memory_task=signals.get("mentions_memory", False),
        is_web_task=signals.get("mentions_web", False) or signals.get("mentions_weather", False),
        is_local_ops_task=signals.get("mentions_host", False),
        is_runtime_task=signals.get("mentions_runtime", False),
        is_report_task=signals.get("mentions_report", False),
        is_sub_agent_task=signals.get("mentions_sub_agent", False),
        needs_tool=intent_profile["has_tools"] or bool(categories),
        needs_context=intent_profile["has_knowledge"] or signals.get("mentions_knowledge", False),
        needs_memory=signals.get("mentions_memory", False),
        needs_knowledge=signals.get("mentions_knowledge", False),
        needs_file=signals.get("mentions_file", False),
        needs_web=signals.get("mentions_web", False) or signals.get("mentions_weather", False),
        needs_local_ops=signals.get("mentions_host", False),
        needs_sub_agent=signals.get("mentions_sub_agent", False),
        needs_clarification=False,
        primary_category=primary_category,
        categories=categories,
        groups=groups,
        signals=signals,
        reason="；".join(reasons) if reasons else "根据用户输入选择场景",
        warnings=[],
        followup_inherited=followup_inherited,
    )
    return decision


def _resolve_primary(signals: dict[str, bool], categories: list[str]) -> str:
    if signals.get("mentions_knowledge") and "knowledge" in categories:
        return "knowledge"
    if (signals.get("mentions_packet") or signals.get("mentions_config_translate")) and "network" in categories:
        return "network"
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
    return categories[0] if categories else "chat"
