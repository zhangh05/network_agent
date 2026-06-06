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
            result_dict = app.invoke(state)
            # LangGraph returns a dict; convert back
            state = NetworkAgentState(**{k: v for k, v in result_dict.items() if k in NetworkAgentState.__dataclass_fields__})
            state.runtime_mode = "langgraph"
        except Exception:
            state = _run_fallback(state)
    else:
        state = _run_fallback(state)

    result = state.tool_results or {}
    llm_ctx = state.context.get("llm", {})
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
        "workspace_id": state.workspace_id or "default",
        "workspace_updated": len(state.tool_calls) > 0,
        "llm": {
            "enabled": llm_ctx.get("enabled", False),
            "used": llm_ctx.get("used", False),
            "provider": llm_ctx.get("provider"),
            "model": llm_ctx.get("model"),
            "task": llm_ctx.get("task"),
            "policy_pass": llm_ctx.get("policy_pass"),
            "fallback_reason": llm_ctx.get("fallback_reason"),
        },
    }


def get_runtime_status() -> dict:
    """Report agent runtime status."""
    import json, os, traceback

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

    # Check LangGraph availability and compile status
    graph_compile_ok = False
    fallback_reason = None
    graph_nodes = []
    if _LANGGRAPH_AVAILABLE:
        try:
            app = _build_langgraph()
            graph_nodes = list(app.get_graph().nodes.keys())
            graph_compile_ok = True
        except Exception as e:
            fallback_reason = f"compile_failed: {traceback.format_exception_only(e)[-1].strip()}"
    else:
        fallback_reason = "langgraph_import_failed"

    from agent.llm.runtime import get_llm_status
    llm_status = get_llm_status()

    from agent.nodes.intent_router import INTENTS

    return {
        "agent_runtime": "langgraph" if _LANGGRAPH_AVAILABLE and graph_compile_ok else "fallback",
        "langgraph_available": _LANGGRAPH_AVAILABLE,
        "fallback_available": True,
        "graph_compile_ok": graph_compile_ok,
        "graph_nodes": graph_nodes,
        "fallback_reason": fallback_reason,
        "llm_enabled": llm_status["enabled"],
        "llm_connected": llm_status["connected"],
        "llm_provider": llm_status["provider"],
        "llm_model": llm_status["model"],
        "llm_safe_mode": llm_status["safe_mode"],
        "llm_allowed_tasks": llm_status["allowed_tasks"],
        "llm_blocked_tasks": llm_status["blocked_tasks"],
        "llm_config_source": llm_status["config_source"],
        "llm_policy_red_lines": llm_status["red_lines"],
        "supported_intents": list(INTENTS.keys()),
        "enabled_skills": enabled_skills,
        "enabled_modules": enabled_modules,
    }
