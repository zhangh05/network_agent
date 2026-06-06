# agent/nodes/memory_writer.py
"""Memory writer — writes run_summary after successful execution."""

from datetime import datetime, timezone

from agent.state import NetworkAgentState


def write_memory(state: NetworkAgentState) -> NetworkAgentState:
    """Write a run_summary memory record on successful agent runs."""
    if state.error:
        return state

    result = state.tool_results or {}
    if not result.get("ok") and state.intent not in (
        "topology_draw", "inspection_analyze", "knowledge_search"
    ):
        return state

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
            counts = f" | deployable:{len(dc.split(chr(10))) if dc else 0} mr:{len(mr)} sn:{len(sn)} us:{len(us)}"

        record = MemoryRecord(
            memory_type="run_summary",
            scope="project",
            title=f"Agent run: {state.intent}",
            content=f"intent={state.intent} skill={state.selected_skill} module={state.active_module}{counts}",
            tags=["agent_run", state.intent or "unknown", state.active_module or "unknown"],
            project_id=state.workspace_id,
        )
        store.put(record)
    except Exception:
        pass

    return state
