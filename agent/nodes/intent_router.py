# agent/nodes/intent_router.py
"""Intent router — keyword-based intent inference.

Router ONLY identifies intent from user input.
Module/Skill mapping is ENTIRELY from registry capabilities.
# Router uses registry capabilities exclusively for module/skill resolution.
"""

from agent.state import NetworkAgentState

# Keyword patterns for intent inference only — NO module/skill mapping
# Order matters: first match wins. assistant_chat before context_qa prevents
# open questions like "天气如何" from being misrouted as result explanations.
INTENTS = {
    "translate_config": ["翻译", "translate", "转换", "cisco", "huawei", "h3c", "ruijie", "juniper"],
    "topology_draw": ["拓扑", "topology", "网络图", "network map"],
    "inspection_analyze": ["巡检", "inspection", "audit", "合规", "diagnose"],
    "knowledge_search": ["知识", "knowledge", "文档", "documentation", "搜索"],
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
    # context_qa: only result/explanation/review queries (NOT general chat)
    "context_qa": [
        "刚才运行", "上次运行", "上次翻译", "上一次结果",
        "manual_review", "quality_summary", "source_residue", "silent_drop",
        "为什么有 warning", "为什么有风险", "复核", "人工",
        "翻译结果怎么看", "转换结果怎么", "解释上次",
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
        return state
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
    assistant_first = [
        "你好", "hello", "hi", "你是谁", "你是什么", "什么模型",
        "你用什么模型", "你是什么模型", "what model", "which model",
        "who are you", "what are you", "你能做什么", "你会什么",
        "可以做什么", "怎么用", "帮助", "help", "当前状态", "系统状态",
        "健康状态", "后端状态", "连接状态", "端口", "登录地址",
        "llm配置", "大模型配置", "memory怎么回事", "记忆怎么回事",
        "历史怎么回事", "run history",
    ]
    if any(kw in text_lower for kw in assistant_first):
        return "assistant_chat"
    # Context QA: result/explanation queries — check BEFORE translate_config
    if any(kw in text_lower for kw in
           ["该怎么看", "怎么看结果", "翻译结果怎么看", "怎么看翻译结果",
            "结果怎么看", "怎么看上次", "上次翻译怎么看", "解释上次",
            "有什么风险", "风险是什么", "刚才的结果", "刚才结果",
            "复核", "人工", "warning", "warnings"]):
        return "context_qa"
    if (
        any(kw in text_lower for kw in ["模型", "llm", "大模型", "memory", "记忆", "历史", "状态", "健康"])
        and not any(kw in text_lower for kw in ["配置翻译", "翻译配置", "source_config", "deployable_config"])
    ):
        return "assistant_chat"
    for intent, keywords in INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            return intent
    if text_lower.endswith(("?", "？", "吗", "呢")):
        return "assistant_chat"
    # Default: anything not matching a business intent is assistant chat
    return "assistant_chat"
