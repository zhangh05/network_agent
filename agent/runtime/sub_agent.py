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
    """Run a minimal sub-agent with restricted tool access.

    Args:
        instruction: Task instruction for the sub-agent.
        workspace_id: Workspace identifier.
        parent_session_id: The parent agent's session ID.
        allowed_tools: Tool allowlist. Defaults to DEFAULT_ALLOWED_TOOLS.
        max_turns: Maximum LLM turns (1-3). Defaults to 3 (v3.8: raised from 1).

    Returns:
        dict with keys: ok, final_response, tool_calls_count, steps,
                        parent_run_id, child_run_id
    """
    parent_run_id = str(uuid.uuid4())[:8]
    child_run_id = str(uuid.uuid4())[:8]

    # ── Validate and clamp max_turns ──
    try:
        max_turns = min(max(1, int(max_turns)), MAX_SUB_AGENT_TURNS)
    except (TypeError, ValueError):
        max_turns = 1

    # ── Build tool allowlist ──
    tool_allowlist = list(allowed_tools) if allowed_tools else list(DEFAULT_ALLOWED_TOOLS)

    # Remove any tools that are forbidden for sub-agents
    tool_allowlist = [
        t for t in tool_allowlist
        if t not in FORBIDDEN_FOR_SUB_AGENT
    ]

    # ── PermissionMatrix filter: remove any tool that would be denied ──
    try:
        from agent.runtime.permission_matrix import PermissionMatrix, PermissionAction, PermissionDecision
        pm = PermissionMatrix()
        filtered_allowlist = []
        for tid in tool_allowlist:
            action = pm.action_for_tool(tid)
            decision = pm.check(tid, action, context=None, spec=None)
            if decision != PermissionDecision.DENY:
                filtered_allowlist.append(tid)
        tool_allowlist = filtered_allowlist
    except Exception:
        pass  # If PermissionMatrix import fails, keep original allowlist

    # ── Create child session ──
    child_session_id = None
    try:
        from workspace.session_store import create_session
        session = create_session(ws_id=workspace_id, title=f"sub_agent_{child_run_id}")
        child_session_id = session.get("session_id")
    except Exception:
        child_session_id = None

    if not child_session_id:
        child_session_id = f"sub_{child_run_id}"

    # ── Build restricted ToolRouter using the full agent registry ──
    tool_router = None
    try:
        from agent.tools.router import ToolRouter
        from agent.tools.registry import ToolRegistry as AgentToolRegistry
        from agent.runtime.services import default_runtime_services

        # Reuse the full registry and copy specs + handlers for allowed tools only
        full_reg = default_runtime_services().tool_service.registry
        agent_registry = AgentToolRegistry()
        # v3.8.1: Copy _tool_client from parent registry so that
        # canonical tools (web.weather, web.search, workspace.file.read, …)
        # can dispatch through the shared tool client instead of returning
        # "No tool client".
        if hasattr(full_reg, '_tool_client') and full_reg._tool_client is not None:
            agent_registry._tool_client = full_reg._tool_client

        for t in full_reg.list_all():
            tid = t.tool_id
            if tid in tool_allowlist:
                agent_registry._specs[tid] = t
                # Copy capability handler if present
                if hasattr(full_reg, '_handlers') and tid in full_reg._handlers:
                    if not hasattr(agent_registry, '_handlers'):
                        agent_registry._handlers = {}
                    agent_registry._handlers[tid] = full_reg._handlers[tid]

        tool_router = ToolRouter.for_turn(agent_registry, allowed_tool_ids=list(tool_allowlist))
        # v3.8.1: Wire dispatch_delegate so the sub-agent's ToolRouter
        # can use the parent ToolService's dispatcher for canonical tools
        # (the same path that context_tools.build_base_tool_router uses).
        parent_tool_service = default_runtime_services().tool_service
        if isinstance(parent_tool_service, ToolRouter):
            tool_router.dispatch_delegate = parent_tool_service.dispatch

    except Exception as e:
        return {
            "ok": False,
            "final_response": f"Sub-agent initialization failed: {str(e)[:200]}",
            "tool_calls_count": 0, "steps": 0,
            "parent_run_id": parent_run_id, "child_run_id": child_run_id,
        }

    visible_tools = list(tool_router.model_visible_tools()) if tool_router else []
    # v3.8.1: model_visible_tools() returns LLMToolSpec objects (OpenAI-format
    # dicts with "type":"function"/"function":{...}), not ToolSpec.
    # Extract real_tool_id via the router's llm_name_map.
    visible_tool_ids = [
        tool_router.llm_name_map.get(t.name, "") if hasattr(t, 'name')
        else tool_router.llm_name_map.get(t.get("function", {}).get("name", ""), "")
        for t in visible_tools
    ]

    # ── Run sub-agent loop ──
    tool_calls_count = 0
    steps = 0
    final_response = ""
    sub_ok = True

    try:
        from agent.core.session import AgentSession
        from agent.core.turn import AgentTurn
        from agent.runtime.loop import run_turn
        from agent.runtime.services import default_runtime_services

        services = default_runtime_services()
        session = AgentSession(
            session_id=child_session_id,
            workspace_id=workspace_id,
            services=services,
        )
        # v3.1.1: Mark as sub-agent so the prompt builder injects role constraints.
        # P0 fix (round 7): use the immutable trust marker `mark_sub_agent()`
        # instead of writing to session.metadata (which the LLM could also write).
        session.mark_sub_agent()

        from agent.protocol.op import AgentOp
        op = AgentOp(
            user_input=instruction,
            session_id=child_session_id,
            workspace_id=workspace_id,
        )

        # Run sub-agent turns in a loop (up to max_turns)
        for turn_num in range(max_turns):
            result = run_turn(
                session,
                AgentTurn.from_op(op),
                services,
                restricted_tool_router=tool_router,
            )

            if result and hasattr(result, "final_response"):
                final_response = result.final_response or ""
                tool_calls_count += len(result.tool_calls) if hasattr(result, 'tool_calls') and result.tool_calls else 0
                sub_ok = getattr(result, 'ok', True)
                steps += getattr(result, 'metadata', {}).get('steps', 1) if hasattr(result, 'metadata') else 1
            elif isinstance(result, dict):
                final_response = result.get("final_response", "")
                tool_calls_count += len(result.get("tool_calls", []))
                sub_ok = result.get("ok", True)
                steps += result.get("metadata", {}).get("steps", 1)

            # Stop if LLM answered without needing more tools
            if not getattr(result, 'tool_calls', None) or not (result.tool_calls if hasattr(result, 'tool_calls') else []):
                break

            # Prepare next turn: append current result as context
            op.message = f"Continue working on: {instruction}. Previous output: {final_response[:500]}"

    except Exception as e:
        sub_ok = False
        final_response = f"Sub-agent execution failed: {str(e)[:500]}"
    finally:
        # v3.2.0 (Guardian): keep the child session + write a structured run
        # record so parents and humans can audit what sub-agents actually did.
        # The session metadata tags it as a sub-agent; the run record carries
        # parent_run_id / child_run_id / visible_tool_ids.
        try:
            if child_session_id:
                from workspace.session_store import update_session
                update_session(
                    child_session_id, workspace_id,
                    metadata={
                        "is_sub_agent": True,
                        "parent_run_id": parent_run_id,
                        "child_run_id": child_run_id,
                        "parent_session_id": parent_session_id,
                        "tool_calls_count": tool_calls_count,
                        "steps": steps,
                        "ok": sub_ok,
                        "finished_at": time.time(),
                    },
                    title=f"sub_agent_{child_run_id}",
                )
        except Exception:
            pass

        # Structured run record (visible via /api/workspaces/{ws}/runs).
        try:
            from workspace.run_store import write_sub_agent_run
            write_sub_agent_run(
                ws_id=workspace_id,
                child_session_id=child_session_id or f"sub_{child_run_id}",
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
                instruction=instruction,
                ok=sub_ok,
                final_response=final_response[:5000],
                tool_calls_count=tool_calls_count,
                steps=steps,
                visible_tool_ids=visible_tool_ids,
            )
        except Exception:
            pass

    return {
        "ok": sub_ok,
        "final_response": final_response,
        "tool_calls_count": tool_calls_count,
        "steps": steps,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "child_session_id": child_session_id,
        "visible_tool_ids": visible_tool_ids,
    }


def _adapt_to_agent_spec(spec_dict: dict):
    """Adapt a runtime ToolSpec dict to an agent ToolSpec."""
    from agent.tools.schemas import ToolSpec
    return ToolSpec(
        tool_id=spec_dict.get("tool_id", ""),
        name=spec_dict.get("name", ""),
        category=spec_dict.get("category", ""),
        description=spec_dict.get("description", ""),
        risk_level=spec_dict.get("risk_level", "low"),
        enabled=spec_dict.get("enabled", True),
        requires_approval=spec_dict.get("requires_approval", False),
        input_schema=spec_dict.get("input_schema", {}),
        callable_by_llm=spec_dict.get("callable_by_llm", True),
        forbidden=False,
        source="general",
    )
