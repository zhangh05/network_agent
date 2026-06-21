# agent/runtime_status.py
"""Agent runtime status."""

import json
import os
import traceback


def get_runtime_status() -> dict:
    """Report agent runtime status."""
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

    # LangGraph availability
    graph_compile_ok = False
    fallback_reason = None
    graph_nodes = []
    try:
        from langgraph.graph import StateGraph
        graph_compile_ok = True
        graph_nodes = ["router", "context", "planner", "executor", "verifier", "composer", "memory"]
    except ImportError:
        fallback_reason = "langgraph_import_failed"

    from agent.llm.runtime import get_llm_status
    llm_status = get_llm_status()

    # Supported intents.
    supported_intents = [
        "assistant_chat", "translate_config", "knowledge_query", "context_qa",
        "topology_draw", "inspection_analyze", "memory_search", "skill_query",
        "module_query",
    ]

    return {
        "agent_runtime": "agentic_loop" if graph_compile_ok else "fallback",
        "langgraph_available": graph_compile_ok,
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
        "supported_intents": supported_intents,
        "enabled_skills": enabled_skills,
        "enabled_modules": enabled_modules,
    }
