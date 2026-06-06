# agent/graph.py
"""Agent orchestrator — LangGraph workflow with fallback to deterministic pipeline."""

from agent.state import NetworkAgentState

# Try LangGraph; fall back to deterministic pipeline if unavailable
_LANGGRAPH_AVAILABLE = False
try:
    from langgraph.graph import StateGraph, END  # noqa
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    pass


def _build_langgraph():
    """Build LangGraph StateGraph."""
    from langgraph.graph import StateGraph, END
    from agent.nodes.intent_router import route
    from agent.nodes.context_loader import load_context
    from agent.nodes.planner import plan
    from agent.nodes.skill_executor import execute
    from agent.nodes.verifier import verify
    from agent.nodes.composer import compose
    from agent.nodes.memory_writer import write_memory

    workflow = StateGraph(NetworkAgentState)
    workflow.add_node("router", route)
    workflow.add_node("context", load_context)
    workflow.add_node("planner", plan)
    workflow.add_node("executor", execute)
    workflow.add_node("verifier", verify)
    workflow.add_node("composer", compose)
    workflow.add_node("memory", write_memory)

    workflow.set_entry_point("router")
    workflow.add_edge("router", "context")
    workflow.add_edge("context", "planner")
    workflow.add_edge("planner", "executor")
    workflow.add_edge("executor", "verifier")
    workflow.add_edge("verifier", "composer")
    workflow.add_edge("composer", "memory")
    workflow.add_edge("memory", END)

    return workflow.compile()


def _run_fallback(state: NetworkAgentState) -> NetworkAgentState:
    """Deterministic fallback pipeline."""
    from agent.nodes.intent_router import route
    from agent.nodes.context_loader import load_context
    from agent.nodes.planner import plan
    from agent.nodes.skill_executor import execute
    from agent.nodes.verifier import verify
    from agent.nodes.composer import compose
    from agent.nodes.memory_writer import write_memory

    state = route(state)
    if state.error and state.intent == "unknown":
        state.final_response = "I didn't understand your request."
        return state

    state = load_context(state)
    state = plan(state)
    state = execute(state)
    state = verify(state)
    state = compose(state)
    state = write_memory(state)
    state.runtime_mode = "fallback"
    return state


def run_agent(user_input: str = "", intent: str = "", payload: dict = None,
              workspace_id: str = "default") -> dict:
    """Run agent pipeline and return full result dict."""
    state = NetworkAgentState(
        user_input=user_input,
        intent=intent,
        payload=payload or {},
        workspace_id=workspace_id,
    )

    if _LANGGRAPH_AVAILABLE:
        try:
            app = _build_langgraph()
            state = app.invoke(state)
            state.runtime_mode = "langgraph"
        except Exception:
            state = _run_fallback(state)
    else:
        state = _run_fallback(state)

    result = state.tool_results or {}
    return {
        "ok": state.error is None,
        "request_id": state.request_id,
        "intent": state.intent,
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "runtime_mode": state.runtime_mode,
        "result": result,
        "verification": state.verification,
        "warnings": state.warnings,
        "final_response": state.final_response,
        "memory_written": len(state.tool_calls) > 0,
    }


def get_runtime_status() -> dict:
    """Report agent runtime status."""
    import json, os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        with open(os.path.join(root, "skills", "registry.json"), encoding="utf-8") as f:
            skills = json.load(f)
        enabled_skills = [s["skill_name"] for s in skills["skills"] if s.get("enabled")]
    except Exception:
        enabled_skills = []

    try:
        with open(os.path.join(root, "modules", "registry.json"), encoding="utf-8") as f:
            modules = json.load(f)
        enabled_modules = [m["module_name"] for m in modules["modules"] if m.get("status") == "enabled"]
    except Exception:
        enabled_modules = []

    from agent.nodes.intent_router import INTENTS

    return {
        "agent_runtime": "langgraph" if _LANGGRAPH_AVAILABLE else "fallback",
        "fallback_available": True,
        "llm_connected": False,
        "llm_provider": None,
        "supported_intents": list(INTENTS.keys()),
        "enabled_skills": enabled_skills,
        "enabled_modules": enabled_modules,
    }
