# agent/nodes/intent_router.py
"""Intent router — keyword-based intent inference.

Router ONLY identifies intent from user input.
Module/Skill mapping is ENTIRELY from registry capabilities.
# Router uses registry capabilities exclusively for module/skill resolution.
"""

from agent.state import NetworkAgentState

# Keyword patterns for intent inference only — NO module/skill mapping
# Order matters: first match wins.
#
# translate_config now uses a two-tier approach:
#   Tier 1 (explicit intent): user says "翻译" / "translate" → direct match
#   Tier 2 (config detection): message looks like a config block → fallback match
# This prevents casual questions about "interface" or "vlan" from routing
# to config translation.
INTENTS = {
    "translate_config": [
        # Tier 1 — explicit translation intent
        "翻译", "translate", "转换", "翻译成", "转成",
        "帮我翻译", "翻译一下", "翻译这段", "翻译这个",
        "convert to", "translate to",
    ],
    "topology_draw": ["拓扑", "topology", "网络图", "network map"],
    "inspection_analyze": ["巡检", "inspection", "audit", "合规", "diagnose"],
    "knowledge_query": [
        # 明确提到知识库/资料/文档
        "知识库", "资料库", "资料", "文档", "文件", "上传",
        "查一下", "找一下", "搜索", "搜一下", "检索",
        # 在知识库/资料里查找
        "书里", "资料里", "文档里", "知识里", "库里",
        "之前上传", "上传的", "那个文件", "那些资料",
        "根据知识", "根据资料", "根据文档",
        "这个报告", "那个报告", "报告里说了", "报告里有什么",
        "artifact里", "artifact 里",
        # 明确说查/搜 + 主题
        "有没有关于", "有没有提到", "有没有讲到",
        "提到了吗", "提到过吗",
        "有没有相关资料", "相关资料",
        # 知识主题关键词(含上下文)
        "联软准入", "cucm", "cu cm", "nat ",
        "网络准入", "准入方案", "准入策略",
    ],
    "memory_search": ["记忆", "memory_recall", "回忆"],
    "skill_query": ["技能", "skill", "能力"],
    "module_query": ["模块", "module"],
    # assistant_chat MUST come before context_qa to catch open questions
    "assistant_chat": [
        "你好", "hello", "hi", "你是谁", "你是什么", "什么模型", "模型",
        "model", "help", "帮助", "能做", "可以做什么", "bye", "再见", "谢谢", "thank",
        "状态", "健康", "后端", "连接", "端口", "地址", "llm", "大模型",
        "天气", "新闻", "股票", "实时", "最新", "闲聊", "聊天",
        "随便", "怎么看", "觉得", "你认为", "聊聊",
    ],
    # context_qa: only result/explanation queries with explicit context reference
    "context_qa": [
        "刚才运行", "上次运行", "上次翻译", "上一次结果",
        "为什么有 warning", "为什么有风险",
        "翻译结果怎么看", "转换结果怎么", "解释上次",
        "manual_review是什么", "quality_summary是什么",
        "source_residue是什么", "silent_drop是什么",
    ],
}


def route(state: NetworkAgentState) -> NetworkAgentState:
    """Determine intent. Module/skill/capability all from registry."""
    explicit = (state.intent or "").strip()
    if explicit in INTENTS:
        state.intent = explicit
    elif explicit:
        state.intent = "unknown"
        state.error = f"unsupported intent: {explicit}"
        state.context["capability_status"] = "unknown"
        state.context["capability_id"] = ""
        state.active_module = "unknown"
        state.selected_skill = "unknown"
    else:
        state.intent = _infer(state.user_input or "")

    # ── Look up capability from registry ──
    _resolve_capability(state)

    # ── Determine liveness ──
    cap_status = state.context.get("capability_status", "unknown")
    live = cap_status in ("enabled", "builtin")

    # ── Trace: intent_routed ──
    state.trace_events.append({
        "event_id": "intent_routed",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": "intent_routed",
        "name": "intent_routed",
        "status": "success",
        "duration_ms": 0.0,
        "summary": f"intent={state.intent} capability={state.context.get('capability_id','?')} module={state.active_module}",
        "metadata": {
            "intent": state.intent,
            "capability_id": state.context.get("capability_id", ""),
            "capability_status": cap_status,
            "active_module": state.active_module,
            "selected_skill": state.selected_skill,
        },
        "redaction_applied": False,
    })

    if not live:
        state.warnings.append(f"Intent '{state.intent}' is planned (coming_soon)")
        state.plan = ["report_coming_soon"]
        _add_warning_event(state, f"intent_planned: {state.intent}")
    else:
        state.plan = [
            "load_context", "plan_steps", "execute_skill",
            "verify_result", "compose_response", "write_memory",
        ]

    return state


