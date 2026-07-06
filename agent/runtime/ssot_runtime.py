"""SSOT Runtime adapter for the public AgentApp turn contract.

This module is the bridge between the production-facing ``AgentResult``
contract and the SSOT Runtime execution engine. SSOT Runtime owns QueryLoop
planning, tool execution, bounded tracking, retry metadata, and result synthesis;
the actual tool boundary remains ``ToolRuntimeClient``
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
from agent.approval import get_approval_store
from core.runtime_engine.runtime_contracts import ExecutionContract

_LOG = logging.getLogger(__name__)


def run_ssot_turn(
    session,
    turn,
    services=None,
    *,
    allowed_tool_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    requested_by: str = "turn_runner",
    emitter: Any | None = None,
) -> AgentResult:
    """Run one user turn through SSOT Runtime and return the stable AgentResult.

    Args:
        emitter: Optional StreamEmitter (or any object exposing ``emit(event_type, payload)``)
            used by SSOT Runtime to publish per-stage progress events to the WebSocket
            real-time callback. When omitted, SSOT Runtime runs without progress signals
            (used by offline tests / replay tools).
    """
    started = time.monotonic()
    trace_id = build_trace_id()
    workspace_id = getattr(session, "workspace_id", "") or getattr(turn.op, "workspace_id", "")
    session_id = getattr(session, "session_id", "") or getattr(turn.op, "session_id", "")
    user_input = (getattr(turn.op, "user_input", "") or "").strip()
    metadata_in = dict(getattr(turn.op, "metadata", {}) or {})
    _graph_run_started(
        run_id=turn.turn_id,
        workspace_id=workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        user_input=user_input,
    )

    # ── Build canonical conversation context for prompt injection ──
    metadata_in["__raw_user_input"] = user_input
    history_block = _build_history_block(session, user_input=user_input)
    if history_block:
        metadata_in["conversation_history_block"] = history_block

    # Build tool registry once — used for both metadata and engine
    ssot_registry = _build_ssot_runtime_tool_registry(allowed_tool_ids)

    context = SimpleNamespace(
        workspace_id=workspace_id,
        session_id=session_id,
        turn_id=turn.turn_id,
        trace_id=trace_id,
        requested_by=requested_by,
        metadata={
            "runtime_engine": "ssot_runtime",
            "transport": metadata_in.get("transport", ""),
            "stream_mode": metadata_in.get("stream_mode", ""),
            "intent": "assistant_chat",
            "visible_tools": sorted(ssot_registry.keys()),
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
            emitter=emitter,
            prebuilt_registry=ssot_registry,
        )
        runtime_result = _run_async(
            engine.run(
                user_input=user_input,
                workspace_id=workspace_id,
                session_id=session_id,
                extras=metadata_in,
            )
        )

        # ── v3.17: SSOT Runtime approval gate → ApprovalStore → frontend bubble ──
        # When the risk policy requires approval (e.g. destructive commands),
        # create ApprovalStore entries so the frontend ApprovalBubble detects
        # them, then block until the user approves/denies.
        runtime_meta = runtime_result.metadata or {}
        if runtime_meta.get("approval_required") and runtime_meta.get("approval_nodes"):
            store = get_approval_store()
            approval_ids: list[str] = []
            approval_details = runtime_meta.get("approval_details") or []
            for detail in approval_details:
                tool_id = detail.get("tool", "unknown")
                reason = detail.get("risk_reason", "高危操作需要确认")
                cmd = detail.get("command", "")
                desc = f"{reason}: {tool_id}"
                if cmd:
                    desc += f" → {cmd[:120]}"
                req = store.create(
                    session_id=session_id,
                    tool_id=tool_id,
                    arguments=detail,
                    description=desc,
                    risk_level=runtime_meta.get("risk_level", "high"),
                    workspace_id=workspace_id,
                    run_id=turn.turn_id,
                )
                approval_ids.append(req.approval_id)

            # If no approval_details, create one entry for all nodes
            if not approval_details:
                nodes = runtime_meta["approval_nodes"]
                tools = runtime_meta.get("tool_summary", [])
                req = store.create(
                    session_id=session_id,
                    tool_id=", ".join(tools) if tools else ", ".join(nodes),
                    arguments={"nodes": nodes},
                    description=runtime_meta.get("approval_reason", "高危操作需要确认"),
                    risk_level=runtime_meta.get("risk_level", "high"),
                    workspace_id=workspace_id,
                    run_id=turn.turn_id,
                )
                approval_ids.append(req.approval_id)

            # Wait for approvals (non-blocking poll, max 30s)
            approved = True
            for aid in approval_ids:
                waited = 0.0
                while waited < 30:
                    result = store.wait(aid, blocking=False)
                    if result is True:
                        break  # approved
                    if result is False:
                        approved = False  # denied
                        break
                    # P2-1: synchronous poll blocks facade thread up to 30s.
                    # Consider async approval with threading.Event or asyncio.
                    time.sleep(0.5)
                    waited += 0.5
                else:
                    # Timeout: fail closed — deny execution when approval does not arrive in time
                    approved = False

            if approved:
                # Re-run with approval bypass flag
                metadata_in["approved_risk"] = True
                engine2 = _build_engine(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    run_id=turn.turn_id,
                    trace_id=trace_id,
                    allowed_tool_ids=allowed_tool_ids,
                    requested_by=requested_by,
                    emitter=emitter,
                )
                runtime_result = _run_async(
                    engine2.run(
                        user_input=user_input,
                        workspace_id=workspace_id,
                        session_id=session_id,
                        extras=metadata_in,
                    )
                )
            else:
                # User denied — return rejection result
                denied_result = AgentResult(
                    ok=True,
                    final_response="操作已取消（审批未通过）。",
                    events=events,
                    trace_id=trace_id,
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    tool_calls=[],
                    metadata={
                        **context.metadata,
                        "runtime_engine": "ssot_runtime",
                        "ssot_runtime": runtime_meta,
                        "approval_denied": True,
                    },
                )
                _graph_run_finished(
                    run_id=turn.turn_id,
                    result=denied_result,
                    runtime_result=None,
                    user_input=user_input,
                )
                _sync_session_history(session, user_input, denied_result.final_response)
                persist_run_record(session, turn, denied_result, context)
                return denied_result

        final_response = _final_response(runtime_result)
        tool_calls = _project_tool_calls(runtime_result)
        events.extend(_project_events(runtime_result, trace_id, turn.turn_id))
        events.append(_event("final", "final", trace_id, turn.turn_id, started_at=started))

        timeline_summary = _timeline_summary(
            started=started,
            events=events,
            tool_calls=tool_calls,
            runtime_result=runtime_result,
        )
        metadata = {
            **context.metadata,
            "runtime_engine": "ssot_runtime",
            "ssot_runtime": runtime_result.metadata,
            "timeline_summary": timeline_summary,
            "steps": 1,
            "model": _current_model_name(),
            "llm": {
                "used": True,
                "provider": _current_provider_name(),
                "model": _current_model_name(),
                "task": "assistant_chat",
            },
            # v3.10 (tool retry): top-level projections so the
            # frontend / API consumers don't have to walk through
            # ``metadata.runtime.*`` to find the retry surface. The
            # canonical source stays inside ``metadata.runtime``; the
            # top-level fields are read-only mirrors maintained for
            # convenience. If both fields are present they MUST be
            # byte-identical.
            "retry_summary": dict(
                (runtime_result.metadata or {}).get("retry_summary")
                or {
                    "retry_attempts": 0,
                    "retried_nodes": [],
                    "retry_succeeded": 0,
                    "retry_failed": 0,
                    "retry_blocked": 0,
                },
            ),
            "retry_events": list(
                (runtime_result.metadata or {}).get("retry_events") or []
            ),
        }
        result = AgentResult(
            ok=bool(runtime_result.success),
            final_response=final_response,
            events=events,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn.turn_id,
            tool_calls=tool_calls,
            warnings=[],
            errors=list(runtime_result.errors or []),
            metadata=metadata,
            error_type="" if runtime_result.success else "ssot_runtime_error",
            tool_decision=_tool_decision(runtime_result, tool_calls),
            no_tool_reason="" if tool_calls else "SSOT Runtime planner selected no tools.",
        )

    except Exception as exc:
        _LOG.exception("SSOT Runtime turn failed")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        events.append(_event("error", "SSOT Runtime error", trace_id, turn.turn_id, started_at=started))
        result = AgentResult(
            ok=False,
            final_response=f"SSOT Runtime failed: {str(exc)[:300]}",
            events=events,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn.turn_id,
            errors=[str(exc)[:500]],
            metadata={
                **context.metadata,
                "runtime_engine": "ssot_runtime",
                "timeline_summary": {
                    "node_count": len(events),
                    "total_duration_ms": elapsed_ms,
                    "artifact_saved_count": 0,
                },
            },
            error_type="ssot_runtime_error",
            tool_decision={"needed": False, "reason": "SSOT Runtime failed before execution."},
            no_tool_reason="ssot_runtime_error",
        )

    # ── Section 2: unified exit — sync session.history for both success
    #    and exception paths so the next turn always has context.
    _graph_run_finished(
        run_id=turn.turn_id,
        result=result,
        runtime_result=locals().get("runtime_result"),
        user_input=user_input,
    )
    _sync_session_history(session, user_input, result.final_response)

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
    emitter: Any | None = None,
    prebuilt_registry: dict[str, dict[str, Any]] | None = None,
):
    from core.runtime_engine import SSOTRuntimeConfig, SSOTRuntimeEngine

    config = SSOTRuntimeConfig(
        enable_finalizer=True,
        max_global_concurrency=8,
        max_layer_concurrency=5,
        max_llm_calls=50,
        max_total_seconds=180,
        max_tool_seconds=120,
        single_node_timeout_ms=120_000,
        parallel_layer_timeout_ms=300_000,
        tracking_max_seconds=150,
        tracking_max_polls=40,
        tracking_poll_interval_cap_seconds=5,
    )
    registry = prebuilt_registry or _build_ssot_runtime_tool_registry(allowed_tool_ids)
    engine_kwargs: dict[str, Any] = {
        "config": config,
        "llm_invoke": _invoke_llm_for_ssot_runtime,
        "tool_registry": registry,
    }
    if emitter is not None:
        engine_kwargs["emitter"] = emitter
    engine = SSOTRuntimeEngine(**engine_kwargs)
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


def _build_ssot_runtime_tool_registry(allowed_tool_ids=None) -> dict[str, dict[str, Any]]:
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
    from core.tools.integration import get_default_tool_runtime_client
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
        from core.tools.context import ToolRuntimeContext

        ctx = ToolRuntimeContext(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            trace_id=trace_id,
            requested_by=requested_by,
            module="ssot_runtime",
        )
        args = dict(args or {})
        # Inject runtime context into args so tool handlers can access
        # session_id / run_id without relying on ToolInvocation fields
        if tool_id.startswith("inspection."):
            args.setdefault("session_id", session_id)
            args.setdefault("run_id", run_id)
            args.setdefault("workspace_id", workspace_id)
        result = await asyncio.to_thread(client.invoke, tool_id, args, context=ctx)
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


def _invoke_llm_for_ssot_runtime(**kwargs) -> str:
    from agent.llm.runtime import invoke_llm
    from agent.runtime.token_tracker import record_llm_call

    system = str(kwargs.get("system") or "")
    user = str(kwargs.get("user") or "")
    is_planner = "execution planner" in system.lower()
    caller_extra = kwargs.get("extra") or {}
    tools = kwargs.get("tools") or None
    session_id = str(kwargs.get("session_id") or caller_extra.get("session_id") or "").strip()
    workspace_id = str(kwargs.get("workspace_id") or caller_extra.get("workspace_id") or "").strip()

    extra = {
        "runtime_engine": "ssot_runtime",
        "planner": is_planner,
        "stream_to_user": not is_planner,
        "stream_scope": "planner" if is_planner else "finalizer",
    }
    if caller_extra:
        extra.update(caller_extra)

    config_override = None
    timeout = kwargs.get("timeout")
    if timeout is not None:
        config_override = {"timeout": int(timeout)}

    resp = invoke_llm(
        task="assistant_chat",
        messages=[
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ],
        tools=tools,
        user_input=user,
        extra=extra,
        config_override=config_override,
    )

    # Track token usage
    if workspace_id:
        try:
            usage = resp.usage or {}
            record_llm_call(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                session_id=session_id,
                workspace_id=workspace_id,
                model=resp.model or "",
                provider=resp.provider or "",
            )
        except Exception:
            _LOG.debug("record_llm_call failed", exc_info=True)

    if resp.error:
        # If streaming produced partial content before error, return it
        # instead of failing entirely (common with timeout on slow providers).
        # v4.1: accept ANY non-empty content — even a single character is
        # better than a generic fallback.
        if resp.content and resp.content.strip():
            return resp.content.strip()
        raise RuntimeError(resp.error)

    # Handle tool_calls response (Function Calling mode)
    tool_calls = getattr(resp, "tool_calls", []) or []
    if tool_calls:
        nodes = []
        for tc in tool_calls:
            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            tc_args = tc.get("arguments", "{}") if isinstance(tc, dict) else getattr(tc, "arguments", "{}")
            if isinstance(tc_args, str):
                try:
                    tc_args = json.loads(tc_args)
                except json.JSONDecodeError:
                    tc_args = {}
            nodes.append({
                "id": f"n{len(nodes)}",
                "tool": tc_name.replace("__", "."),
                "args": tc_args,
                "deps": [],
            })
        return json.dumps({"nodes": nodes, "final_response": ""}, ensure_ascii=False)

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


_BOGUS_FINAL_PATTERNS = (
    "收到",
    "已完成。",
    "工具执行成功",
    "工具执行完成",
    "No tools were executed",
    "readartifact completed",
    "readartifact succeeded",
)


def _is_bogus_final(text: str) -> bool:
    """Return True when *text* is a placeholder stub rather than
    a real answer produced by the finalizer LLM."""
    t = text.strip()
    if len(t) <= 10:
        return True
    return any(p in t for p in _BOGUS_FINAL_PATTERNS)


def _final_response(runtime_result) -> str:
    text = str(getattr(runtime_result, "final_response", "") or "").strip()

    # v3.16: if the final response is a known placeholder but we
    # have actual tool results, degrade gracefully instead of
    # returning a useless stub like "收到。".
    if text and _is_bogus_final(text):
        text = ""  # fall through to meaningful defaults

    if text:
        return text
    if runtime_result.node_results:
        ok = runtime_result.node_success_count
        failed = runtime_result.node_failure_count
        return f"工具执行完成：成功 {ok} 个，失败 {failed} 个。"
    if runtime_result.errors:
        return "任务执行失败：" + "; ".join(str(e) for e in runtime_result.errors[:3])
    return "收到。"


def _project_tool_calls(runtime_result) -> list[dict[str, Any]]:
    calls = []
    for node_id, tr in (runtime_result.node_results or {}).items():
        data = tr.data if isinstance(tr.data, dict) else {"value": tr.data}
        raw_ids = list(data.get("artifact_ids") or [])
        # Normalise artifacts: frontend expects objects, not plain strings.
        artifacts: list[dict[str, str]] = []
        for aid in raw_ids:
            if isinstance(aid, dict):
                artifacts.append({
                    "artifact_id": str(aid.get("artifact_id", aid.get("id", ""))),
                    "artifact_type": str(aid.get("artifact_type", aid.get("type", ""))),
                    "title": str(aid.get("title", aid.get("name", ""))),
                })
            elif isinstance(aid, str):
                artifacts.append({
                    "artifact_id": aid,
                    "artifact_type": "",
                    "title": aid,
                })

        calls.append({
            "call_id": node_id,
            "tool_id": tr.tool,
            "ok": bool(tr.success),
            "status": "succeeded" if tr.success else "failed",
            "summary": _tool_summary(data, tr),
            "result": data.get("output", data),
            "duration_ms": tr.latency_ms,
            "errors": list(data.get("errors") or ([tr.error] if tr.error else [])),
            "warnings": list(data.get("warnings") or []),
            "artifacts": artifacts,
            "metadata": {
                "runtime_engine": "ssot_runtime",
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


def _project_events(runtime_result, trace_id: str, turn_id: str) -> list[dict[str, Any]]:
    events = []
    for node_id, tr in (runtime_result.node_results or {}).items():
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
    for idx, ev in enumerate((runtime_result.metadata or {}).get("retry_events") or []):
        if not isinstance(ev, dict):
            continue
        events.append({
            "event_id": f"retry-{turn_id}-{idx}",
            "event_type": "tool_retry",
            "type": "tool_retry",
            "name": "工具自动重试",
            "status": ev.get("final_status") or ("succeeded" if ev.get("retry_allowed") else "blocked"),
            "summary": _retry_event_summary(ev),
            "tool_id": ev.get("tool_id", ""),
            "node_id": ev.get("node_id", ""),
            "trace_id": trace_id,
            "run_id": turn_id,
            "timestamp": time.time(),
            "duration_ms": ev.get("duration_ms", 0),
            "metadata": ev,
        })
    return events


def _retry_event_summary(ev: dict[str, Any]) -> str:
    tool_id = str(ev.get("tool_id") or ev.get("node_id") or "tool")
    reason = str(ev.get("reason") or ev.get("error_code") or "")
    if ev.get("retry_allowed"):
        if str(ev.get("final_status") or "") == "succeeded":
            return f"{tool_id} 首次失败后已自动重试并恢复"
        return f"{tool_id} 已按策略重试，但仍未完成"
    if ev.get("blocked_by_policy"):
        return f"{tool_id} 未重试：{reason or '策略禁止重试'}"
    return f"{tool_id} 未触发重试：{reason or '不满足重试条件'}"


def _event(event_type: str, name: str, trace_id: str, turn_id: str, *, started_at: float) -> dict[str, Any]:
    return {
        "type": event_type,
        "name": name,
        "trace_id": trace_id,
        "run_id": turn_id,
        "timestamp": time.time(),
        "duration_ms": int((time.monotonic() - started_at) * 1000),
    }


def _timeline_summary(*, started: float, events: list, tool_calls: list, runtime_result) -> dict[str, Any]:
    return {
        "node_count": max(len(events), 1),
        "total_duration_ms": int((time.monotonic() - started) * 1000),
        "artifact_saved_count": sum(len(c.get("artifacts") or []) for c in tool_calls),
        "execution_duration_ms": int(getattr(runtime_result, "execution_latency_ms", 0) or 0),
        "llm_calls": int((runtime_result.metadata or {}).get("llm_calls", 0) or 0),
        "tool_calls": len(tool_calls),
        "max_parallel_width": int((runtime_result.metadata or {}).get("metrics", {}).get("max_parallel_width", 0) or 0),
    }


def _tool_decision(runtime_result, tool_calls: list) -> dict[str, Any]:
    if not tool_calls:
        return {"needed": False, "reason": "SSOT Runtime planner selected no tools.", "selected_tools": []}
    return {
        "needed": True,
        "reason": "SSOT Runtime execution graph selected tool nodes.",
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


# ── GraphStore SSOT projection ─────────────────────────────────────

def _graph_run_started(
    *,
    run_id: str,
    workspace_id: str,
    session_id: str,
    trace_id: str,
    user_input: str,
) -> None:
    """Append the production turn boundary to the canonical GraphStore."""
    try:
        from core.graph.graph_store import EventType, get_graph_store

        store = get_graph_store()
        store.append(EventType.RUN_CREATED, run_id, {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "input": user_input,
        })
        store.append(EventType.RUN_STARTED, run_id, {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "trace_id": trace_id,
        })
    except Exception:
        _LOG.debug("GraphStore run-start append failed for %s", run_id, exc_info=True)


def _graph_run_finished(
    *,
    run_id: str,
    result: AgentResult,
    runtime_result: Any | None,
    user_input: str,
) -> None:
    """Append planner/tool/final projections for a completed public turn."""
    try:
        from core.graph.graph_store import EventType, get_graph_store

        store = get_graph_store()
        tool_calls = list(getattr(result, "tool_calls", []) or [])
        nodes = [
            {
                "id": str(tc.get("node_id") or tc.get("tool_call_id") or f"node_{i}"),
                "tool": str(tc.get("tool_id") or tc.get("tool") or ""),
                "args": dict(tc.get("arguments") or {}),
                "deps": [],
            }
            for i, tc in enumerate(tool_calls)
            if isinstance(tc, dict)
        ]
        store.append(EventType.PLAN_GENERATED, run_id, {
            "nodes": nodes,
            "node_count": len(nodes),
            "user_input": user_input,
        })
        for node, tc in zip(nodes, tool_calls):
            node_id = node["id"]
            if not isinstance(tc, dict):
                continue
            ok = bool(tc.get("ok", tc.get("success", True)))
            payload = {
                "node_id": node_id,
                "tool": node["tool"],
                "result": {
                    "ok": ok,
                    "summary": tc.get("summary") or tc.get("content") or "",
                    "latency_ms": tc.get("latency_ms", 0),
                    "artifacts": tc.get("artifacts") or [],
                },
            }
            store.append(EventType.NODE_STARTED, run_id, {
                "node_id": node_id,
                "tool": node["tool"],
            })
            if ok:
                store.append(EventType.NODE_COMPLETED, run_id, payload)
            else:
                store.append(EventType.NODE_FAILED, run_id, {
                    **payload,
                    "error": tc.get("error") or tc.get("summary") or "tool failed",
                })
        store.append(EventType.FINAL_RESPONSE, run_id, {
            "text": getattr(result, "final_response", "") or "",
        })
        if getattr(result, "ok", False):
            store.append(EventType.RUN_COMPLETED, run_id, {})
        else:
            store.append(EventType.RUN_FAILED, run_id, {
                "errors": list(getattr(result, "errors", []) or []),
                "runtime_errors": list(getattr(runtime_result, "errors", []) or []) if runtime_result else [],
            })
    except Exception:
        _LOG.debug("GraphStore run-finish append failed for %s", run_id, exc_info=True)


# ── Conversation history block builder ──────────────────────────────

_HISTORY_MAX_CHARS = 12000
_HISTORY_RECENT_MESSAGES = 30
_HISTORY_MESSAGE_MAX_CHARS = 1200
_HISTORY_SUMMARY_MAX_CHARS = 2500
_HISTORY_REFERENCE_PATTERNS = (
    "前面", "之前", "上次", "刚才", "继续", "还记得", "记得",
    "那个", "上一轮", "前一轮", "前面的", "之前的", "刚才的",
)


def _build_history_block(session, *, user_input: str = "") -> str:
    """Build prompt-ready conversation context from the session message SSOT.

    Source order:
      1. ``SessionMessageStore`` full persisted messages
      2. in-memory ``session.history`` entries not yet flushed

    The block keeps recent messages verbatim, summarizes older turns, and
    pulls a small retrieved-history section when the current input references
    earlier conversation. This preserves long-session entities without reviving
    a second runtime path.
    """
    try:
        messages = _load_context_messages(session)
        if not messages:
            return ""

        recent = messages[-_HISTORY_RECENT_MESSAGES:]
        older = messages[:-_HISTORY_RECENT_MESSAGES]
        parts: list[str] = []
        if older:
            summary = _summarize_older_messages(older)
            if summary:
                parts.append("SESSION SUMMARY:\n" + summary)
        retrieved = _retrieve_history_references(messages, user_input)
        if retrieved:
            parts.append("RETRIEVED HISTORY:\n" + "\n".join(
                f"  [{m['role']}] {_truncate(m['content'], _HISTORY_MESSAGE_MAX_CHARS)}"
                for m in retrieved
            ))
        if recent:
            parts.append("RECENT CONVERSATION HISTORY:\n" + "\n".join(
                f"  [{m['role']}] {_truncate(m['content'], _HISTORY_MESSAGE_MAX_CHARS)}"
                for m in recent
            ))
        block = "\n\n".join(parts)
        return _truncate(block, _HISTORY_MAX_CHARS)
    except Exception:
        _LOG.debug("conversation history block build failed", exc_info=True)
        return ""


def _load_context_messages(session) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    seen: set[str] = set()
    ws_id = str(getattr(session, "workspace_id", "") or "")
    session_id = str(getattr(session, "session_id", "") or "")
    if ws_id and session_id:
        try:
            from workspace.message_store import SessionMessageStore

            for m in SessionMessageStore(session_id=session_id, ws_id=ws_id).get_messages():
                _append_context_message(messages, seen, m)
        except Exception:
            _LOG.debug("SessionMessageStore history read failed for %s", session_id, exc_info=True)

    for i, msg in enumerate(list(getattr(session, "history", None) or [])):
        role = str(getattr(msg, "role", "") or "")
        content = str(getattr(msg, "content", "") or "")
        _append_context_message(messages, seen, {
            "message_id": getattr(msg, "id", "") or getattr(msg, "message_id", "") or f"mem:{i}:{role}:{content[:40]}",
            "role": role,
            "content": content,
        })
    return messages


def _append_context_message(messages: list[dict[str, str]], seen: set[str], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    role = str(raw.get("role") or "")
    content = str(raw.get("content") or "").strip()
    if role not in ("user", "assistant") or not content:
        return
    key = str(raw.get("message_id") or raw.get("id") or raw.get("run_id") or f"{role}:{content[:80]}")
    if key in seen:
        return
    seen.add(key)
    messages.append({"role": role, "content": content})


def _summarize_older_messages(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for m in messages:
        content = m["content"]
        if _looks_context_important(content):
            lines.append(f"  [{m['role']}] {_truncate(content, 350)}")
        if len("\n".join(lines)) >= _HISTORY_SUMMARY_MAX_CHARS:
            break
    if not lines and messages:
        sample = messages[:3] + messages[-3:]
        for m in sample:
            lines.append(f"  [{m['role']}] {_truncate(m['content'], 220)}")
    if not lines:
        return ""
    return _truncate("\n".join(lines), _HISTORY_SUMMARY_MAX_CHARS)


def _retrieve_history_references(messages: list[dict[str, str]], user_input: str) -> list[dict[str, str]]:
    text = (user_input or "").strip()
    if not text or not any(p in text for p in _HISTORY_REFERENCE_PATTERNS):
        return []
    terms = {
        token.strip("，。,.、：:；;（）()[]【】\"'")
        for token in text.replace("/", " ").replace("-", " ").split()
        if len(token.strip()) >= 2
    }
    important: list[dict[str, str]] = []
    for m in messages[:-_HISTORY_RECENT_MESSAGES]:
        content = m["content"]
        if (terms and any(t in content for t in terms)) or _looks_context_important(content):
            important.append(m)
    return important[-8:]


def _looks_context_important(text: str) -> bool:
    markers = (
        "ASBR", "BGP", "OSPF", "IP", "设备", "巡检", "区域", "CMDB",
        "报告", "资产", "故障", "异常", "配置", "记住", "总结", "结论",
    )
    return any(m in text for m in markers)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


# ── Session history sync ──────────────────────────────────────

def _sync_session_history(session, user_input: str, final_response: str) -> None:
    """Append current turn to session.history for context in next turns."""
    try:
        from agent.protocol.message import UserMessage, AssistantMessage

        history = getattr(session, "history", None)
        if history is None:
            history = []
            session.history = history

        # Dedup check: skip if last entries already match
        if len(history) >= 2:
            last_user = history[-2]
            last_asst = history[-1]
            if (getattr(last_user, "role", "") == "user"
                and getattr(last_asst, "role", "") == "assistant"
                and getattr(last_user, "content", "") == user_input
                and getattr(last_asst, "content", "") == final_response):
                return

        history.append(UserMessage(content=user_input))
        history.append(AssistantMessage(content=final_response))
    except Exception:
        pass
