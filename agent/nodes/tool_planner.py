# agent/nodes/tool_planner.py
"""DEPRECATED — Agent-supervised Tool Runtime bridge.

This module has been superseded by agent/nodes/llm_orchestrator.py::_handle_llm_disabled().
It is no longer called from any active LangGraph node and will be removed in a future release.

Original purpose: assistant_chat tool execution via ToolRuntimeClient.
"""

import re
from typing import Optional

from agent.state import NetworkAgentState
from tool_runtime.context import ToolRuntimeContext
from tool_runtime.integration import get_default_tool_runtime_client


_TOOL_ID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\b")


def maybe_execute_tool(state: NetworkAgentState) -> bool:
    """Execute an allowed Tool Runtime request for assistant_chat.

    Returns True when this function handled the user input, either by invoking
    a low-risk tool, dry-running a medium-risk tool, or returning a safety block.
    """
    if state.intent != "assistant_chat":
        return False

    text = state.user_input or ""
    client = get_default_tool_runtime_client()

    if _is_tool_catalog_question(text):
        tools = client.list_tools()
        by_risk = {}
        by_category = {}
        for tool in tools:
            by_risk[tool.get("risk_level", "unknown")] = by_risk.get(tool.get("risk_level", "unknown"), 0) + 1
            by_category[tool.get("category", "unknown")] = by_category.get(tool.get("category", "unknown"), 0) + 1
        state.skill_results = {
            "ok": True,
            "mode": "tool_catalog",
            "tool_catalog": {
                "count": len(tools),
                "by_risk": by_risk,
                "by_category": by_category,
                "auto_callable_count": sum(1 for t in tools if _auto_callable(t)),
            },
        }
        state.tool_results = state.skill_results
        state.context["tool_catalog_count"] = len(tools)
        return True

    tool_id = _select_tool_id(text, client.list_tools())
    if not tool_id:
        return False

    spec = client.get_tool(tool_id)
    if not spec:
        return False

    arguments = _build_arguments(tool_id, text, state.workspace_id or "default")
    risk = spec.get("risk_level", "unknown")
    requires_approval = bool(spec.get("requires_approval"))
    dry_run_requested = _wants_dry_run(text)

    if risk == "low" and spec.get("enabled", False) and not requires_approval:
        result = client.invoke(tool_id, arguments, context=_tool_context(state))
        _record_tool_result(state, result, arguments, dry_run=False)
        return True

    if risk == "medium" and spec.get("enabled", False) and dry_run_requested:
        result = client.invoke(tool_id, arguments, dry_run=True, context=_tool_context(state))
        _record_tool_result(state, result, arguments, dry_run=True)
        return True

    reason = "approval_required" if (risk == "high" or requires_approval) else "dry_run_required"
    state.skill_results = {
        "ok": False,
        "mode": "tool_runtime_blocked",
        "tool_id": tool_id,
        "risk_level": risk,
        "requires_approval": requires_approval,
        "reason": reason,
        "dry_run_supported": spec.get("dry_run_supported", False),
    }
    state.tool_results = state.skill_results
    state.warnings.append(f"tool_runtime_blocked:{tool_id}:{reason}")
    return True


def _is_tool_catalog_question(text: str) -> bool:
    lower = text.lower()
    return (
        ("tool" in lower or "工具" in lower)
        and any(k in lower for k in ["多少", "几个", "列表", "清单", "catalog", "能调用", "可以调用"])
    )


def _select_tool_id(text: str, tools: list) -> Optional[str]:
    lower = text.lower()
    explicit = _TOOL_ID_RE.search(lower)
    if explicit:
        return explicit.group(0)

    if any(k in lower for k in ["运行时", "runtime", "健康", "health", "诊断"]):
        return "runtime.health"
    if any(k in lower for k in ["最近运行", "recent run", "run history", "运行记录"]):
        return "run.list"
    if any(k in lower for k in ["workspace", "工作区", "工作空间"]):
        return "workspace.metadata.get"
    if any(k in lower for k in ["artifact", "产物", "文件列表"]):
        return "workspace.artifact.list"
    if any(k in lower for k in ["知识库", "knowledge", "检索", "搜索"]):
        return "knowledge.search"

    tool_ids = {t.get("tool_id") for t in tools}
    for tid in sorted(tool_ids):
        if tid and tid in lower:
            return tid
    return None


def _build_arguments(tool_id: str, text: str, workspace_id: str) -> dict:
    args = {"workspace_id": workspace_id}
    if tool_id in ("knowledge.search", "workspace.artifact.search", "memory.search"):
        args["query"] = _extract_query(text, tool_id)
        args["limit"] = 5
    elif tool_id == "run.list":
        args["limit"] = 5
    elif tool_id == "host.shell.exec":
        pass  # LLM provides the full command
    return args


def _extract_query(text: str, tool_id: str) -> str:
    cleaned = text
    for token in [tool_id, "调用", "搜索", "检索", "知识库", "knowledge.search"]:
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or text.strip()


def _wants_dry_run(text: str) -> bool:
    lower = text.lower()
    return "dry" in lower or "预演" in lower or "试运行" in lower or "不执行" in lower


def _auto_callable(spec: dict) -> bool:
    return spec.get("enabled", False) and spec.get("risk_level") == "low" and not spec.get("requires_approval")


def _tool_context(state: NetworkAgentState) -> ToolRuntimeContext:
    return ToolRuntimeContext(
        workspace_id=state.workspace_id or "default",
        run_id=state.request_id,
        trace_id=state.trace_id or None,
        capability=state.context.get("capability_id"),
        skill=state.selected_skill,
        module=state.active_module,
        requested_by="agent:tool_bridge",
    )


def _record_tool_result(state: NetworkAgentState, result, arguments: dict, dry_run: bool):
    output = result.output if isinstance(result.output, dict) else {}
    safe_result = result.as_dict()
    state.skill_results = {
        "ok": result.status in ("succeeded", "dry_run"),
        "mode": "tool_runtime",
        "tool_id": result.tool_id,
        "status": result.status,
        "summary": result.summary,
        "output": output,
        "arguments": arguments,
        "dry_run": dry_run,
        "tool_result": safe_result,
    }
    state.tool_results = state.skill_results
    state.context.setdefault("tool_invocations", []).append({
        "tool_id": result.tool_id,
        "invocation_id": result.invocation_id,
        "status": result.status,
        "duration_ms": result.duration_ms,
        "dry_run": dry_run,
    })
    state.context["tool_call_count"] = len(state.context.get("tool_invocations", []))
