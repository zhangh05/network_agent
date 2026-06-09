# agent/graph.py
"""Agent orchestrator — LangGraph workflow with fallback to deterministic pipeline.

Both LangGraph and fallback runtimes share a unified trace wrapper (wrap_trace_node)
that guarantees every node records node_start / node_end / duration_ms.
"""

import time
from agent.state import NetworkAgentState

# Try LangGraph; fall back to deterministic pipeline if unavailable
_LANGGRAPH_AVAILABLE = False
try:
    from langgraph.graph import StateGraph, END  # noqa
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    pass

# Canonical 7 nodes (name, display_name)
_CANONICAL_NODES = [
    ("router", "router"),
    ("context", "context_loader"),
    ("planner", "planner"),
    ("executor", "executor"),
    ("verifier", "verifier"),
    ("composer", "composer"),
    ("memory", "memory_writer"),
]


def _add_trace_event(state: NetworkAgentState, event_type: str, name: str,
                     status: str = "started", duration_ms: float = 0.0,
                     summary: str = "", metadata: dict = None):
    """Append a trace event to state. All events go through this helper."""
    state.trace_events.append({
        "event_id": f"{name}_{event_type}",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": event_type,
        "name": name,
        "status": status,
        "duration_ms": duration_ms,
        "summary": summary or f"{event_type}: {name}",
        "metadata": metadata or {},
        "redaction_applied": False,
    })


def wrap_trace_node(node_name: str, display_name: str):
    """Create a trace-wrapped node function for LangGraph.

    Returns a callable suitable for StateGraph.add_node().
    Records node_start before execution and node_end after.

    Args:
        node_name: Internal key (e.g. "router", "context")
        display_name: Human-readable name for trace (e.g. "router", "context_loader")
    """

    def _load_func():
        # Lazy import to avoid circular dependency
        mapping = {
            "router": ("agent.nodes.intent_router", "route"),
            "context": ("agent.nodes.context_loader", "load_context"),
            "planner": ("agent.nodes.planner", "plan"),
            "orchestrator": ("agent.nodes.llm_orchestrator", "orchestrate"),
            "executor": ("agent.nodes.skill_executor", "execute"),
            "verifier": ("agent.nodes.verifier", "verify"),
            "composer": ("agent.nodes.composer", "compose"),
            "memory": ("agent.nodes.memory_writer", "write_memory"),
        }
        mod_name, func_name = mapping[node_name]
        import importlib
        mod = importlib.import_module(mod_name)
        return getattr(mod, func_name)

    func = _load_func()

    def traced(state: NetworkAgentState) -> NetworkAgentState:
        # Record node_start
        _add_trace_event(state, "node_start", display_name, status="started",
                         summary=f"{display_name} started")

        start = time.time()
        try:
            result = func(state)
            status = "success"
        except Exception as e:
            status = "failed"
            if not state.error:
                state.error = str(e)
            _add_trace_event(state, "error", display_name, status="failed",
                             metadata={"error": str(e)[:200]})
            # Re-raise so LangGraph can handle it
            raise

        duration = round((time.time() - start) * 1000, 2)
        state.node_timings[display_name] = duration

        # Build metadata from state after node execution
        meta = {}
        if node_name == "router":
            meta = {"intent": state.intent, "active_module": state.active_module,
                    "selected_skill": state.selected_skill}
        elif node_name == "context":
            meta = {"memory_hits": len(state.context.get("memory_hits", []))}
        elif node_name == "executor":
            meta = {"skill": state.selected_skill, "module": state.active_module}
        elif node_name == "composer":
            meta = {"llm_used": state.context.get("llm", {}).get("used", False)}
        elif node_name == "memory":
            meta = {"memory_written": state.context.get("memory_written", False),
                    "workspace_updated": state.context.get("workspace_updated", False)}

        _add_trace_event(state, "node_end", display_name, status=status,
                         duration_ms=duration, summary=f"{display_name}: {status} ({duration}ms)",
                         metadata=meta)
        return result

    return traced


