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
    "context_qa": ["刚才", "为什么", "解释", "说明", "复核", "人工", "风险", "这些", "上次"],
}

LIVE_INTENTS = {"translate_config", "context_qa"}


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

    state.active_module = _module_for(state.intent)
    state.selected_skill = _skill_for(state.intent)

    if state.intent not in LIVE_INTENTS:
        state.warnings.append(f"Intent '{state.intent}' is planned (coming_soon)")
        state.plan = ["report_coming_soon"]
    else:
        state.plan = ["load_context", "plan_steps", "execute_skill", "verify_result", "compose_response", "write_memory"]

    return state


def _infer(text: str) -> str:
    text_lower = text.lower()
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
