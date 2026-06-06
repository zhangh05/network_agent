# agent/nodes/intent_router.py
"""Intent router — classifies user message into an intent."""

from agent.state import NetworkAgentState

INTENTS = {
    "translate_config": ["翻译", "translate", "转换", "config", "配置", "cisco", "huawei", "h3c", "ruijie", "juniper"],
    "topology_draw": ["拓扑", "topology", "网络图", "network map"],
    "inspection_analyze": ["巡检", "检查", "inspection", "audit", "合规", "diagnose"],
    "knowledge_search": ["知识", "knowledge", "文档", "documentation", "搜索"],
    "memory_search": ["记忆", "memory", "回忆", "会话", "history"],
    "skill_query": ["技能", "skill", "能力"],
    "module_query": ["模块", "module"],
    "context_qa": ["刚才", "为什么", "解释", "说明", "复核", "人工", "风险", "这些", "上次", "怎么", "如何", "是什么"],
}

LIVE_INTENTS = {"translate_config", "context_qa"}

# Local intent capability map — fallback when registry unavailable
_INTENT_CAPABILITY_MAP = {
    "translate_config": "config.translate",
    "context_qa": "config.review",
}


def route(state: NetworkAgentState) -> NetworkAgentState:
    """Determine intent from user_input or explicit intent."""
    # Explicit intent takes priority
    explicit = (state.intent or "").strip()
    if explicit in INTENTS:
        state.intent = explicit
    elif explicit:
        state.intent = "unknown"
        state.error = f"unsupported intent: {explicit}"
        return state
    else:
        state.intent = _infer(state.user_input or "")

    # Set active_module and selected_skill
    state.active_module = _module_for(state.intent)
    state.selected_skill = _skill_for(state.intent)

    # ── Map intent → capability_id via registry ──
    try:
        from registry.loader import load_capabilities
        caps = load_capabilities()
        for cap in caps:
            if cap.intent == state.intent and cap.is_enabled():
                state.context["capability_id"] = cap.capability_id
                state.active_module = cap.module
                state.selected_skill = cap.skill
                break
    except Exception:
        pass

    # For context_qa, keep the module from last run
    if state.intent == "context_qa":
        try:
            from workspace.manager import get_workspace_state
            ws = get_workspace_state(state.workspace_id or "default")
            last_module = ws.get("last_active_module", "")
            if last_module and last_module != "unknown":
                state.active_module = last_module
                state.selected_skill = _skill_for(ws.get("last_intent", "")) or "config_translation"
        except Exception:
            pass

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
        "summary": f"intent={state.intent} module={state.active_module}",
        "metadata": {"intent": state.intent, "active_module": state.active_module, "selected_skill": state.selected_skill},
        "redaction_applied": False,
    })

    # Set plan based on liveness
    if state.intent not in LIVE_INTENTS:
        state.warnings.append(f"Intent '{state.intent}' is planned (coming_soon)")
        state.plan = ["report_coming_soon"]
        _add_warning_event(state, f"intent_planned: {state.intent}")
    else:
        state.plan = [
            "load_context", "plan_steps", "execute_skill",
            "verify_result", "compose_response", "write_memory",
        ]

    return state


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
    """Infer intent from keywords. Follow-up keywords → context_qa."""
    text_lower = text.lower()

    # Check each intent category
    for intent, keywords in INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            return intent
    return "unknown"


def _module_for(intent: str) -> str:
    mapping = {
        "translate_config": "config_translation",
        "topology_draw": "topology",
        "inspection_analyze": "inspection",
        "knowledge_search": "knowledge_base",
        "memory_search": "memory",
        "skill_query": "skills",
        "module_query": "modules",
        "context_qa": "config_translation",  # default to last active
    }
    return mapping.get(intent, "unknown")


def _skill_for(intent: str) -> str:
    mapping = {
        "translate_config": "config_translation",
        "topology_draw": "topology_draw",
        "inspection_analyze": "inspection_analyze",
        "knowledge_search": "knowledge_search",
    }
    return mapping.get(intent)
