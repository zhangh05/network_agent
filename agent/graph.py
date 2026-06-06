# agent/graph.py
"""Agent orchestrator — LangGraph workflow with fallback to deterministic pipeline."""

import time
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
    """Deterministic fallback pipeline with trace instrumentation."""
    from agent.nodes.intent_router import route
    from agent.nodes.context_loader import load_context
    from agent.nodes.planner import plan
    from agent.nodes.skill_executor import execute
    from agent.nodes.verifier import verify
    from agent.nodes.composer import compose
    from agent.nodes.memory_writer import write_memory

    _run_node(state, "router", route)
    if state.error and state.intent == "unknown":
        state.final_response = "I didn't understand your request."
        return state

    _run_node(state, "context_loader", load_context)
    _run_node(state, "planner", plan)
    _run_node(state, "executor", execute)
    _run_node(state, "verifier", verify)
    _run_node(state, "composer", compose)
    _run_node(state, "memory_writer", write_memory)
    state.runtime_mode = "fallback"
    return state


def _run_node(state, node_name, func):
    """Run a node function with trace timing."""
    start = time.time()
    try:
        state = func(state)
        status = "success"
    except Exception as e:
        status = "failed"
        if not state.error:
            state.error = str(e)
    duration = round((time.time() - start) * 1000, 2)

    state.node_timings[node_name] = duration
    state.trace_events.append({
        "event_id": node_name,
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": "node_end",
        "name": node_name,
        "status": status,
        "duration_ms": duration,
        "summary": f"{node_name}: {status} ({duration}ms)",
        "metadata": {},
        "redaction_applied": False,
    })
    return state


def run_agent(user_input: str = "", intent: str = "", payload: dict = None,
              workspace_id: str = "default") -> dict:
    """Run agent pipeline and return full result dict with metadata + trace."""
    payload = payload or {}
    context_ref = payload.pop("context_ref", "")

    state = NetworkAgentState(
        user_input=user_input,
        intent=intent,
        payload=payload,
        workspace_id=workspace_id,
    )

    if context_ref:
        state.context["context_ref"] = context_ref

    # ═══ Create trace ═══
    from observability.trace import create_trace, finalize_trace
    trace_id = create_trace(state, workspace_id)

    # ═══ Run pipeline ═══
    if _LANGGRAPH_AVAILABLE:
        try:
            app = _build_langgraph()
            result_dict = app.invoke(state)
            state = NetworkAgentState(**{
                k: v for k, v in result_dict.items()
                if k in NetworkAgentState.__dataclass_fields__
            })
            state.runtime_mode = "langgraph"
        except Exception:
            state = _run_fallback(state)
    else:
        state = _run_fallback(state)

    # ═══ Finalize & persist trace ═══
    try:
        trace = finalize_trace(state, workspace_id)
        from observability.store import write_trace
        write_trace(trace, workspace_id)
    except Exception:
        pass

    result = state.tool_results or {}
    llm_ctx = state.context.get("llm", {})
    timeline = {
        "total_duration_ms": sum(state.node_timings.values()),
        "node_count": len(state.node_timings),
        "skill_call_count": state.context.get("skill_call_count", 0),
        "module_call_count": state.context.get("module_call_count", 0),
        "llm_call_count": 1 if llm_ctx.get("used") else 0,
        "memory_write_count": 1 if state.context.get("memory_written") else 0,
        "warning_count": len(state.warnings),
        "error_count": 1 if state.error else 0,
    }

    return {
        "ok": state.error is None,
        "run_id": state.request_id,
        "request_id": state.request_id,
        "intent": state.intent,
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "runtime_mode": state.runtime_mode,
        "result": result,
        "verification": state.verification,
        "warnings": state.warnings,
        "final_response": state.final_response,
        "workspace_id": state.workspace_id or "default",
        "memory_written": state.context.get("memory_written", False),
        "workspace_updated": state.context.get("workspace_updated", False),
        "memory_hits_count": len(state.context.get("memory_hits", [])),
        "artifacts": [],
        # ── Trace ──
        "trace_id": trace_id,
        "trace_available": True,
        "timeline_summary": timeline,
        # ── LLM ──
        "llm": {
            "enabled": llm_ctx.get("enabled", False),
            "used": llm_ctx.get("used", False),
            "provider": llm_ctx.get("provider"),
            "model": llm_ctx.get("model"),
            "task": llm_ctx.get("task"),
            "config_source": llm_ctx.get("config_source", "default"),
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