def _resolve_capability(state: NetworkAgentState):
    """Resolve intent → capability via registry. Sets active_module/selected_skill/capability_id."""
    if state.intent == "assistant_chat":
        state.active_module = "assistant"
        state.selected_skill = "assistant_chat"
        state.context["capability_id"] = "assistant.chat"
        state.context["capability_status"] = "builtin"
        return

    if state.intent == "knowledge_query":
        state.active_module = "knowledge"
        state.selected_skill = "knowledge_query"
        state.context["capability_id"] = "knowledge.query"
        state.context["capability_status"] = "builtin"
        return

    try:
        from registry.loader import load_capabilities
        caps = load_capabilities()

        # Try enabled first, then planned
        for cap in caps:
            if cap.intent == state.intent and cap.is_enabled():
                _apply_capability(state, cap, "enabled")
                return

        for cap in caps:
            if cap.intent == state.intent and cap.status == "planned":
                _apply_capability(state, cap, "planned")
                return

        # For context_qa: if no explicit capability found, try config.review
        if state.intent == "context_qa":
            from registry.loader import get_capability
            cap = get_capability("config.review")
            if cap and cap.status == "enabled":
                _apply_capability(state, cap, "enabled")
                return

        # Fallback: unknown module from intent name
        state.active_module = f"unknown_{state.intent}"
        state.selected_skill = f"unknown_{state.intent}"
        state.context["capability_id"] = ""
        state.context["capability_status"] = "unknown"

    except Exception:
        state.context["capability_status"] = "registry_unavailable"


def _apply_capability(state, cap, status):
    """Apply a capability to state."""
    state.context["capability_id"] = cap.capability_id
    state.context["capability_status"] = status
    state.active_module = cap.module
    state.selected_skill = cap.skill

    # For context_qa, preserve last active module
    if state.intent == "context_qa":
        try:
            from workspace.manager import get_workspace_state
            ws = get_workspace_state(state.workspace_id or "default")
            last_module = ws.get("last_active_module", "")
            if last_module and last_module != "unknown":
                state.active_module = last_module
        except Exception:
            pass


def _add_warning_event(state, msg):
    state.trace_events.append({
        "event_id": f"warn_{len(state.trace_events)}",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": "warning",
        "name": "warning",
        "status": "skipped",
        "duration_ms": 0.0,
        "summary": msg,
        "metadata": {},
        "redaction_applied": False,
    })


