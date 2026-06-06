"""Memory writer — memory + workspace state + run record."""

import json, os
from agent.state import NetworkAgentState

def write_memory(state: NetworkAgentState) -> NetworkAgentState:
    if state.error: return state

    result = state.tool_results or {}
    ws_id = state.workspace_id or "default"

    # 1. Memory run_summary
    try:
        from memory.schemas import MemoryRecord
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        counts = ""
        if state.intent == "translate_config":
            dc = result.get("deployable_config","")
            mr = result.get("manual_review",[])
            us = result.get("unsupported",[])
            counts = f" | d:{len(dc.split(chr(10))) if dc else 0} mr:{len(mr)} us:{len(us)}"
        llm_ctx = state.context.get("llm", {})
        content = f"intent={state.intent} skill={state.selected_skill} module={state.active_module}{counts}"
        if llm_ctx.get("used"):
            content += f" | llm:{llm_ctx.get('provider')} task:{llm_ctx.get('task')}"
        record = MemoryRecord(memory_type="run_summary", scope="project",
            title=f"Agent run: {state.intent}", content=content,
            tags=["agent_run", state.intent or "unknown", state.active_module or "unknown"],
            project_id=ws_id)
        store.put(record)
    except: pass

    # 2. Workspace state update
    try:
        from workspace.manager import update_workspace_state
        mr = result.get("manual_review",[])
        us = result.get("unsupported",[])
        dc = result.get("deployable_config","")
        update_workspace_state(ws_id, {
            "last_run_id": state.request_id,
            "last_intent": state.intent,
            "last_active_module": state.active_module,
            "last_result_summary": f"intent={state.intent}",
            "last_result_counts": {"deployable_lines": len(dc.split(chr(10))) if dc else 0,
                "manual_review_count": len(mr), "unsupported_count": len(us)},
            "last_manual_review_samples": [{"reason": r.get("reason","")[:80]} for r in mr[:3]],
            "last_unsupported_samples": [{"reason": r.get("reason","")[:80]} for r in us[:3]],
            "llm_metadata": state.context.get("llm", {}),
        })
    except: pass

    # 3. Run record
    try:
        from workspace.run_store import write_run_record
        write_run_record(state, ws_id)
    except: pass

    return state
