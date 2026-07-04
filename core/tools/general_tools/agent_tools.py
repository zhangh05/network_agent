"""Agent orchestration tools — OpenCode-aligned profile-based subagent system."""

from __future__ import annotations

from core.tools.schemas import ToolInvocation
from workspace.ids import validate_workspace_id

from core.tools.general_tools.shared import _caller_workspace, _error_inv, _ok, _result


# ── Agent profiles — declarative, extensible ─────────────────────────

_AGENT_PROFILES: dict[str, dict] = {
    "explore": {
        "name": "explore",
        "description": "Read-only code explorer. Finds files, searches code, answers codebase questions.",
        "allowed_tools": [
            "workspace.file", "workspace.artifact",
            "web.manage", "knowledge.manage",
            "code.search", "text.analyze",
        ],
        "temperature": 0.3,
        "max_turns": 3,
        "scale": "small",  # fast, low cost
    },
    "research": {
        "name": "research",
        "description": "Web and knowledge research. Searches external sources, fetches docs, aggregates findings.",
        "allowed_tools": [
            "web.manage", "knowledge.manage",
            "data.manage", "text.analyze",
            "workspace.artifact",
        ],
        "temperature": 0.5,
        "max_turns": 5,
        "scale": "medium",
    },
    "worker": {
        "name": "worker",
        "description": "Full-capability worker. Reads/writes files, executes commands, processes data.",
        "allowed_tools": [
            "workspace.file", "workspace.artifact",
            "web.manage", "knowledge.manage",
            "data.manage", "text.analyze",
            "exec.run", "system.manage",
            "browser.manage", "config.manage",
        ],
        "temperature": 0.4,
        "max_turns": 8,
        "scale": "large",
    },
    "review": {
        "name": "review",
        "description": "Read-only reviewer. Checks code quality, finds issues, suggests improvements.",
        "allowed_tools": [
            "workspace.file", "workspace.artifact",
            "text.analyze", "data.manage",
            "knowledge.manage",
        ],
        "temperature": 0.2,
        "max_turns": 3,
        "scale": "small",
    },
}


def _get_profile(agent_type: str) -> dict | None:
    return _AGENT_PROFILES.get(agent_type)


def _inv_session_id(inv: ToolInvocation) -> str:
    args = inv.arguments or {}
    return str(args.get("session_id") or getattr(inv, "session_id", "") or "").strip()


# ── Subagent execution ───────────────────────────────────────────────


def _run_durable_subagent(*, instruction: str, workspace_id: str, session_id: str,
                          parent_task_id: str = "",
                          agent_type: str = "explore",
                          max_turns: int = 3,
                          background: bool = False) -> dict:
    from agent.runtime.durable.subagent import (
        create_subagent_task,
        merge_subagent_result,
        run_subagent_task,
    )

    profile = _get_profile(agent_type)
    if not profile:
        return {"ok": False, "error": f"unknown agent_type: {agent_type}"}

    profile_id = profile["name"]
    effective_turns = min(max_turns, profile.get("max_turns", 5))
    allowed_tools = profile.get("allowed_tools", [])

    created = create_subagent_task(
        parent_task_id=parent_task_id,
        workspace_id=workspace_id,
        session_id=session_id,
        profile_id=profile_id,
        goal=instruction,
        context_refs=[],
    )
    if not created.get("ok"):
        return {"ok": False, "error": created.get("error", "failed to create subagent task")}

    subtask_id = created["subtask_id"]

    if background:
        # TODO: Wire up async background execution
        return {
            "ok": True, "subtask_id": subtask_id,
            "background": True,
            "_hint": f"Subagent {agent_type} launched in background (task: {subtask_id})",
        }

    result = run_subagent_task(subtask_id, workspace_id)
    merge_subagent_result(parent_task_id, subtask_id, workspace_id)
    child_session_id = result.get("child_session_id") or subtask_id
    return {
        "ok": result.get("ok", False) and result.get("status") == "succeeded",
        "final_response": result.get("summary", ""),
        "summary": result.get("summary", ""),
        "subtask_id": subtask_id,
        "child_session_id": child_session_id,
        "agent_type": agent_type,
        "status": result.get("status", "unknown"),
        "findings": result.get("findings", []),
        "tool_results": result.get("tool_results", []),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
    }


# ── Action handlers ──────────────────────────────────────────────────


def handle_agent_list(inv: ToolInvocation) -> dict:
    """List available agent profiles with capabilities."""
    profiles = []
    for ptype, p in _AGENT_PROFILES.items():
        profiles.append({
            "agent_type": ptype,
            "description": p["description"],
            "max_turns": p.get("max_turns", 5),
            "scale": p.get("scale", "medium"),
        })
    return _ok(inv, "", {
        "agents": profiles, "count": len(profiles),
        "_hint": (
            "explore/research/review 用于只读任务。worker 用于需要写文件或执行命令的任务。"
            "用 spawn 启动子Agent，用 get 获取结果。"
        ),
    })