def _build_langgraph():
    """Build LangGraph StateGraph with trace-wrapped nodes."""
    from langgraph.graph import StateGraph, END

    workflow = StateGraph(NetworkAgentState)
    for node_name, display_name in _CANONICAL_NODES:
        workflow.add_node(node_name, wrap_trace_node(node_name, display_name))

    workflow.set_entry_point("router")
    for src, dst in zip([n for n, _ in _CANONICAL_NODES],
                        [n for n, _ in _CANONICAL_NODES][1:]):
        workflow.add_edge(src, dst)
    workflow.add_edge("memory", END)

    return workflow.compile()


def _run_fallback(state: NetworkAgentState) -> NetworkAgentState:
    """Deterministic fallback pipeline — uses same trace wrapper via _run_timed_node."""
    for node_name, display_name in _CANONICAL_NODES:
        try:
            _run_timed_node(state, node_name, display_name)
        except Exception:
            # For fallback: catch errors and continue, node_end already recorded
            pass
        if state.error and state.intent == "unknown" and node_name == "router":
            state.final_response = "I didn't understand your request."
            break

    state.runtime_mode = "fallback"
    return state


def _run_timed_node(state: NetworkAgentState, node_name: str, display_name: str):
    """Run a single node with start/end trace events. Used by fallback pipeline.

    Mirrors wrap_trace_node but works synchronously without LangGraph context.
    Shares the same _add_trace_event helper and node_timings pattern.
    """
    # node_start
    _add_trace_event(state, "node_start", display_name, status="started",
                     summary=f"{display_name} started")

    start = time.time()

    # Import and run
    import importlib
    mapping = {
        "router": ("agent.nodes.intent_router", "route"),
        "context": ("agent.nodes.context_loader", "load_context"),
        "planner": ("agent.nodes.planner", "plan"),
        "executor": ("agent.nodes.skill_executor", "execute"),
        "verifier": ("agent.nodes.verifier", "verify"),
        "composer": ("agent.nodes.composer", "compose"),
        "memory": ("agent.nodes.memory_writer", "write_memory"),
    }
    mod_name, func_name = mapping[node_name]
    mod = importlib.import_module(mod_name)
    func = getattr(mod, func_name)

    try:
        state = func(state)
        status = "success"
    except Exception as e:
        status = "failed"
        if not state.error:
            state.error = str(e)
        _add_trace_event(state, "error", display_name, status="failed",
                         metadata={"error": str(e)[:200]})

    duration = round((time.time() - start) * 1000, 2)
    state.node_timings[display_name] = duration

    # Build metadata
    meta = {}
    if node_name == "router":
        meta = {"intent": state.intent, "active_module": state.active_module,
                "selected_skill": state.selected_skill}
    elif node_name == "executor":
        meta = {"skill": state.selected_skill, "module": state.active_module}
    elif node_name == "composer":
        meta = {"llm_used": state.context.get("llm", {}).get("used", False)}
    elif node_name == "memory":
        meta = {"memory_written": state.context.get("memory_written", False),
                "workspace_updated": state.context.get("workspace_updated", False)}

    _add_trace_event(state, "node_end", display_name, status=status,
                     duration_ms=duration, summary=f"{display_name}: {status} ({duration}ms)",
                     metadata=meta)
    return state


