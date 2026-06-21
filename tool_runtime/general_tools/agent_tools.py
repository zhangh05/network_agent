"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_agent_spawn(inv: ToolInvocation) -> dict:
    """Spawn a sub-agent with restricted tool access.

    Creates a child session and runs a constrained sub-agent loop
    with only read-only, low-risk tools. Returns compressed results.
    """
    instruction = str(inv.arguments.get("instruction", "")).strip()
    workspace_id = inv.arguments.get("workspace_id", "default")
    parent_session_id = str(inv.arguments.get("session_id", ""))
    allowed_tools = list(inv.arguments.get("allowed_tools") or [])
    max_turns = int(inv.arguments.get("max_turns", 1))

    if not instruction:
        return _error_inv(inv, "instruction is required")

    try:
        validate_workspace_id(workspace_id)
        from agent.runtime.sub_agent import run_sub_agent
        result = run_sub_agent(
            instruction=instruction,
            workspace_id=workspace_id,
            parent_session_id=parent_session_id,
            allowed_tools=allowed_tools if allowed_tools else None,
            max_turns=max_turns,
        )
        return _result(inv, result.get("ok", False), result)
    except Exception as e:
        import sys, traceback
        traceback.print_exc(file=sys.stderr)
        return _error_inv(inv, str(e)[:200])

def handle_agent_list_roles(inv: ToolInvocation) -> dict:
    """List available agent roles: planner, worker, reviewer."""
    roles = [
        {
            "name": "planner",
            "description": "Plans high-level task decomposition. Breaks complex tasks into subtasks and assigns to workers.",
            "default_tools": ["agent.spawn", "skill.list", "memory.search", "memory.list", "web.search"],
        },
        {
            "name": "worker",
            "description": "Executes assigned subtasks. Has access to read-only research, validation, and data tools.",
            "default_tools": ["web.search", "web.fetch_summary", "knowledge.search", "text.classify", "json.validate", "yaml.validate"],
        },
        {
            "name": "reviewer",
            "description": "Reviews worker outputs for quality, correctness, and completeness. Can request rework.",
            "default_tools": ["text.diff", "text.classify", "memory.search", "artifact.search", "workspace.file.read"],
        },
    ]
    return _ok(inv, "", {"roles": roles, "count": len(roles)})

