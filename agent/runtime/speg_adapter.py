"""SPEG adapter for the public AgentApp turn contract.

This module is the bridge between the production-facing ``AgentResult``
contract and the SPEG execution engine.  SPEG owns planning, DAG scheduling
and result synthesis; the actual tool boundary remains ``ToolRuntimeClient``
so manifest, policy, redaction and audit behavior are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace
from typing import Any

from agent.llm.schemas import LLMMessage
from agent.runtime.result import AgentResult
from agent.runtime.turn_persistence import persist_run_record
from agent.runtime.query_engine import build_trace_id
from agent.runtime.utils import now_iso

_LOG = logging.getLogger(__name__)


def run_speg_turn(
    session,
    turn,
    services=None,
    *,
    allowed_tool_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    requested_by: str = "turn_runner",
) -> AgentResult:
    """Run one user turn through SPEG and return the stable AgentResult."""
    started = time.monotonic()
    trace_id = build_trace_id()
    workspace_id = getattr(session, "workspace_id", "") or getattr(turn.op, "workspace_id", "")
    session_id = getattr(session, "session_id", "") or getattr(turn.op, "session_id", "")
    user_input = (getattr(turn.op, "user_input", "") or "").strip()
    metadata_in = dict(getattr(turn.op, "metadata", {}) or {})

    context = SimpleNamespace(
        workspace_id=workspace_id,
        session_id=session_id,
        turn_id=turn.turn_id,
        trace_id=trace_id,
        requested_by=requested_by,
        metadata={
            "runtime_engine": "speg",
            "transport": metadata_in.get("transport", ""),
            "stream_mode": metadata_in.get("stream_mode", ""),
            "intent": "assistant_chat",
            "visible_tools": sorted(_build_speg_tool_registry(allowed_tool_ids).keys()),
            "requested_by": requested_by,
        },
    )

    events: list[dict[str, Any]] = [
        _event("turn_start", "轮次开始", trace_id, turn.turn_id, started_at=started),
        _event("model", "model", trace_id, turn.turn_id, started_at=started),
    ]

    try:
        engine = _build_engine(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=turn.turn_id,
            trace_id=trace_id,
            allowed_tool_ids=allowed_tool_ids,
            requested_by=requested_by,
        )
        speg_result = _run_async(
            engine.run(
                user_input=user_input,
                workspace_id=workspace_id,
                session_id=session_id,
            )
        )
        final_response = _final_response(speg_result)
        tool_calls = _project_tool_calls(speg_result)
        events.extend(_project_events(speg_result, trace_id, turn.turn_id))
        events.append(_event("final", "final", trace_id, turn.turn_id, started_at=started))

        timeline_summary = _timeline_summary(
            started=started,
            events=events,
            tool_calls=tool_calls,
            speg_result=speg_result,
        )
        metadata = {
            **context.metadata,
            "runtime_engine": "speg",
            "speg": speg_result.metadata,
            "timeline_summary": timeline_summary,
            "steps": 1,
            "model": _current_model_name(),
            "llm": {
                "used": True,
                "provider": _current_provider_name(),
                "model": _current_model_name(),
                "task": "assistant_chat",
            },
        }
        result = AgentResult(
            ok=bool(speg_result.success),
            final_response=final_response,
            events=events,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn.turn_id,
            tool_calls=tool_calls,
            warnings=[],
            errors=list(speg_result.errors or []),
            metadata=metadata,
            error_type="" if speg_result.success else "speg_runtime_error",
            tool_decision=_tool_decision(speg_result, tool_calls),
            no_tool_reason="" if tool_calls else "SPEG planner selected no tools.",
        )
    except Exception as exc:
        _LOG.exception("SPEG turn failed")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        events.append(_event("error", "SPEG runtime error", trace_id, turn.turn_id, started_at=started))
        result = AgentResult(
            ok=False,
            final_response=f"SPEG runtime failed: {str(exc)[:300]}",
            events=events,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn.turn_id,
            errors=[str(exc)[:500]],
            metadata={
                **context.metadata,
                "runtime_engine": "speg",
                "timeline_summary": {
                    "node_count": len(events),
                    "total_duration_ms": elapsed_ms,
                    "artifact_saved_count": 0,
                },
            },
            error_type="speg_runtime_error",
            tool_decision={"needed": False, "reason": "SPEG runtime failed before execution."},
            no_tool_reason="speg_runtime_error",
        )

    persist_run_record(session, turn, result, context)
    return result


def _build_engine(
    *,
    workspace_id: str,
    session_id: str,
    run_id: str,
    trace_id: str,
    allowed_tool_ids=None,
    requested_by: str,
):
    from speg_engine import SPEGConfig, SPEGEngine

    config = SPEGConfig(
        enable_finalizer=True,
        max_global_concurrency=8,
        max_layer_concurrency=5,
        max_llm_calls=2,
        max_total_seconds=180,
        max_tool_seconds=120,
        single_node_timeout_ms=120_000,
        parallel_layer_timeout_ms=300_000,
    )
    registry = _build_speg_tool_registry(allowed_tool_ids)
    engine = SPEGEngine(
        config=config,
        llm_invoke=_invoke_llm_for_speg,
        tool_registry=registry,
    )
    client = _tool_runtime_client()

    for tool_id in registry:
        engine.register_tool(
            tool_id,
            _make_tool_handler(
                client=client,
                tool_id=tool_id,
                workspace_id=workspace_id,
                session_id=session_id,
                run_id=run_id,
                trace_id=trace_id,
                requested_by=requested_by,
            ),
            description=registry[tool_id].get("description", ""),
            args_schema=registry[tool_id].get("args_schema", {}),
        )
    return engine


def _build_speg_tool_registry(allowed_tool_ids=None) -> dict[str, dict[str, Any]]:
    client = _tool_runtime_client()
    tools = {}
    allowed = set(allowed_tool_ids or []) if allowed_tool_ids else None
    for item in client.list_tools():
        tool_id = str(item.get("tool_id") or "")
        if not tool_id:
            continue
        if allowed is not None and tool_id not in allowed:
            continue
        if item.get("enabled") is False or item.get("callable_by_llm") is False:
            continue
        if item.get("forbidden") is True:
            continue
        tools[tool_id] = {
            "description": str(item.get("description") or tool_id),
            "args_schema": item.get("input_schema") or {},
            "category": item.get("category") or "",
            "risk_level": item.get("risk_level") or "low",
        }
    return tools


def _tool_runtime_client():
    from tool_runtime.integration import get_default_tool_runtime_client
    return get_default_tool_runtime_client()


def _make_tool_handler(
    *,
    client,
    tool_id: str,
    workspace_id: str,
    session_id: str,
    run_id: str,
    trace_id: str,
    requested_by: str,
):
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        from tool_runtime.context import ToolRuntimeContext

        ctx = ToolRuntimeContext(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            trace_id=trace_id,
            requested_by=requested_by,
            module="speg_runtime",
        )
        result = await asyncio.to_thread(client.invoke, tool_id, args or {}, context=ctx)
        return {
            "status": result.status,
            "ok": result.status in ("succeeded", "dry_run"),
            "summary": result.summary or "",
            "output": result.output or {},
            "artifact_ids": list(result.artifact_ids or []),
            "warnings": list(result.warnings or []),
            "errors": list(result.errors or []),
            "duration_ms": result.duration_ms,
            "redacted": bool(result.redacted),
        }

    return _handler


def _invoke_llm_for_speg(**kwargs) -> str:
    from agent.llm.runtime import invoke_llm

    system = str(kwargs.get("system") or "")
    user = str(kwargs.get("user") or "")
    is_planner = "execution planner" in system.lower()
    resp = invoke_llm(
        task="assistant_chat",
        messages=[
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ],
        tools=None,
        user_input=user,
        extra={"runtime_engine": "speg", "planner": is_planner},
    )
    if resp.error:
        raise RuntimeError(resp.error)
    content = (resp.content or "").strip()
    if is_planner and not _looks_like_plan_json(content):
        return json.dumps({"nodes": [], "final_response": content}, ensure_ascii=False)
    return content


def _looks_like_plan_json(text: str) -> bool:
    try:
        data = json.loads(_strip_fences(text))
    except Exception:
        return False
    return isinstance(data, dict) and isinstance(data.get("nodes", []), list)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _run_async(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    box: dict[str, Any] = {}

    def _target():
        try:
            box["result"] = asyncio.run(awaitable)
        except Exception as exc:  # pragma: no cover - defensive branch
            box["error"] = exc

    import threading

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _final_response(speg_result) -> str:
    text = str(getattr(speg_result, "final_response", "") or "").strip()
    if text:
        return text
    if speg_result.node_results:
        ok = speg_result.node_success_count
        failed = speg_result.node_failure_count
        return f"工具执行完成：成功 {ok} 个，失败 {failed} 个。"
    if speg_result.errors:
        return "任务执行失败：" + "; ".join(str(e) for e in speg_result.errors[:3])
    return "收到。"


def _project_tool_calls(speg_result) -> list[dict[str, Any]]:
    calls = []
    for node_id, tr in (speg_result.node_results or {}).items():
        data = tr.data if isinstance(tr.data, dict) else {"value": tr.data}
        calls.append({
            "call_id": node_id,
            "tool_id": tr.tool,
            "ok": bool(tr.success),
            "status": "succeeded" if tr.success else "failed",
            "summary": _tool_summary(data, tr),
            "result": data.get("output", data),
            "errors": list(data.get("errors") or ([tr.error] if tr.error else [])),
            "warnings": list(data.get("warnings") or []),
            "artifacts": list(data.get("artifact_ids") or []),
            "metadata": {
                "runtime_engine": "speg",
                "node_id": node_id,
                "duration_ms": tr.latency_ms,
                "redacted": bool(data.get("redacted", True)),
            },
        })
    return calls


def _tool_summary(data: dict[str, Any], tr) -> str:
    for key in ("summary", "message", "error"):
        value = data.get(key)
        if value:
            return str(value)[:500]
    if tr.error:
        return str(tr.error)[:500]
    return "Tool completed" if tr.success else "Tool failed"


def _project_events(speg_result, trace_id: str, turn_id: str) -> list[dict[str, Any]]:
    events = []
    for node_id, tr in (speg_result.node_results or {}).items():
        events.append({
            "type": "tool_call",
            "name": "tool_call",
            "tool_id": tr.tool,
            "node_id": node_id,
            "trace_id": trace_id,
            "run_id": turn_id,
            "timestamp": time.time(),
            "status": "started",
        })
        events.append({
            "type": "tool_result",
            "name": "tool_result",
            "tool_id": tr.tool,
            "node_id": node_id,
            "trace_id": trace_id,
            "run_id": turn_id,
            "timestamp": time.time(),
            "status": "success" if tr.success else "failed",
            "ok": bool(tr.success),
            "summary": _tool_summary(tr.data if isinstance(tr.data, dict) else {}, tr),
            "duration_ms": tr.latency_ms,
        })
    return events


def _event(event_type: str, name: str, trace_id: str, turn_id: str, *, started_at: float) -> dict[str, Any]:
    return {
        "type": event_type,
        "name": name,
        "trace_id": trace_id,
        "run_id": turn_id,
        "timestamp": time.time(),
        "duration_ms": int((time.monotonic() - started_at) * 1000),
    }


def _timeline_summary(*, started: float, events: list, tool_calls: list, speg_result) -> dict[str, Any]:
    return {
        "node_count": max(len(events), 1),
        "total_duration_ms": int((time.monotonic() - started) * 1000),
        "artifact_saved_count": sum(len(c.get("artifacts") or []) for c in tool_calls),
        "execution_duration_ms": int(getattr(speg_result, "execution_latency_ms", 0) or 0),
        "llm_calls": int((speg_result.metadata or {}).get("llm_calls", 0) or 0),
        "tool_calls": len(tool_calls),
        "max_parallel_width": int((speg_result.metadata or {}).get("metrics", {}).get("max_parallel_width", 0) or 0),
    }


def _tool_decision(speg_result, tool_calls: list) -> dict[str, Any]:
    if not tool_calls:
        return {"needed": False, "reason": "SPEG planner selected no tools.", "selected_tools": []}
    return {
        "needed": True,
        "reason": "SPEG execution graph selected tool nodes.",
        "selected_tools": [c["tool_id"] for c in tool_calls],
        "tool_count": len(tool_calls),
    }


def _current_provider_name() -> str:
    try:
        from agent.llm.config import resolve_provider_config
        return str(resolve_provider_config().get("provider") or "")
    except Exception:
        return ""


def _current_model_name() -> str:
    try:
        from agent.llm.config import resolve_provider_config
        return str(resolve_provider_config().get("model") or "")
    except Exception:
        return ""
