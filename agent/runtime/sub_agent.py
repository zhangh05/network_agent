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

    # ── Create child session ──
    try:
        from workspace.session_store import create_session
        child_session_id = uuid.uuid4().hex[:16]
        create_session(ws_id=workspace_id, title=f"sub_agent_{child_run_id}")
    except Exception:
        child_session_id = None

    child_session_id = child_session_id or f"sub_{child_run_id}"

    # ── Build restricted ToolRouter ──
    try:
        from agent.tools.router import ToolRouter
        from agent.tools.registry import ToolRegistry as AgentToolRegistry
        from tool_runtime.registry import ToolRegistry as RuntimeToolRegistry

        # Build the runtime-level registry with general tools
        runtime_registry = RuntimeToolRegistry()
        from tool_runtime.general_tools import ALL_GENERAL_TOOLS, REMOVED_GENERAL_TOOL_IDS
        from copy import deepcopy
        for spec, handler in ALL_GENERAL_TOOLS:
            if spec.tool_id in REMOVED_GENERAL_TOOL_IDS:
                continue
            if spec.tool_id not in tool_allowlist:
                continue
            runtime_registry.register_tool(deepcopy(spec), handler)

        # Build agent-level registry and router
        agent_registry = AgentToolRegistry()
        for spec, handler in ALL_GENERAL_TOOLS:
            if spec.tool_id in REMOVED_GENERAL_TOOL_IDS:
                continue
            if spec.tool_id not in tool_allowlist:
                continue
            spec_copy = deepcopy(spec)
            agent_registry._specs[spec_copy.tool_id] = agent_registry._specs.__class__.__new__(
                agent_registry._specs.__class__
            )
            # We need to adapt — the agent.ToolRegistry uses agent.tools.schemas.ToolSpec
            # while the runtime uses tool_runtime.schemas.ToolSpec. Let's check.
            agent_spec = _adapt_to_agent_spec(spec_copy.as_dict())
            agent_registry._specs[spec_copy.tool_id] = agent_spec

        tool_router = ToolRouter.for_turn(agent_registry, allowed_tool_ids=tool_allowlist)

    except Exception as e:
        return {
            "ok": False,
            "final_response": f"Sub-agent initialization failed: {str(e)[:200]}",
            "tool_calls_count": 0,
            "steps": 0,
            "parent_run_id": parent_run_id,
            "child_run_id": child_run_id,
        }

    # ── Run sub-agent loop ──
    tool_calls_count = 0
    steps = 0
    final_response = ""

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
        elif isinstance(result, dict):
            final_response = result.get("final_response", "")
        else:
            final_response = str(result)

        steps = 1  # Single turn count

    except Exception as e:
        final_response = f"Sub-agent execution failed: {str(e)[:500]}"

    return {
        "ok": True,
        "final_response": final_response,
        "tool_calls_count": tool_calls_count,
        "steps": steps,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
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
