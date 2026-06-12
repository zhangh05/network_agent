# agent/runtime/loop.py
"""RuntimeLoop — the core turn execution engine (Codex-style agentic loop)."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from agent.protocol.message import UserMessage, SystemMessage, AssistantMessage, ToolResultMessage, RuntimeContextMessage
from agent.protocol.tool_result import ToolResult
from agent.runtime.result import AgentResult
from agent.llm.runtime import invoke_llm

MAX_STEPS = 8


# ─── Run persistence adapter ─────────────────────────────────────────
# v0.6+ 新的 runtime (Codex-style) 用了 dataclass-based Turn / Session /
# TurnContext, 跟 legacy NetworkAgentState 字段不一样. 老 runtime 的
# legacy/memory_writer.py 会调 write_run_record() 落 run record 并把
# run_id 追加到 session.run_ids. 新 runtime 缺这一环, 所以
# /api/sessions/<id>/messages 永远返回 [].
#
# 这个 adapter 把 Turn/Session/Result 投影成 write_run_record 期望的
# state-like 对象, 然后调用既有的落盘逻辑 (自动触发 add_run_to_session).
# 在 4 个 return 出口 (success / provider_error / timeout / max_steps)
# 统一调一次, 确保任何路径都会写盘.
#
# v1.0.3.1: 同时写入独立完整消息到 SessionMessageStore，不再依赖
# run record 的 120/300 字符摘要。
def _persist_run_record(session, turn, result, context) -> None:
    """Best-effort: persist this turn to workspace/run_store so that
    it shows up in /api/sessions/<id>/messages for plan-C sync.

    v1.0.3.1: also writes full user/assistant messages to the
    SessionMessageStore, so chat history does NOT rely on the
    120/300-character summaries in run records.

    Never raises — persistence failure must not break the turn.
    """
    try:
        from workspace.run_store import write_run_record
        from workspace.message_store import SessionMessageStore
        user_input = (turn.op.user_input if turn.op else "") or ""
        final_response = (result.final_response if result else "") or ""
        ws_id = session.workspace_id or "default"
        run_id = turn.turn_id
        created_at = _created_at_for_turn(turn, context)
        # Project to legacy-style state object. write_run_record reads
        # these exact attributes (see workspace/run_store.py:14-103).
        skill_results = {}
        if result and getattr(result, "tool_calls", None):
            for tc in result.tool_calls or []:
                md = tc.get("metadata", {}) if isinstance(tc, dict) else {}
                for k in ("deployable_config", "manual_review", "unsupported", "semantic_near", "audit"):
                    if k in md:
                        skill_results[k] = md[k]
        selected_skill = _selected_skill_for_record(context)
        active_module = _active_module_for_record(context, selected_skill)
        state = SimpleNamespace(
            request_id=turn.turn_id,
            session_id=session.session_id,
            created_at=created_at,
            user_input=user_input,
            intent=(context.metadata.get("intent", "") if context and context.metadata else ""),
            context={
                "llm": (context.metadata.get("llm", {}) if context and context.metadata else {}),
                "capability_id": (context.metadata.get("capability_id", "") if context and context.metadata else ""),
                "memory_written": False,
                "workspace_updated": False,
            },
            active_module=active_module,
            selected_skill=selected_skill,
            runtime_mode="codex_v1",
            final_response=final_response,
            warnings=(result.warnings if result and result.warnings else []),
            trace_id=(result.trace_id if result else ""),
            error=((result.errors[0] if result and result.errors else None)),
            skill_results=skill_results,
            tool_results=skill_results,  # write_run_record 两者都接受
        )
        write_run_record(state, ws_id)
        # v1.0.3.1: also persist full messages independently
        if session.session_id:
            store = SessionMessageStore(session_id=session.session_id, ws_id=ws_id)
            if user_input:
                store.write_message(run_id, "user", user_input, metadata={
                    "created_at": state.created_at,
                    "intent": state.intent,
                })
            if final_response:
                store.write_message(run_id, "assistant", final_response, metadata={
                    "created_at": state.created_at,
                    "intent": state.intent,
                    "trace_id": result.trace_id if result else "",
                })
        # v1.0.3.2: persist trace events to disk so Runtime Audit works
        if result and result.events:
            try:
                _persist_trace(run_id, ws_id, result.events)
            except Exception:
                pass
    except Exception:
        # Persistence is best-effort; never let it break the turn.
        pass


def _selected_skill_for_record(context) -> str:
    """Pick the user-meaningful skill for run records.

    Runtime context can select multiple skills. The run list should show the
    business skill when present, not the generic assistant wrapper.
    """
    if not context:
        return ""
    if getattr(context, "skill_snapshot", None):
        value = context.skill_snapshot.get("skill_id", "")
        if value:
            return str(value)
    metadata = getattr(context, "metadata", None) or {}
    selected = metadata.get("selected_skills") or []
    if isinstance(selected, str):
        selected = [selected]
    for skill in selected:
        if skill and skill != "assistant_chat":
            return str(skill)
    return str(selected[0]) if selected else ""


def _active_module_for_record(context, selected_skill: str) -> str:
    if context and getattr(context, "module_snapshot", None):
        value = context.module_snapshot.get("module_id", "")
        if value:
            return str(value)
    if selected_skill and selected_skill != "assistant_chat":
        return selected_skill
    metadata = getattr(context, "metadata", None) or {}
    visible_tools = metadata.get("visible_tools") or []
    if isinstance(visible_tools, str):
        visible_tools = [visible_tools]
    first_tool = str(visible_tools[0]) if visible_tools else ""
    return first_tool.split(".", 1)[0] if "." in first_tool else ""


def _created_at_for_turn(turn, context) -> str:
    """Return a non-empty timestamp for run/session projections."""
    if context and getattr(context, "metadata", None):
        value = context.metadata.get("created_at")
        if value:
            return str(value)
    if turn and getattr(turn, "context", None):
        value = turn.context.get("created_at")
        if value:
            return str(value)
    if turn and getattr(turn, "op", None):
        value = getattr(turn.op, "created_at", None)
        if value:
            return str(value)
    return datetime.now(timezone.utc).isoformat()


def _persist_trace(run_id: str, ws_id: str, events: list) -> None:
    """Write trace events to workspaces/<ws>/runs/<run_id>.trace.json."""
    import json, time
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    runs_dir = WS_ROOT / ws_id / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = runs_dir / f"{run_id}.trace.json"
    record = {
        "run_id": run_id,
        "workspace_id": ws_id,
        "events": events,
        "event_count": len(events),
        "persisted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # Atomic write: tmp → rename
    tmp = trace_path.with_suffix(".trace.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(trace_path)


# v0.8.2 — Standard tool_call projection

def _enrich_metadata(metadata: dict, context) -> dict:
    """v1.0.3: inject selected_skills / visible_tools from TurnContext
    into every AgentResult.metadata (including error/timeout paths).
    """
    if context and getattr(context, "metadata", None):
        for k in ("selected_skills", "visible_tools"):
            if k in context.metadata and k not in metadata:
                metadata[k] = context.metadata[k]
    return metadata

def _to_standard_tool_call(call_id: str, tool_id: str, result) -> dict:
    """Build a v0.8.2 standard tool_call dict from any handler result.

    The result can be a ToolResult instance, a dict (legacy v0.7.x shape),
    or any object exposing attributes. The output has all 10 standard
    fields present, with safe defaults. This guarantees the public
    AgentResult.tool_calls contract holds even for older handlers.
    """
    if isinstance(result, ToolResult):
        tr = result
        if not tr.call_id:
            tr.call_id = call_id
        if not tr.tool_id:
            tr.tool_id = tool_id
        return {
            "call_id": tr.call_id,
            "tool_id": tr.tool_id,
            "ok": tr.ok,
            "summary": tr.summary,
            "artifacts": list(tr.artifacts or []),
            "source_count": tr.source_count,
            "manual_review_count": tr.manual_review_count,
            "errors": list(tr.errors or []),
            "warnings": list(tr.warnings or []),
            "metadata": dict(tr.metadata or {}),
        }
    # Dict-like result (v0.7.x or v0.8.2 dict-shaped)
    if isinstance(result, dict):
        tr = ToolResult.from_legacy_dict(tool_id=tool_id, call_id=call_id, d=result)
    else:
        # Object with attributes (e.g. a ToolSpec-ish result)
        tr = ToolResult(
            call_id=call_id,
            tool_id=tool_id,
            ok=bool(getattr(result, 'ok', False)),
            summary=str(getattr(result, 'summary', str(result))[:500]),
            artifacts=list(getattr(result, 'artifacts', []) or []),
            source_count=getattr(result, 'source_count', None),
            manual_review_count=getattr(result, 'manual_review_count', None),
            errors=list(getattr(result, 'errors', []) or []),
            warnings=list(getattr(result, 'warnings', []) or []),
            metadata=dict(getattr(result, 'metadata', {}) or {}),
            data=dict(getattr(result, 'data', {}) or {}),
        )
    return {
        "call_id": tr.call_id,
        "tool_id": tr.tool_id,
        "ok": tr.ok,
        "summary": tr.summary,
        "artifacts": list(tr.artifacts or []),
        "source_count": tr.source_count,
        "manual_review_count": tr.manual_review_count,
        "errors": list(tr.errors or []),
        "warnings": list(tr.warnings or []),
        "metadata": dict(tr.metadata or {}),
    }


def run_turn(session, turn, services=None) -> AgentResult:
    """Execute a single turn: user message → LLM → tools → LLM → ... → final answer."""
    from agent.runtime.context_builder import build_turn_context

    audit_events = services.audit_service["events"] if services and hasattr(services, 'audit_service') and services.audit_service else None
    audit_trace = services.audit_service["trace"] if services and hasattr(services, 'audit_service') and services.audit_service else None

    # 1. audit: turn_started
    if audit_events:
        audit_events.emit("turn_started", session_id=session.session_id, turn_id=turn.turn_id,
                          user_input=turn.op.user_input if turn.op else "")

    turn.status = "running"

    # 2. build context
    context = build_turn_context(session, turn, services)

    # v1.0.3.1: hydrate history_window from the SessionMessageStore (canonical
    # disk source) instead of AgentSession.history (in-memory cache that
    # can drift). If the store has more recent runs than the in-memory
    # list, prefer the store. Falls back to the in-memory list if the
    # store is unavailable.
    try:
        from workspace.message_store import SessionMessageStore
        store = SessionMessageStore(session_id=session.session_id, ws_id=session.workspace_id or "default")
        if store.exists():
            window = store.get_history_window(k=8)
            if window:
                msgs = []
                for m in window:
                    if m.get("role") == "user":
                        msgs.append(UserMessage(content=m.get("content", "")))
                    elif m.get("role") == "assistant":
                        msgs.append(AssistantMessage(content=m.get("content", "")))
                context.history_window = msgs
    except Exception:
        # Store unavailable → fall back to the in-memory list (v0.6+ path).
        pass
    if audit_events:
        audit_events.emit("context_built", session_id=session.session_id, turn_id=turn.turn_id)

    # 3. build messages
    messages = _build_initial_messages(context, services)

    # 4. get tools
    tools = []
    if context.tool_router:
        try:
            tools = context.tool_router.model_visible_tools()
        except Exception:
            pass

    # 5. agentic loop
    step = 0
    all_tool_results = []
    final_response = ""

    while step < MAX_STEPS:
        step += 1

        # audit: model_request_started
        if audit_events:
            audit_events.emit("model_request_started", session_id=session.session_id, turn_id=turn.turn_id, step=step)
        if audit_trace:
            audit_trace.record_model_request(turn.turn_id, step, f"{len(messages)} messages", len(tools))

        # Call LLM via invoke_llm
        try:
            resp = invoke_llm(
                task="assistant_chat",
                messages=messages,
                tools=tools,
                safe_context=context.safe_context,
                user_input=context.user_input,
            )
        except Exception as e:
            error_str = str(e)[:200]
            is_timeout = "timeout" in error_str.lower() or "timed out" in error_str.lower()
            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  error=error_str)
            turn.status = "failed"
            turn.errors.append(error_str)
            user_msg = "LLM 服务请求超时，请稍后重试。" if is_timeout else f"LLM 调用异常：{error_str}"
            # Record failure for LLM health UX
            try:
                from agent.llm.config import record_recent_failure
                record_recent_failure(user_msg, "provider_timeout" if is_timeout else "provider_error")
            except Exception:
                pass
            _err_result = AgentResult(
                ok=False,
                final_response=user_msg,
                session_id=session.session_id, turn_id=turn.turn_id, trace_id=context.trace_id,
                errors=[error_str],
                events=_collect_events(audit_events, turn.turn_id),
                metadata=_enrich_metadata({"provider_error_type": "provider_timeout" if is_timeout else "provider_error",
                          "retryable": is_timeout}, context),
            )
            _persist_run_record(session, turn, _err_result, context)
            return _err_result

        if audit_events:
            audit_events.emit("model_response_received", session_id=session.session_id, turn_id=turn.turn_id, step=step)
        if audit_trace:
            audit_trace.record_model_response(turn.turn_id, step,
                                              has_content=bool(resp.content),
                                              has_tool_calls=resp.has_tool_calls(),
                                              finish_reason=getattr(resp, 'finish_reason', ''))

        # Handle provider error
        if resp.error:
            provider_meta = resp.metadata or {}
            error_type = provider_meta.get("error_type", "provider_error")
            is_timeout = error_type == "provider_timeout"
            retryable = provider_meta.get("retryable", is_timeout)

            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  error=f"Provider error ({error_type}): {resp.error}")

            turn.status = "failed"
            turn.errors.append(resp.error)

            # User-friendly message
            if is_timeout:
                user_msg = "LLM 服务请求超时，请稍后重试。系统已保留本轮事件记录。"
            else:
                user_msg = f"LLM 服务暂不可用：{resp.error[:200]}"

            # Record failure for LLM health UX
            try:
                from agent.llm.config import record_recent_failure
                record_recent_failure(user_msg, "provider_timeout" if is_timeout else "provider_error")
            except Exception:
                pass

            _err_result = AgentResult(
                ok=False,
                final_response=user_msg,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                trace_id=context.trace_id,
                errors=[resp.error],
                warnings=["provider_timeout"] if is_timeout else [],
                events=_collect_events(audit_events, turn.turn_id),
                metadata=_enrich_metadata({
                    "provider_error_type": error_type,
                    "retryable": retryable,
                    "provider_error_detail": provider_meta.get("error_detail", ""),
                }, context),
            )
            _persist_run_record(session, turn, _err_result, context)
            return _err_result

        # Handle tool calls
        if resp.has_tool_calls():
            assistant_msg = AssistantMessage(
                content=resp.content if resp.content else "",
                tool_calls=[{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                } for tc in resp.tool_calls],
            )
            messages.append(assistant_msg.to_llm_message())

            for tc in resp.tool_calls:
                llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")

                # Try to build ToolCall (may raise UnknownToolCallError)
                try:
                    tool_call = context.tool_router.build_tool_call(tc)
                except Exception as e:
                    # Unknown tool — record and feed back to LLM
                    error_name = getattr(e, '__class__', type(e)).__name__
                    if audit_events:
                        audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                          tool_id=llm_name, errors=[str(e)[:200]])
                    if audit_trace:
                        audit_trace.record_tool_result(turn.turn_id, step, llm_name, False, str(e)[:100])
                    all_tool_results.append({
                        "tool_id": llm_name,
                        "ok": False,
                        "summary": f"Tool not visible to model: {llm_name}",
                    })
                    tool_msg = ToolResultMessage(
                        content=json.dumps({
                            "ok": False,
                            "error": f"{error_name}: {str(e)[:200]}",
                            "hint": "Only call tools from the provided function list."
                        }, ensure_ascii=False)[:1000],
                        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
                    )
                    messages.append(tool_msg.to_llm_message())
                    continue

                if audit_events:
                    audit_events.emit("tool_call_started", session_id=session.session_id, turn_id=turn.turn_id,
                                      tool_id=tool_call.real_tool_id)
                if audit_trace:
                    audit_trace.record_tool_call(turn.turn_id, step, tool_call.real_tool_id, str(tool_call.arguments)[:100])

                try:
                    result = context.tool_router.dispatch(tool_call, context)
                    if audit_events:
                        if result.ok:
                            audit_events.emit("tool_call_finished", session_id=session.session_id, turn_id=turn.turn_id,
                                              tool_id=tool_call.real_tool_id, summary=result.summary)
                        else:
                            audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                              tool_id=tool_call.real_tool_id, errors=result.errors)
                    if audit_trace:
                        audit_trace.record_tool_result(turn.turn_id, step, tool_call.real_tool_id, result.ok, result.summary)
                except Exception as e:
                    if audit_events:
                        audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                          tool_id=tool_call.real_tool_id, errors=[str(e)[:200]])
                    if audit_trace:
                        audit_trace.record_tool_result(turn.turn_id, step, tool_call.real_tool_id, False, str(e)[:100])
                    result = ToolResult(
                        ok=False,
                        summary=str(e)[:200],
                        errors=[str(e)[:200]],
                    )

                all_tool_results.append(_to_standard_tool_call(
                    tool_call.call_id, tool_call.real_tool_id, result
                ))

                # Build richer ToolResultMessage for LLM
                tool_msg_payload = {"ok": result.ok, "summary": getattr(result, 'summary', '')}
                if hasattr(result, 'source_count'):
                    tool_msg_payload["source_count"] = result.source_count
                if hasattr(result, 'manual_review_count'):
                    tool_msg_payload["manual_review_count"] = result.manual_review_count
                if hasattr(result, 'artifacts') and result.artifacts:
                    tool_msg_payload["artifact_count"] = len(result.artifacts)
                    tool_msg_payload["artifacts"] = [{"artifact_id": a.get("artifact_id", ""),
                                                       "artifact_type": a.get("artifact_type", ""),
                                                       "title": a.get("title", "")} for a in result.artifacts[:3]]
                if hasattr(result, 'source_summary'):
                    tool_msg_payload["source_summary"] = result.source_summary
                tool_msg = ToolResultMessage(
                    content=json.dumps(tool_msg_payload, ensure_ascii=False)[:2000],
                    tool_call_id=tc.id,
                )
                messages.append(tool_msg.to_llm_message())

            continue

        # LLM returned content (final answer)
        from agent.llm.runtime import sanitize_provider_output
        final_response, reasoning_stripped = sanitize_provider_output(resp.content)
        if audit_events:
            audit_events.emit("assistant_message", session_id=session.session_id, turn_id=turn.turn_id,
                              content_len=len(final_response), reasoning_stripped=reasoning_stripped)

        # v1.0.3.5: output policy check — block/rewrite dangerous content
        output_policy_ok = True
        try:
            from prompts.policy import check_prompt_output
            out_result = check_prompt_output(final_response)
            if not out_result.is_ok:
                output_policy_ok = False
                final_response += (
                    "\n\n⚠️ [输出策略告警] 当前回答可能包含不应展示的内容，已标注。"
                )
                turn.warnings.append(f"output_policy_failed: {out_result.issues}")
        except Exception:
            pass

        session.history.append(UserMessage(content=context.user_input))
        session.history.append(AssistantMessage(content=final_response))

        if audit_events:
            audit_events.emit("turn_finished", session_id=session.session_id, turn_id=turn.turn_id)
        turn.status = "finished"
        turn.final_response = final_response

        result = AgentResult(
            ok=True,
            final_response=final_response,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            trace_id=context.trace_id,
            tool_calls=all_tool_results,
            warnings=turn.warnings,
            events=_collect_events(audit_events, turn.turn_id),
            metadata=_enrich_metadata({
                "model": context.model_config.get("model", ""),
                "steps": step,
                "output_policy_ok": output_policy_ok,
            }, context),
        )

        # Persist rollout
        try:
            if services and hasattr(services, 'audit_service') and services.audit_service:
                rollout = services.audit_service.get("rollout")
                if rollout:
                    rollout.persist_turn(turn, result)
        except Exception:
            pass

        # Persist run record so /api/sessions/<id>/messages 拿得到
        _persist_run_record(session, turn, result, context)
        # Record successful turn for Settings health display
        try:
            from agent.llm.config import record_recent_success
            record_recent_success()
        except Exception:
            pass
        return result

    # Max steps exceeded
    turn.status = "finished"
    turn.warnings.append(f"max_steps ({MAX_STEPS}) reached — partial result")
    if audit_events:
        audit_events.emit("turn_finished", session_id=session.session_id, turn_id=turn.turn_id,
                          warning="max_steps exceeded")
    _partial = AgentResult(
        ok=True,
        final_response=f"[partial] {_build_partial_answer(all_tool_results)}",
        session_id=session.session_id,
        turn_id=turn.turn_id,
        trace_id=context.trace_id,
        warnings=[f"max_steps ({MAX_STEPS}) reached — partial result"],
        events=_collect_events(audit_events, turn.turn_id),
        metadata=_enrich_metadata({
            "terminal_reason": "max_steps_exceeded",
            "partial": True,
            "steps": MAX_STEPS,
        }, context),
    )
    _persist_run_record(session, turn, _partial, context)
    return _partial


def _build_initial_messages(context, services) -> list:
    """Build initial message list with system prompt, snapshot, skill injections, history, user input."""
    messages = []

    # System prompt
    from agent.runtime.prompts import build_system_prompt
    messages.append(SystemMessage(
        content=build_system_prompt()
    ).to_llm_message())

    # Runtime snapshot
    from agent.context.snapshot import RuntimeSnapshot
    snapshot_fields = set(RuntimeSnapshot.__dataclass_fields__.keys())
    snap = RuntimeSnapshot(**{
        k: v for k, v in (context.runtime_snapshot or {}).items()
        if k in snapshot_fields
    })
    snap.workspace_id = context.workspace_id
    snap.session_id = context.session_id
    snap.model = context.model_config.get("model", "")
    messages.append(RuntimeContextMessage(content=snap.to_prompt_text()).to_llm_message())

    # Skill injections
    if services and services.skill_service:
        try:
            from agent.skills.injection import build_skill_injections
            inj = build_skill_injections(context)
            if inj:
                messages.append(RuntimeContextMessage(content=inj).to_llm_message())
        except Exception:
            pass

    # History window
    for h in context.history_window:
        if hasattr(h, 'to_llm_message'):
            messages.append(h.to_llm_message())

    # Current user input
    messages.append(UserMessage(content=context.user_input).to_llm_message())

    return messages


def _collect_events(audit_events, turn_id: str) -> list:
    """Collect events for a turn from the event recorder."""
    if audit_events and hasattr(audit_events, 'events_for_turn_dicts'):
        return audit_events.events_for_turn_dicts(turn_id)
    return []


def _safe_get(obj, attr: str, default=None):
    """Safely get attribute or key from result object/dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    if hasattr(obj, attr):
        return getattr(obj, attr)
    return default


def _build_partial_answer(tool_results: list) -> str:
    """Build partial answer when max steps exceeded."""
    if not tool_results:
        return "I've completed the analysis but need more information to provide a complete answer."
    parts = ["Here's what I've found so far:"]
    for tr in tool_results[-5:]:
        parts.append(f"- {tr.get('tool_id', 'unknown')}: {tr.get('summary', 'no result')}")
    return "\n".join(parts)
