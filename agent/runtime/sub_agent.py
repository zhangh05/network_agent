# agent/runtime/sub_agent.py
"""Sub-Agent — minimal child-agent that reuses the main AgentApp loop.

A sub-agent runs with a restricted ToolRouter (only read-only, low-risk tools),
a child session, and a hard turn limit. It returns compressed results to the
parent agent.
"""

import time
import uuid
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Tool allow lists ──

DEFAULT_ALLOWED_TOOLS = [
    # text / data validation (read-only)
    "text.analyze",
    "text.analyze",
    "text.analyze",
    "text.analyze",
    "data.validate",
    "data.validate",
    "data.data.csv.summarize",
    "data.data.table.extract",
    # knowledge (read-only)
    "knowledge.source.list",
    "knowledge.search",
    "knowledge.read",
    "knowledge.read",
    # artifacts (read-only)
    "workspace.artifact.list",
    "workspace.artifact.read",
    # memory (read-only)
    "memory.search",
    "memory.search",
    "memory.proworkspace.file.read",
    # web (read-only)
    "web.search",
    "web.page.process",
    "web.page.process",
    "web.search",
    # weather/news (read-only)
    "web.weather",
    "web.weather",
    "web.search",
    # runtime (read-only)
    "system.diagnostics",
    "system.diagnostics",
    # workspace (read-only)
    "workspace.file.list",
    "workspace.file.read",
    "workspace.file.list",
    "workspace.metadata.get",
    # sessions (read-only)
    "system.session.get",
    "system.session.get",
    "system.run.get",
    "system.run.get",
    "skill.list",
]

FORBIDDEN_FOR_SUB_AGENT = [
    "exec.run",
    "exec.run",
    "exec.python",
    "agent.spawn",
    "workspace.artifact.tag",
    "workspace.artifact.delete_soft",
    "workspace.artifact.save",
    "workspace.file.write_artifact",
    "report.artifact.save",
    "memory.manage",
    "memory.profile",
    "memory.manage",
    "system.system.session.checkpoint",
    "system.system.session.export",
    "system.session.snapshot",
    "system.system.session.rewind",
    "knowledge.import",
    "knowledge.source.reindex",
    "knowledge.import.document",
    "knowledge.import.file",
    "web.page.process",
]

MAX_SUB_AGENT_TURNS = 3


def run_sub_agent(instruction: str, workspace_id: str,
                  parent_session_id: str,
                  allowed_tools: list = None,
                  max_turns: int = 3) -> dict:
    """v3.10: Delegates to durable subagent via create_subagent_task + run_subagent_task.

    The old in-process session creation path is fully replaced.
    Returns dict with keys: ok, final_response, subtask_id, status.
    """
    if not workspace_id:
        return {"ok": False, "error": "workspace_id is required"}

    tool_allowlist = list(allowed_tools) if allowed_tools else list(DEFAULT_ALLOWED_TOOLS)
    # Remove forbidden tools
    tool_allowlist = [t for t in tool_allowlist if t not in FORBIDDEN_FOR_SUB_AGENT]

    from agent.runtime.durable.subagent import create_subagent_task, run_subagent_task

    if {"workspace.file.edit", "workspace.file.patch", "workspace.file.write_artifact"} & set(tool_allowlist):
        prof_id = "fix_agent"
    elif {"exec.run", "exec.python", "system.diagnostics"} & set(tool_allowlist):
        prof_id = "test_agent"
    elif {"config.analysis.run", "pcap.analysis.run", "device.list", "device.get"} & set(tool_allowlist):
        prof_id = "network_diag_agent"
    else:
        prof_id = "review_agent"

    create_result = create_subagent_task(
        profile_id=prof_id,
        goal=instruction,
        workspace_id=workspace_id,
        session_id=parent_session_id,
        parent_task_id="",
        context_refs=None,
    )
    if not create_result.get("ok"):
        return {"ok": False, "error": create_result.get("error", "failed to create subagent task")}

    subtask_id = create_result["subtask_id"]
    run_result = run_subagent_task(subtask_id, workspace_id)
    succeeded = run_result.get("ok", False) and run_result.get("status") == "succeeded"
    return {
        "ok": succeeded,
        "final_response": run_result.get("summary", ""),
        "subtask_id": subtask_id,
        "status": run_result.get("status", "unknown"),
        "findings": run_result.get("findings", []),
        "children_run_ids": [subtask_id],
    }
