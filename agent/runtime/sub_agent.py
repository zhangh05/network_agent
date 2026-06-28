# agent/runtime/sub_agent.py
"""v3.10: Sub-Agent bridge — delegates to durable subagent via create_subagent_task + run_subagent_task.

All old session-creation logic has been removed. The durable subagent enforces
profile-gated tool access, budget limits, and pending-only memory writes.
"""

import uuid

# v3.10: DEFAULT_ALLOWED_TOOLS and FORBIDDEN_FOR_SUB_AGENT are legacy artifacts.
# Subagent tool access is now controlled by SubagentProfile.allowed_tools.
# These lists remain for backward compat with legacy callers that pass allowed_tools explicitly.
DEFAULT_ALLOWED_TOOLS = [
    "workspace.file", "workspace.file", "code.search",
    "knowledge.manage", "knowledge.manage", "web.manage",
    "web.manage", "system.manage",
]
FORBIDDEN_FOR_SUB_AGENT = ["exec.run", "exec.run", "agent.manage"]
MAX_SUB_AGENT_TURNS = 3


def run_sub_agent(instruction: str, workspace_id: str,
                  parent_session_id: str,
                  allowed_tools: list = None,
                  max_turns: int = 3) -> dict:
    """v3.10: Delegates to durable subagent via create_subagent_task + run_subagent_task.

    Returns dict with keys: ok, final_response, subtask_id, status.
    """
    if not workspace_id:
        return {"ok": False, "error": "workspace_id is required"}

    tool_allowlist = list(allowed_tools) if allowed_tools else list(DEFAULT_ALLOWED_TOOLS)
    tool_allowlist = [t for t in tool_allowlist if t not in FORBIDDEN_FOR_SUB_AGENT]

    from agent.runtime.durable.subagent import (
        create_subagent_task, run_subagent_task, get_profile, SubagentProfile,
    )
    prof_id = "generic_agent"
    prof = get_profile(prof_id)
    if not prof:
        prof = SubagentProfile(
            profile_id="generic_agent", name="Generic Agent",
            role="General assistant", allowed_action_classes=["read"],
            allowed_tools=tool_allowlist,
            max_steps=min(max_turns, MAX_SUB_AGENT_TURNS),
            max_runtime_seconds=120,
            memory_write_policy="pending_only",
        )

    create_result = create_subagent_task(
        profile_id=prof_id, goal=instruction,
        workspace_id=workspace_id, session_id=parent_session_id,
        parent_task_id="", context_refs=None,
    )
    if not create_result.get("ok"):
        return {"ok": False, "error": create_result.get("error", "failed to create subagent task")}

    subtask_id = create_result["subtask_id"]
    run_result = run_subagent_task(subtask_id, workspace_id)
    return {
        "ok": run_result.get("ok", False),
        "final_response": run_result.get("summary", ""),
        "subtask_id": subtask_id,
        "status": run_result.get("status", "unknown"),
        "findings": run_result.get("findings", []),
        "children_run_ids": [subtask_id],
    }
