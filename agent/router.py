# agent/router.py
"""Intent router — maps user intent to module/skill."""

from agent.state import NetworkAgentState

_SUPPORTED_INTENTS = {
    "translate_config": "config_translation",
    "topology_draw": "topology",
    "inspection_analyze": "inspection",
    "knowledge_search": "knowledge_base",
    "memory_search": "memory",
}

_LIVE_INTENTS = {"translate_config"}


def route(state: NetworkAgentState) -> NetworkAgentState:
    """Determine intent and active module from user_input."""
    intent = (state.intent or _infer_intent(state.user_input)).strip()

    if not intent or intent not in _SUPPORTED_INTENTS:
        state.error = f"unsupported intent: {intent or 'empty'}"
        state.done = False
        return state

    state.intent = intent
    state.active_module = _SUPPORTED_INTENTS[intent]

    if intent not in _LIVE_INTENTS:
        state.error = f"Intent '{intent}' is planned (coming_soon)"
        state.final_response = f"Module '{state.active_module}' is planned but not yet implemented."
        state.done = True
        return state

    return state


def _infer_intent(user_input: str) -> str:
    """Simple keyword-based intent inference."""
    text = user_input.lower()
    if any(kw in text for kw in ("翻译", "translate", "转换", "config", "配置")):
        return "translate_config"
    if any(kw in text for kw in ("拓扑", "topology", "网络图")):
        return "topology_draw"
    if any(kw in text for kw in ("巡检", "检查", "inspection", "audit", "合规")):
        return "inspection_analyze"
    if any(kw in text for kw in ("知识", "knowledge", "文档")):
        return "knowledge_search"
    return "unknown"