def handle_agent_spawn(inv: ToolInvocation) -> dict:
    """Spawn a subagent with typed profile.

    Required: agent_type (explore|research|worker|review), instruction.
    Optional: max_turns (default from profile), background (default false).
    """
    args = inv.arguments
    instruction = str(args.get("instruction", "")).strip()
    agent_type = str(args.get("agent_type", "explore")).strip()
    max_turns = int(args.get("max_turns", 0) or 0)
    background = bool(args.get("background", False))

    if not instruction:
        return _error_inv(inv, "instruction is required")

    profile = _get_profile(agent_type)
    if not profile:
        available = list(_AGENT_PROFILES.keys())
        return _error_inv(inv, f"unknown agent_type: {agent_type!r}. Available: {available}")

    workspace_id = _caller_workspace(inv)
    effective_turns = max_turns or profile.get("max_turns", 5)

    try:
        validate_workspace_id(workspace_id)
        result = _run_durable_subagent(
            instruction=instruction,
            workspace_id=workspace_id,
            session_id=_inv_session_id(inv),
            parent_task_id=getattr(inv, "task_id", "") or "",
            agent_type=agent_type,
            max_turns=effective_turns,
            background=background,
        )
        return _result(inv, result.get("ok", False), {
            **result,
            "_hint": (
                f"Subagent {agent_type} "
                + ("已启动（后台）。" if background else f"完成，状态: {result.get('status')}。")
                + f" subtask_id: {result.get('subtask_id')}。"
                + " 用 get 获取详细结果。"
            ),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_agent_get_result(inv: ToolInvocation) -> dict:
    """Get subagent result by child_session_id."""
    args = inv.arguments
    ws = _caller_workspace(inv)
    child_session_id = str(args.get("child_session_id", "")).strip()

    if not child_session_id:
        return _error_inv(inv, "child_session_id is required")

    try:
        validate_workspace_id(ws)
        from workspace.message_store import SessionMessageStore
        store = SessionMessageStore(session_id=child_session_id, ws_id=ws)
        if store.exists():
            messages = store.get_history_window(k=50)
            summary = {
                "child_session_id": child_session_id,
                "workspace_id": ws,
                "message_count": len(messages),
                "last_assistant_message": "",
                "tool_calls_count": 0,
            }
            for m in reversed(messages):
                if m.get("role") == "assistant":
                    summary["last_assistant_message"] = (m.get("content", "") or "")[:500]
                    break
            summary["tool_calls_count"] = sum(1 for m in messages if m.get("role") == "tool")
            return _ok(inv, "", summary)

        # Fall back to run records
        try:
            from workspace.run_store import list_runs
            runs = list_runs(ws, session_id=child_session_id, limit=10)
            if runs:
                return _ok(inv, "", {
                    "child_session_id": child_session_id,
                    "workspace_id": ws,
                    "run_count": len(runs),
                    "runs": [{
                        "run_id": r.get("run_id", ""),
                        "ok": r.get("ok", False),
                        "summary": str(r.get("summary", ""))[:200],
                    } for r in runs],
                })
        except Exception:
            pass

        return _ok(inv, "", {
            "child_session_id": child_session_id,
            "workspace_id": ws,
            "note": "no records found for this child session",
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_agent_cancel(inv: ToolInvocation) -> dict:
    """Cancel a running subagent by subtask_id."""
    args = inv.arguments
    subtask_id = str(args.get("subtask_id", "")).strip()
    if not subtask_id:
        return _error_inv(inv, "subtask_id is required")
    try:
        ws = _caller_workspace(inv)
        validate_workspace_id(ws)
        # Mark subtask as cancelled in trajectory
        from agent.runtime.durable.trajectory import _live_tasks
        task = _live_tasks.get(subtask_id)
        if task:
            task["status"] = "cancelled"
            task["cancelled_at"] = getattr(__import__("agent.runtime.utils", fromlist=["now_iso"]), "now_iso", lambda: "")()
        return _ok(inv, "", {
            "subtask_id": subtask_id, "cancelled": True,
            "_hint": f"Subagent {subtask_id} 已取消。",
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_agent_status(inv: ToolInvocation) -> dict:
    """List all running/completed subagent tasks."""
    try:
        ws = _caller_workspace(inv)
        validate_workspace_id(ws)
        from agent.runtime.durable.trajectory import _live_tasks
        tasks = []
        for tid, task in list(_live_tasks.items()):
            tasks.append({
                "subtask_id": tid,
                "status": task.get("status", "unknown"),
                "agent_type": task.get("profile_id", ""),
                "instruction": (task.get("goal", "") or "")[:100],
            })
        return _ok(inv, "", {
            "tasks": tasks, "count": len(tasks),
            "_hint": f"{len(tasks)} 个子Agent任务。用 cancel 取消运行中的任务。",
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


# ── Exports ──────────────────────────────────────────────────────────

__all__ = [
    'handle_agent_list',
    'handle_agent_spawn',
    'handle_agent_get_result',
    'handle_agent_cancel',
    'handle_agent_status',
    '_AGENT_PROFILES',
]
