# agent/nodes/context_loader.py
"""Context loader — loads workspace state, memory hits, registry info."""

import json
import os

from agent.state import NetworkAgentState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_context(state: NetworkAgentState) -> NetworkAgentState:
    """Load context: workspace state, memory hits, module/skill registries."""

    ws_id = state.workspace_id or "default"

    # ═══ 1. Workspace state ═══
    try:
        from workspace.manager import get_workspace_state
        ws = get_workspace_state(ws_id)
        state.context["workspace_state"] = ws

        # Handle context_ref=last_result
        if state.context.get("context_ref") == "last_result":
            summary = ws.get("last_result_summary", "")
            counts = ws.get("last_result_counts", {})
            samples_mr = ws.get("last_manual_review_samples", [])
            samples_us = ws.get("last_unsupported_samples", [])
            state.context["last_result"] = {
                "has_result": bool(ws.get("last_intent")),
                "last_intent": ws.get("last_intent"),
                "summary": summary,
                "counts": counts,
                "manual_review_samples": samples_mr[:5],
                "unsupported_samples": samples_us[:5],
                "llm_metadata": ws.get("llm_metadata", {}),
            }
    except Exception:
        state.context["last_result"] = {"has_result": False}

    # ═══ 2. Memory hits via retriever ═══
    try:
        from memory.retriever import retrieve_for_context
        hits = retrieve_for_context(
            query=state.user_input or "",
            project_id=ws_id,
            limit=5,
        )
        state.context["memory_hits"] = hits
    except Exception:
        state.context["memory_hits"] = []

    # ═══ 3. Module registry ═══
    try:
        with open(os.path.join(ROOT, "modules", "registry.json"), encoding="utf-8") as f:
            modules = json.load(f)
        state.context["modules"] = {
            m["module_name"]: m["status"] for m in modules.get("modules", [])
        }
    except Exception:
        pass

    # ═══ 4. Skill registry ═══
    try:
        with open(os.path.join(ROOT, "skills", "registry.json"), encoding="utf-8") as f:
            skills = json.load(f)
        state.context["skills"] = {
            s["skill_name"]: s.get("enabled", False) for s in skills.get("skills", [])
        }
    except Exception:
        pass

    return state
