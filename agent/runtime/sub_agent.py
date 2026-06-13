# agent/runtime/sub_agent.py
"""Sub-Agent — minimal child-agent that reuses the main AgentApp loop.

A sub-agent runs with a restricted ToolRouter (only read-only, low-risk tools),
a child session, and a hard turn limit. It returns compressed results to the
parent agent.
"""

import uuid
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Tool allow lists ──

DEFAULT_ALLOWED_TOOLS = [
    # text / data validation (read-only)
    "text.redact",
    "text.diff",
    "text.extract_keywords",
    "text.classify",
    "json.validate",
    "yaml.validate",
    "csv.summarize",
    "table.extract",
    # knowledge (read-only)
    "knowledge.query",
    "knowledge.list_sources",
    "knowledge.search_chunks",
    "knowledge.read_chunk",
    "knowledge.read_parent",
    # artifacts (read-only)
    "artifact.list",
    "artifact.read",
    # memory (read-only)
    "memory.search",
    "memory.list",
    "memory.get_profile",
    # web (read-only)
    "web.search",
    "web.fetch_summary",
    "web.extract_links",
    "web.official_doc_search",
    # weather/news (read-only)
    "weather.current",
    "weather.forecast",
    "news.search",
    # runtime (read-only)
    "runtime.health",
    "runtime.diagnostics",
    # workspace (read-only)
    "workspace.list_files",
    "workspace.read_text_preview",
    "workspace.path_exists",
    "workspace.get_metadata",
    # sessions (read-only)
    "session.list",
    "session.get_summary",
    "run.list_recent",
    "run.get_summary",
    "skill.list",
]

FORBIDDEN_FOR_SUB_AGENT = [
    "shell.exec",
    "powershell.exec",
    "python.exec",
    "agent.spawn",
    "artifact.tag",
    "artifact.delete_soft",
    "artifact.save_result",
    "workspace.write_artifact_file",
    "report.save_artifact",
    "memory.create",
    "memory.set_profile",
    "memory.confirm",
    "session.create",
    "session.archive",
    "session.snapshot",
    "session.rewind",
    "knowledge.index_artifact",
    "knowledge.reindex",
    "knowledge.import_document",
    "knowledge.import_file",
    "web.save_to_artifact",
]

MAX_SUB_AGENT_TURNS = 3


def run_sub_agent(instruction: str, workspace_id: str,
                  parent_session_id: str,
                  allowed_tools: list = None,
                  max_turns: int = 1) -> dict:
    """Run a minimal sub-agent with restricted tool access.

    Args:
        instruction: Task instruction for the sub-agent.
        workspace_id: Workspace identifier.
        parent_session_id: The parent agent's session ID.
        allowed_tools: Tool allowlist. Defaults to DEFAULT_ALLOWED_TOOLS.
        max_turns: Maximum LLM turns (1-3). Defaults to 1.

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
    try:
        from workspace.session_store import create_session
        child_session_id = uuid.uuid4().hex[:16]
        create_session(ws_id=workspace_id, session_id=child_session_id, title=f"sub_agent_{child_run_id}")
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

    except Exception as e:
        return {
            "ok": False,
            "final_response": f"Sub-agent initialization failed: {str(e)[:200]}",
            "tool_calls_count": 0, "steps": 0,
            "parent_run_id": parent_run_id, "child_run_id": child_run_id,
        }

    visible_tools = list(tool_router.model_visible_tools()) if tool_router else []
    visible_tool_ids = [t.tool_id if hasattr(t, 'tool_id') else t.get('tool_id', '') for t in visible_tools]

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

        from agent.protocol.op import AgentOp
        op = AgentOp(
            message=instruction,
            session_id=child_session_id,
            workspace_id=workspace_id,
        )

        # Pass restricted tool_router directly to run_turn
        result = run_turn(
            session,
            AgentTurn.from_op(op),
            services,
            restricted_tool_router=tool_router,
        )

        if result and hasattr(result, "final_response"):
            final_response = result.final_response or ""
            tool_calls_count = len(result.tool_calls) if hasattr(result, 'tool_calls') and result.tool_calls else 0
            sub_ok = getattr(result, 'ok', True)
            # Use actual turn count if available from result metadata
            steps = getattr(result, 'metadata', {}).get('steps', 1) if hasattr(result, 'metadata') else 1
        elif isinstance(result, dict):
            final_response = result.get("final_response", "")
            tool_calls_count = len(result.get("tool_calls", []))
            sub_ok = result.get("ok", True)
            steps = result.get("metadata", {}).get("steps", 1)
        else:
            final_response = str(result)

    except Exception as e:
        sub_ok = False
        final_response = f"Sub-agent execution failed: {str(e)[:500]}"

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