def handle_agent_team(inv: ToolInvocation) -> dict:
    """Multi-agent team with planner/worker/reviewer roles.

    Planner: uses agent.spawn with knowledge.read tools to plan.
    Worker: uses agent.spawn with text/data tools to execute.
    Reviewer: optional, reviews worker output.

    Supports parallel worker mode: when parallel=True, each subtask from the
    planner gets its own concurrent worker sub-agent.
    Max 3 agents, max 2 turns each. High-risk tools forbidden.
    """
    import json as _json
    import concurrent.futures
    args = inv.arguments
    workspace_id = args.get("workspace_id", "default")
    instruction = str(args.get("instruction", "")).strip()
    roles = list(args.get("roles") or ["planner", "worker"])
    parallel = bool(args.get("parallel", False))

    if not instruction:
        return _error_inv(inv, "instruction is required")

    try:
        validate_workspace_id(workspace_id)
        from agent.runtime.sub_agent import run_sub_agent

        # Low-risk read-only tools only for all roles
        _low_risk_read_tools = [
            "web.search", "web.fetch_summary", "knowledge.search",
            "knowledge.get_source", "knowledge.get_chunk_summary",
            "artifact.search", "artifact.read_content_safe",
            "skill.list", "skill.inspect", "skill.find_skills",
            "memory.search", "memory.list", "memory.get_profile",
            "text.classify", "text.diff", "text.extract_keywords",
            "json.validate", "yaml.validate", "csv.summarize",
            "workspace.file.list", "workspace.file.preview",
            "workspace.file.exists", "workspace.get_metadata",
            "workspace.file.list", "workspace.file.exists", "workspace.file.read",
            "session.list", "session.summary.get",
            "run.list", "run.summary.get",
        ]
        _text_data_tools = [
            "web.search", "web.fetch_summary",
            "text.classify", "text.diff", "text.extract_keywords",
            "json.validate", "yaml.validate", "csv.summarize",
            "table.extract", "workspace.file.preview",
            "workspace.file.read",
        ]

        result = {"ok": True, "instruction": instruction, "roles_used": [], "plan": "", "worker_result": None, "reviewer_result": None}
        subtasks = []

        # ── Planner (if in roles) ──
        if "planner" in roles:
            plan_instruction = (
                f"Plan the execution of this task. Break it into subtasks. "
                f"Do NOT execute — only produce a structured plan.\n\n"
                f"Task: {instruction}\n\n"
                f"Output your plan STRICTLY as a JSON array of objects: "
                f'[{{"id": "1", "task": "..."}}, {{"id": "2", "task": "..."}}]. '
                f"Each subtask should be specific and actionable. Do not add prose."
            )
            plan_result = run_sub_agent(
                instruction=plan_instruction,
                workspace_id=workspace_id,
                parent_session_id=str(args.get("session_id", "")),
                allowed_tools=_low_risk_read_tools,
                max_turns=2,
            )
            if plan_result.get("ok"):
                result["plan"] = plan_result.get("final_response", "") or plan_result.get("summary", "")
                # v3.2.0 (Guardian): parse JSON subtasks, fall back to numbered list.
                plan_text = result["plan"]
                parsed_json = _parse_planner_json(plan_text)
                if parsed_json is not None:
                    subtasks = parsed_json
                else:
                    for line in plan_text.split("\n"):
                        stripped = line.strip()
                        if stripped and (stripped[0].isdigit() and (". " in stripped or ") " in stripped or "、".encode() in stripped.encode())):
                            task = stripped.split(". ", 1)[-1].split(") ", 1)[-1].split("、", 1)[-1].strip()
                            if task:
                                subtasks.append(task)
            else:
                result["plan"] = f"Planner failed: {plan_result.get('error', 'unknown')}"
            result["roles_used"].append("planner")

        # ── Worker(s) ──
        if not subtasks:
            subtasks = [instruction]

        max_parallel = min(len(subtasks), 3)  # Cap at 3 concurrent workers

        if parallel and len(subtasks) > 1:
            # v3.1.1: Parallel worker execution
            def _run_worker(task: str) -> dict:
                return run_sub_agent(
                    instruction=task,
                    workspace_id=workspace_id,
                    parent_session_id=str(args.get("session_id", "")),
                    allowed_tools=_text_data_tools,
                    max_turns=2,
                )

            worker_outputs = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
                futures = {
                    executor.submit(_run_worker, task): i
                    for i, task in enumerate(subtasks[:max_parallel])
                }
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        wr = future.result(timeout=60)
                        worker_outputs.append({
                            "task_index": idx,
                            "task": subtasks[idx],
                            "ok": wr.get("ok", False),
                            "final_response": wr.get("final_response", ""),
                        })
                    except Exception as e:
                        worker_outputs.append({
                            "task_index": idx,
                            "task": subtasks[idx],
                            "ok": False,
                            "final_response": f"Worker failed: {str(e)[:200]}",
                        })

            # Sort by task index
            worker_outputs.sort(key=lambda x: x["task_index"])
            combined = "\n\n".join(
                f"Subtask {wo['task_index']+1}: {wo['task']}\nResult: {wo['final_response']}"
                for wo in worker_outputs
            )
            result["worker_result"] = {
                "ok": all(wo["ok"] for wo in worker_outputs),
                "final_response": combined,
                "parallel": True,
                "worker_count": len(worker_outputs),
                "worker_details": worker_outputs,
            }
            result["roles_used"].append("worker")
        else:
            # Sequential worker (original behavior)
            worker_instruction = instruction
            if result.get("plan"):
                worker_instruction = f"Plan:\n{result['plan']}\n\nExecute the above plan. Task: {instruction}"
            worker_result = run_sub_agent(
                instruction=worker_instruction,
                workspace_id=workspace_id,
                parent_session_id=str(args.get("session_id", "")),
                allowed_tools=_text_data_tools,
                max_turns=2,
            )
            result["worker_result"] = {
                "ok": worker_result.get("ok", False),
                "final_response": worker_result.get("final_response", ""),
                "summary": worker_result.get("summary", ""),
                "tool_calls_count": len(worker_result.get("tool_calls", [])),
                "parallel": False,
            }
            result["roles_used"].append("worker")

        # ── Reviewer (optional) ──
        if "reviewer" in roles:
            worker_output = result["worker_result"].get("final_response", "") or result["worker_result"].get("summary", "")
            review_instruction = (
                f"Review the following worker output for quality, correctness, and completeness. "
                f"Identify any issues, missing information, or errors.\n\n"
                f"Original task: {instruction}\n\n"
                f"Worker output:\n{worker_output}\n\n"
                f"Provide your review: is the output acceptable, or does it need revision?"
            )
            reviewer_result = run_sub_agent(
                instruction=review_instruction,
                workspace_id=workspace_id,
                parent_session_id=str(args.get("session_id", "")),
                allowed_tools=_low_risk_read_tools,
                max_turns=2,
            )
            result["reviewer_result"] = {
                "ok": reviewer_result.get("ok", False),
                "final_response": reviewer_result.get("final_response", ""),
                "summary": reviewer_result.get("summary", ""),
            }
            result["roles_used"].append("reviewer")

        return _ok(inv, f"Team run completed (roles={roles}, parallel={parallel}).", result)
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_agent_get_result(inv: ToolInvocation) -> dict:
    """Get sub-agent result by child_session_id.

    Looks up child session and returns summary from run records or message store.
    """
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    child_session_id = str(args.get("child_session_id", "")).strip()

    if not child_session_id:
        return _error_inv(inv, "child_session_id is required")

    try:
        validate_workspace_id(ws)

        # Try to find run records for this child session
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
            # Extract last assistant message content
            for m in reversed(messages):
                if m.get("role") == "assistant":
                    content = m.get("content", "")
                    summary["last_assistant_message"] = content[:500]
                    break
            # Count tool result messages
            summary["tool_calls_count"] = sum(1 for m in messages if m.get("role") == "tool")
            return _ok(summary)
        else:
            # Fall back to run records
            try:
                from workspace.run_store import list_runs
                runs = list_runs(ws, session_id=child_session_id, limit=10)
                if runs:
                    return _ok(inv, "", {
                        "child_session_id": child_session_id,
                        "workspace_id": ws,
                        "run_count": len(runs),
                        "runs": [{"run_id": r.get("run_id", ""), "ok": r.get("ok", False), "summary": str(r.get("summary", ""))[:200]} for r in runs],
                    })
            except Exception:
                pass
            return _ok(inv, "", {
                "child_session_id": child_session_id,
                "workspace_id": ws,
                "message_count": 0,
                "last_assistant_message": "",
                "tool_calls_count": 0,
                "note": "no records found for this child session",
            })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_agent_spawn', 'handle_agent_list_roles', 'handle_agent_team', 'handle_agent_get_result', '_parse_planner_json']


