# agent/nodes/intent_router.py
"""Intent router — keyword-based intent inference.

Router ONLY identifies intent from user input.
Module/Skill mapping is ENTIRELY from registry capabilities.
# Router uses registry capabilities exclusively for module/skill resolution.
"""

from agent.state import NetworkAgentState

# Keyword patterns for intent inference only — NO module/skill mapping
INTENTS = {
    "translate_config": ["翻译", "translate", "转换", "config", "配置", "cisco", "huawei", "h3c", "ruijie", "juniper"],
    "topology_draw": ["拓扑", "topology", "网络图", "network map"],
    "inspection_analyze": ["巡检", "检查", "inspection", "audit", "合规", "diagnose"],
    "knowledge_search": ["知识", "knowledge", "文档", "documentation", "搜索"],
    "memory_search": ["记忆", "memory", "回忆", "会话", "history"],
    "skill_query": ["技能", "skill", "能力"],
    "module_query": ["模块", "module"],
    "context_qa": ["刚才", "为什么", "解释", "说明", "复核", "人工", "风险", "这些", "上次", "怎么", "如何", "是什么"],
    "assistant_chat": ["你好", "hello", "hi", "你是谁", "help", "帮助", "能做", "可以做什么", "bye", "再见", "谢谢", "thank"],
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
    live = cap_status == "enabled"

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
    for intent, keywords in INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            return intent
    return "unknown"