def run_agent(user_input: str = "", intent: str = "", payload: dict = None,
              workspace_id: str = "default", session_id: str = "") -> dict:
    """Run agent pipeline and return full result dict with metadata + trace.

    Args:
        user_input: The user's input text.
        intent: Optional forced intent.
        payload: Additional payload data.
        workspace_id: Workspace identifier.
        session_id: Optional session identifier for conversation grouping.
    """
    try:
        from workspace.ids import validate_workspace_id
        workspace_id = validate_workspace_id(workspace_id)
    except ValueError:
        return _rejected_result("invalid_workspace_id", intent, warning="invalid_workspace_id")

    payload = payload or {}
    if payload.get("source_config"):
        from backend.core.limits import source_config_too_large
        if source_config_too_large(payload.get("source_config", "")):
            return _rejected_result("source_config_too_large", intent, warning="source_config_too_large")
    elif intent == "translate_config":
        from backend.core.limits import source_config_too_large
        if source_config_too_large(user_input):
            return _rejected_result("source_config_too_large", intent, warning="source_config_too_large")

    context_ref = payload.pop("context_ref", "")

    state = NetworkAgentState(
        user_input=user_input,
        intent=intent,
        payload=payload,
        workspace_id=workspace_id,
        session_id=session_id or None,
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

    result = state.skill_results or state.tool_results or {}
    llm_ctx = state.context.get("llm", {})

    # ═══ Compute timeline from trace events (not hardcoded) ═══
    from observability.timeline import build_timeline_summary
    timeline = build_timeline_summary(state)
    planned = state.context.get("capability_status") == "planned" or state.verification.get("status") == "planned"
    status = "planned" if planned else ("error" if state.error else "ok")

    return {
        "ok": (state.error is None and not planned),
        "status": status,
        "run_id": state.request_id,
        "request_id": state.request_id,
        "session_id": state.session_id or "",
        "intent": state.intent,
        "capability": state.context.get("capability_id", ""),
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
        "input_artifacts": state.context.get("input_artifacts", []),
        "output_artifacts": state.context.get("output_artifacts", []),
        "report_artifacts": state.context.get("report_artifacts", []),
        "artifact_refs": _build_artifact_refs(state),
        "report_refs": [],
        "job_refs": [],
        "tool_invocations": state.context.get("tool_invocations", []),
        # ── Knowledge ──
        "knowledge_results_count": state.context.get("knowledge_results_count", 0),
        "knowledge_sources": state.context.get("knowledge_sources", []),
        "knowledge_chunks": state.context.get("knowledge_chunks", []),
        "knowledge_not_found": state.context.get("knowledge_not_found", False),
        "knowledge_result_details": _safe_knowledge_details(state.context.get("knowledge_results", [])),
        # ── Quality ──
        "quality_summary": _safe_quality_summary(result),
        "manual_review_count": len(result.get("manual_review", [])),
        # ── UI Actions (Agent → Frontend bridge) ──
        "ui_actions": state.ui_actions,
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


def _build_artifact_refs(state) -> list:
    """Build artifact refs from context (safe summary only, no full content)."""
    refs = []
    ws = state.workspace_id or "default"
    for art_id in (state.context.get("input_artifacts", []) +
                   state.context.get("output_artifacts", []) +
                   state.context.get("report_artifacts", [])):
        try:
            from artifacts.store import summarize_artifact_content
            s = summarize_artifact_content(ws, art_id)
            if s:
                refs.append(s)
        except Exception:
            pass
    return refs


def _safe_quality_summary(result: dict) -> dict:
    qs = result.get("quality_summary", {}) if isinstance(result, dict) else {}
    keys = [
        "source_residue_count",
        "silent_drop_count",
        "unsupported_count",
        "safe_drop_count",
        "review_required_count",
    ]
    return {key: int(qs.get(key, 0) or 0) if isinstance(qs, dict) else 0 for key in keys}


def _safe_knowledge_details(results: list) -> list:
    """Build safe knowledge result details for frontend display.

    Only includes metadata — no full content, secrets, or config.
    """
    details = []
    for r in results[:10]:  # Max 10 results for display
        d = r if isinstance(r, dict) else {}
        details.append({
            "artifact_id": (d.get("artifact_id", "") or "")[:8],
            "chunk_id": (d.get("chunk_id", "") or "")[:8],
            "title": d.get("title", "")[:80],
            "sensitivity": d.get("sensitivity", "internal"),
            "score": round(float(d.get("score", 0) or 0), 3),
        })
    return details


def _rejected_result(error: str, intent: str = "", warning: str = "") -> dict:
    warnings = [warning or error]
    return {
        "ok": False,
        "error": error,
        "run_id": "",
        "request_id": "",
        "intent": intent or "",
        "active_module": None,
        "selected_skill": None,
        "runtime_mode": "rejected",
        "result": {},
        "verification": {},
        "warnings": warnings,
        "final_response": error,
        "workspace_id": "",
        "memory_written": False,
        "workspace_updated": False,
        "memory_hits_count": 0,
        "artifacts": [],
        "input_artifacts": [],
        "output_artifacts": [],
        "report_artifacts": [],
        "artifact_refs": [],
        "report_refs": [],
        "job_refs": [],
        "tool_invocations": [],
        "quality_summary": {},
        "manual_review_count": 0,
        "trace_id": "",
        "trace_available": False,
        "timeline_summary": {},
        "llm": {"enabled": False, "used": False},
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