def _infer(text: str) -> str:
    text_lower = text.lower()
    # Root-level pre-check: exact-match greetings only
    # "hi" matched "this" before, so we check hi with word boundaries
    text_lower = text.lower().strip()
    is_greeting = (
        text_lower in ("你好", "hello", "hi", "hey", "嗨")
        or text_lower.startswith(("你好", "hello ", "hi ", "hey ", "嗨 "))
    )
    if is_greeting:
        return "assistant_chat"

    # Context QA: result/explanation queries
    _context_words = [
        "该怎么看", "怎么看结果", "翻译结果怎么看", "怎么看翻译结果",
        "结果怎么看", "怎么看上次", "上次翻译怎么看", "解释上次",
        "有什么风险", "风险是什么", "刚才的结果", "刚才结果",
        "这次", "上次", "刚才", "结果",
    ]
    _ctx_term_explain = [
        "manual_review是什么", "quality_summary是什么",
        "source_residue是什么", "silent_drop是什么",
        "manual_review 是什么", "quality_summary 是什么",
        "source_residue 是什么", "silent_drop 是什么",
    ]
    if any(kw in text_lower for kw in _context_words):
        return "context_qa"
    if any(kw in text_lower for kw in _ctx_term_explain):
        return "context_qa"

    # General platform questions → assistant_chat
    if (
        any(kw in text_lower for kw in ["模型", "llm", "大模型", "memory", "记忆", "历史", "状态", "健康"])
        and not any(kw in text_lower for kw in ["配置翻译", "翻译配置", "source_config", "deployable_config"])
    ):
        return "assistant_chat"

    # Knowledge query: explicit catalog/document search words
    _knowledge_context = [
        "知识库", "资料库", "资料", "文档", "上传", "文件",
        "查一下", "找一下", "搜索", "搜一下", "检索",
        "资料里", "文档里", "知识里", "库里", "书里",
        "之前上传", "上传的", "那个文件", "那些资料",
        "根据知识", "根据资料", "根据文档",
        "这个报告", "那个报告", "报告里", "artifact",
        "有没有关于", "有没有提到", "有没有讲到",
        "提到了吗", "提到过吗", "相关资料",
    ]
    if any(kw in text_lower for kw in _knowledge_context):
        return "knowledge_query"

    # Iterate INTENTS for explicit matches (translate_config etc.)
    for intent, keywords in INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            return intent

    # Tier 2 config detection: message looks like a config block
    if _looks_like_config(text):
        return "translate_config"

    # Question marks → assistant_chat
    if text_lower.endswith(("?", "？", "吗", "呢")):
        return "assistant_chat"

    return "assistant_chat"


# ═══════════════ Config Text Detection ═══════════════

_CONFIG_SIGNALS = [
    # Interface patterns
    r'interface\s+\S+', r'gigabitethernet', r'fastethernet',
    r'\S+ethernet', r'serial\s+\S', r'loopback\s+\d',
    # Config commands
    r'ip\s+address\s+\d+\.\d+\.\d+\.\d+', r'no\s+shutdown',
    r'undo\s+shutdown', r'shutdown',
    # Routing
    r'router\s+(ospf|bgp|isis|eigrp|rip)\s+\d+',
    r'network\s+\d+\.\d+\.\d+\.\d+',
    # VLAN
    r'vlan\s+\d+', r'vlan\s+batch', r'access-list\s+\d+',
    r'prefix-list\s+\S+', r'route-map\s+\S+',
    # System config
    r'hostname\s+\S+', r'sysname\s+\S+', r'snmp-server\s+\S+',
    r'ntp\s+server', r'logging\s+\S+', r'banner\s+\S+',
    r'line\s+vty\s+\d+',
    # ACL
    r'^\s*(permit|deny)\s+(ip|tcp|udp|icmp)',
]

import re as _re

_CONFIG_SIGNAL_RE = [_re.compile(p, _re.I | _re.M) for p in _CONFIG_SIGNALS]


def _looks_like_config(text: str) -> bool:
    """Check if text looks like a network device config block.

    Returns True if enough config signal patterns match,
    indicating the user pasted a config rather than chatting.
    """
    if not text or len(text) < 20:
        return False

    lines = text.strip().split('\n')

    # Too short for config
    if len(lines) < 3:
        return False

    # Count matching signals
    signal_count = 0
    for pattern in _CONFIG_SIGNAL_RE:
        if pattern.search(text):
            signal_count += 1
            if signal_count >= 3:  # Need 3+ signals to be confident
                return True

    # Density check: if it has many config-like lines
    if len(lines) >= 10:
        config_lines = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('!') or stripped.startswith('#'):
                continue
            # Check if line looks like a config command
            if any(pattern.search(stripped) for pattern in _CONFIG_SIGNAL_RE):
                config_lines += 1
        # At least 30% of non-empty lines look like config
        non_empty = [l for l in lines if l.strip() and not l.strip().startswith(('!', '#'))]
        if non_empty and config_lines / len(non_empty) >= 0.3:
            return True

    return False