def _parse_planner_json(plan_text: str):
    """v3.2.0 (Guardian): extract subtasks from planner JSON output.

    Accepts either:
      - a bare JSON array: [{"task": "..."}]
      - JSON wrapped in ```json ... ``` fences
      - a top-level object with a "subtasks" key
      - surrounding prose (we find the first JSON array/object span)

    Returns a list of subtask strings, or None if no JSON could be parsed.
    The caller falls back to numbered-list parsing in that case.
    """
    import json as _json
    import re

    if not plan_text:
        return None

    text = plan_text.strip()

    # Strip ```json fences
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    # Try parsing directly
    candidates: list = []
    try:
        candidates.append(_json.loads(text))
    except Exception:
        pass

    # Find first balanced array/object span
    if not candidates:
        for opener, closer in (("[", "]"), ("{", "}")):
            start = text.find(opener)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        snippet = text[start:i + 1]
                        try:
                            candidates.append(_json.loads(snippet))
                        except Exception:
                            pass
                        break

    for obj in candidates:
        if isinstance(obj, list):
            tasks = []
            for item in obj:
                if isinstance(item, dict) and item.get("task"):
                    tasks.append(str(item["task"]).strip())
                elif isinstance(item, str):
                    tasks.append(item.strip())
            tasks = [t for t in tasks if t]
            if tasks:
                return tasks[:10]  # cap to 10 to bound parallel fan-out
        elif isinstance(obj, dict):
            sub = obj.get("subtasks") or obj.get("tasks") or obj.get("plan")
            if isinstance(sub, list) and sub:
                tasks = []
                for item in sub:
                    if isinstance(item, dict) and item.get("task"):
                        tasks.append(str(item["task"]).strip())
                    elif isinstance(item, str):
                        tasks.append(item.strip())
                tasks = [t for t in tasks if t]
                if tasks:
                    return tasks[:10]
    return None
