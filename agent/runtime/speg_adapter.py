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
    emitter: Any | None = None,
) -> AgentResult:
    """Run one user turn through SPEG and return the stable AgentResult.

    Args:
        emitter: Optional StreamEmitter (or any object exposing ``emit(event_type, payload)``)
            used by SPEG to publish per-stage progress events to the WebSocket
            real-time callback. When omitted, SPEG runs without progress signals
            (used by offline tests / replay tools).
    """
    started = time.monotonic()
    trace_id = build_trace_id()
    workspace_id = getattr(session, "workspace_id", "") or getattr(turn.op, "workspace_id", "")
    session_id = getattr(session, "session_id", "") or getattr(turn.op, "session_id", "")
    user_input = (getattr(turn.op, "user_input", "") or "").strip()
    metadata_in = dict(getattr(turn.op, "metadata", {}) or {})

    # ── v3.14: Conversation Context Injection ───────────────────────
    # Build structured ConversationContext from session history with
    # token-budgeted recent window, session summary, and history
    # reference resolution via message_store.
    metadata_in["__raw_user_input"] = user_input  # needed for ref resolution
    _inject_conversation_context(session, metadata_in)

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
            emitter=emitter,
        )
        speg_result = _run_async(
            engine.run(
                user_input=user_input,
                workspace_id=workspace_id,
                session_id=session_id,
                extras=metadata_in,
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

    # ── Section 2: unified exit — sync session.history for both success
    #    and exception paths so the next turn always has context.
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
    engine_kwargs: dict[str, Any] = {
        "config": config,
        "llm_invoke": _invoke_llm_for_speg,
        "tool_registry": registry,
    }
    if emitter is not None:
        engine_kwargs["emitter"] = emitter
    engine = SPEGEngine(**engine_kwargs)
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
    caller_extra = kwargs.get("extra") or {}

    # v3.11 (stream scope): planner tokens are internal-only
    # (stream_to_user=False); finalizer tokens are user-visible
    # (stream_to_user=True).  This prevents planner JSON / tool
    # selection from leaking into the user-facing token channel, and
    # ensures first_answer_token_ms measures the *answer* token,
    # not the planner's first token.
    #
    # When the caller provides its own ``extra`` (e.g. direct-answer
    # fast path), it takes precedence over the auto-detected values.
    extra = {
        "runtime_engine": "speg",
        "planner": is_planner,
        "stream_to_user": not is_planner,
        "stream_scope": "planner" if is_planner else "finalizer",
    }
    if caller_extra:
        extra.update(caller_extra)

    resp = invoke_llm(
        task="assistant_chat",
        messages=[
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ],
        tools=None,
        user_input=user,
        extra=extra,
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


# ── v3.14: Conversation Context Injection ──────────────────────────────

# Token budget (approximate chars for CJK; 1 char ≈ 0.5–1.0 tokens).
_RECENT_WINDOW_MAX_CHARS = 8000

# Keep at least this many messages regardless of budget.
_RECENT_WINDOW_MIN_MESSAGES = 2

# Max chars for a single message. Content beyond this is truncated
# with a note but the turn boundary is still preserved.
_MAX_SINGLE_MESSAGE_CHARS = 3000

# Max chars for the session_summary block.
_SESSION_SUMMARY_MAX_CHARS = 2000

# Historical-reference patterns that trigger message_store retrieval.
_HISTORY_REFERENCE_PATTERNS = (
    "前面提到的", "刚才那个", "上一个任务", "继续刚才",
    "之前的", "刚才的", "上次我说的", "我上次说了",
    "还记得", "你记得", "之前说的", "再之前的",
    "我说过的", "我提到过", "讨论过", "聊过的",
)


def _inject_conversation_context(session, metadata_in: dict[str, Any]) -> None:
    """Build and inject a full ConversationContext into metadata_in.

    Uses session.history (memory) AND SessionMessageStore (disk) for
    complete history, with:
      - recent_messages: token-budgeted complete turns
      - session_summary: older-message rolling summary
      - previous_user_message / previous_assistant_message: exact
      - retrieved_history: cross-turn reference resolution

    Never raises — injection failure must not break the turn, but
    MUST log the error so diagnostics can see injection failures.
    """
    error_reason = None
    try:
        from speg_engine.models import ConversationContext

        cc = ConversationContext()
        _populate_from_session(session, cc)
        _resolve_history_references(session, metadata_in, cc)

        metadata_in["conversation_context"] = cc
        metadata_in["conversation_history"] = cc.recent_messages
        metadata_in["session_summary"] = cc.session_summary
        metadata_in["previous_user_message"] = cc.previous_user_message
        metadata_in["previous_assistant_message"] = cc.previous_assistant_message

    except Exception as e:
        error_reason = f"{type(e).__name__}: {e}"
    finally:
        if error_reason:
            metadata_in["conversation_context_error"] = error_reason
            try:
                _LOG.warning("Conversation context injection failed: %s", error_reason)
            except Exception:
                pass


def _populate_from_session(session, cc) -> None:
    """Populate ConversationContext from session.history (memory) AND
    SessionMessageStore (disk).

    Merge strategy:
      1. Read complete history from SessionMessageStore (disk).
      2. Merge session.history (in-memory) for latest unsaved turns.
      3. Dedup by (role, content, run_id).
      4. Sort chronologically, feed into window/summary/previous.
    """
    # ── 1. Read from SessionMessageStore (disk) ──────────────────
    disk_messages: list[dict[str, str]] = []
    ws_id = getattr(session, "workspace_id", "") or "default"
    sid = getattr(session, "session_id", "")
    if sid:
        try:
            from workspace.message_store import SessionMessageStore
            store = SessionMessageStore(session_id=sid, ws_id=ws_id)
            raw = store.get_messages()
            for m in raw:
                role = m.get("role", "")
                content = m.get("content", "")
                if role in ("user", "assistant") and content.strip():
                    disk_messages.append({
                        "role": role,
                        "content": content,
                        "_run_id": m.get("run_id", ""),
                        "_created_at": m.get("created_at", ""),
                    })
        except Exception:
            # Disk read failure → fall back to session.history
            pass

    # ── 2. Read from session.history (in-memory) ─────────────────
    history_entries = getattr(session, "history", None) or []
    mem_messages: list[dict[str, str]] = []
    for msg in history_entries:
        role = str(getattr(msg, "role", "") or "")
        content = str(getattr(msg, "content", "") or "")
        if role in ("user", "assistant") and content.strip():
            mem_messages.append({"role": role, "content": content})

    # ── 3. Merge: disk first, then memory (memory is more recent)─
    seen: set[tuple[str, str]] = set()
    all_messages: list[dict[str, str]] = []

    for m in disk_messages + mem_messages:
        # Dedup key: (role, first 80 chars of content)
        key = (m["role"], m.get("content", "")[:80])
        if key in seen:
            continue
        seen.add(key)
        all_messages.append({"role": m["role"], "content": m.get("content", "")})

    # ── 4. Recent window, session summary, previous messages ─────
    recent, older_start = _build_recent_window(all_messages)

    cc.recent_messages = recent
    cc.token_estimate = sum(len(m.get("content", "")) for m in recent) // 2

    if older_start > 0:
        older = all_messages[:older_start]
        cc.session_summary = _build_session_summary(older)

    prev_user = ""
    prev_assistant = ""
    for msg in reversed(all_messages):
        if msg["role"] == "assistant" and not prev_assistant:
            prev_assistant = msg["content"]
        elif msg["role"] == "user" and not prev_user:
            prev_user = msg["content"]
        if prev_user and prev_assistant:
            break
    cc.previous_user_message = prev_user
    cc.previous_assistant_message = prev_assistant


def _build_recent_window(
    all_messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    """Walk backwards through messages, keeping complete turns.

    A "turn" = user message followed by its assistant reply. We keep
    complete turns while the total char count is within budget, but we
    always keep at least ``_RECENT_WINDOW_MIN_MESSAGES``.

    Returns:
        (recent, older_start): recent is in chronological order;
        older_start is the index in all_messages at which the recent
        window begins (i.e. all_messages[:older_start] are the older
        messages).
    """
    if not all_messages:
        return [], 0

    # Segment into turns: pair user→assistant messages.
    turns: list[list[dict[str, str]]] = []
    current_turn: list[dict[str, str]] = []
    for msg in all_messages:
        current_turn.append(msg)
        if msg["role"] == "assistant":
            turns.append(current_turn)
            current_turn = []
    if current_turn:
        # Lone user message at end
        turns.append(current_turn)

    # Walk backwards through turns.
    selected_turns: list[list[dict[str, str]]] = []
    total_chars = 0
    min_reached = False

    for turn in reversed(turns):
        turn_chars = sum(len(m.get("content", "")) for m in turn)
        turn_chars_capped = sum(
            min(len(m.get("content", "")), _MAX_SINGLE_MESSAGE_CHARS)
            for m in turn
        )

        if total_chars + turn_chars_capped > _RECENT_WINDOW_MAX_CHARS:
            if len(selected_turns) * 2 >= _RECENT_WINDOW_MIN_MESSAGES:
                # Budget exceeded and we've met min → stop.
                break
            # Haven't met min yet → include anyway (truncated).
            min_reached = False

        selected_turns.append(turn)
        total_chars += turn_chars_capped
        if len(selected_turns) * 2 >= _RECENT_WINDOW_MIN_MESSAGES:
            min_reached = True

    selected_turns.reverse()

    # Flatten turns back into chronological messages.
    recent: list[dict[str, str]] = []
    for turn in selected_turns:
        for msg in turn:
            content = msg.get("content", "")
            if len(content) > _MAX_SINGLE_MESSAGE_CHARS:
                content = content[:_MAX_SINGLE_MESSAGE_CHARS] + "\n...[truncated]"
            recent.append({"role": msg["role"], "content": content})

    # Find older_start boundary.
    older_start = len(all_messages) - len(recent)
    return recent, max(0, older_start)


def _build_session_summary(older_messages: list[dict[str, str]]) -> str:
    """Build a brief summary from older messages using pattern extraction.

    Since we want to avoid an LLM call for summary generation, we
    extract key phrases: first 80 chars of each message, concatenated
    with turn markers. The LLM (planner/finalizer/direct-answer) can
    use this as supplementary context.
    """
    if not older_messages:
        return ""

    lines: list[str] = []
    max_items = min(len(older_messages), 16)  # Cap at 16 older messages

    for msg in older_messages[-max_items:]:
        content = (msg.get("content") or "").strip()
        if len(content) > 200:
            content = content[:200] + "…"
        role = msg.get("role", "?")
        lines.append(f"  [{role}] {content}")

    summary = "\n".join(lines)
    if len(summary) > _SESSION_SUMMARY_MAX_CHARS:
        summary = summary[:_SESSION_SUMMARY_MAX_CHARS] + "\n…[older messages omitted]"

    return summary


def _resolve_history_references(session, metadata_in: dict[str, Any], cc) -> None:
    """If the current user input contains a history-reference pattern,
    retrieve the referenced context from SessionMessageStore (disk)
    and set cc.retrieved_history.

    This handles queries like "前面提到的 TCP 文件路径是什么" where
    session.history may not reach back far enough.
    """
    user_input = metadata_in.get("__raw_user_input") or ""
    if not user_input:
        return

    text = user_input.strip()
    has_ref = any(pat in text for pat in _HISTORY_REFERENCE_PATTERNS)
    if not has_ref:
        return

    try:
        ws_id = getattr(session, "workspace_id", "") or "default"
        sid = getattr(session, "session_id", "")
        if not sid:
            return

        from workspace.message_store import SessionMessageStore
        store = SessionMessageStore(session_id=sid, ws_id=ws_id)
        all_msgs = store.get_messages()

        if not all_msgs:
            return

        # Extract reference keywords from user input for matching.
        # Simple keyword intersection with message content.
        ref_terms = _extract_reference_terms(text)
        if not ref_terms:
            # No specific terms → retrieve last 4 messages as reference.
            reference = all_msgs[-4:]
            for m in reference:
                content = m.get("content", "")[:1000]
                cc.retrieved_history.append({
                    "role": m.get("role", "unknown"),
                    "content": content,
                })
            return

        # Search back through history for matching terms.
        matched: list[dict[str, str]] = []
        for m in reversed(all_msgs):
            content = m.get("content", "").lower()
            if any(term.lower() in content for term in ref_terms):
                matched.insert(0, {
                    "role": m.get("role", "unknown"),
                    "content": m.get("content", "")[:1000],
                })
            if len(matched) >= 4:
                break

        cc.retrieved_history = matched

    except Exception:
        pass


def _extract_reference_terms(text: str) -> list[str]:
    """Extract likely reference terms from user input.

    These are nouns/phrases that appear near history-reference words.
    """
    # Strip the reference pattern words and split remaining into terms.
    for pat in _HISTORY_REFERENCE_PATTERNS:
        text = text.replace(pat, " ")

    # Extract meaningful CJK/ASCII terms (2+ chars).
    import re
    tokens = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_-]{3,}', text)

    # Filter stop words and short tokens.
    stop_words = {"的", "了", "是", "在", "我", "你", "他", "她", "它",
                  "吗", "吧", "呢", "啊", "哦", "嗯", "什么", "怎么",
                  "这个", "那个", "一个", "可以", "应该", "需要",
                  "the", "a", "an", "is", "are", "was", "were", "be"}
    return [t for t in tokens if t.lower() not in stop_words]


# ── Section 1: Session history sync ────────────────────────────────────

def _sync_session_history(session, user_input: str, final_response: str) -> None:
    """Append current turn to session.history immediately.

    Before this fix, session.history was only restored from disk on
    session init.  Active sessions' in-memory history was never
    updated after a turn, so the next turn's ``_inject_conversation_context``
    saw stale data and follow-up queries ("什么意思", "我上句话说了什么")
    would lose context.

    Dedup: if the last two entries already match, skip (handles
    retry/re-submit scenarios).
    """
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
