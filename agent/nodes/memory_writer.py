# agent/nodes/memory_writer.py
"""Memory writer — writes run_summary and workspace state."""

import json, os
from agent.state import NetworkAgentState


def write_memory(state: NetworkAgentState) -> NetworkAgentState:
    """Write run_summary memory + workspace state."""
    if state.error:
        return state

    result = state.tool_results or {}

    try:
        from memory.schemas import MemoryRecord
        from memory.backends.jsonl_store import JSONLMemoryStore

        store = JSONLMemoryStore()
        counts = ""
        if state.intent == "translate_config":
            dc = result.get("deployable_config", "")
            mr = result.get("manual_review", [])
            us = result.get("unsupported", [])
            sn = result.get("semantic_near", [])
            counts = f" | d:{len(dc.split(chr(10))) if dc else 0} mr:{len(mr)} sn:{len(sn)} us:{len(us)}"

        llm_ctx = state.context.get("llm", {})
        content = f"intent={state.intent} skill={state.selected_skill} module={state.active_module}{counts}"
        if llm_ctx.get("used"):
            content += f" | llm:{llm_ctx.get('provider')} task:{llm_ctx.get('task')} policy:{llm_ctx.get('policy_pass')}"

        record = MemoryRecord(
            memory_type="run_summary", scope="project",
            title=f"Agent run: {state.intent}",
            content=content,
            tags=["agent_run", state.intent or "unknown", state.active_module or "unknown"],
            project_id=state.workspace_id,
        )
        store.put(record)
    except Exception:
        pass

    # Write workspace state summary
    _write_workspace_state(state)

    return state


def _write_workspace_state(state: NetworkAgentState):
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ws_path = os.path.join(root, "workspaces", state.workspace_id or "default", "state.json")
        os.makedirs(os.path.dirname(ws_path), exist_ok=True)

        result = state.tool_results or {}
        mr = result.get("manual_review", [])
        us = result.get("unsupported", [])

        summary = {
            "last_run_id": state.request_id,
            "last_intent": state.intent,
            "last_active_module": state.active_module,
            "last_result_counts": {
                "deployable_lines": len(result.get("deployable_config", "").split("\n")) if result.get("deployable_config") else 0,
                "manual_review_count": len(mr),
                "unsupported_count": len(us),
            },
            "last_manual_review_samples": [
                {"reason": r.get("reason", "")} for r in mr[:5]
            ],
            "last_unsupported_samples": [
                {"reason": r.get("reason", "")} for r in us[:5]
            ],
            "last_audit_summary": result.get("audit", {}).get("counts", {}),
            "llm_metadata": {
                "used": state.context.get("llm", {}).get("used", False),
                "provider": state.context.get("llm", {}).get("provider"),
                "task": state.context.get("llm", {}).get("task"),
                "policy_pass": state.context.get("llm", {}).get("policy_pass"),
                "fallback_reason": state.context.get("llm", {}).get("fallback_reason"),
            },
        }
        with open(ws_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
