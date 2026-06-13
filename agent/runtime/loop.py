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
    safe_context = getattr(context, "safe_context", None) or {}
    if isinstance(safe_context, dict):
        sources = safe_context.get("context_sources") or []
        citations = safe_context.get("citations") or []
        if sources and "context_sources" not in metadata:
            metadata["context_sources"] = list(sources)[:8]
            metadata["source_summary"] = [
                {
                    "source_id": s.get("source_id", ""),
                    "title": s.get("title", ""),
                    "snippet": s.get("snippet", ""),
                    "score": s.get("score", 0),
                    "citation_id": s.get("citation_id", ""),
                    "evidence_type": s.get("evidence_type", "knowledge"),
                }
                for s in list(sources)[:8]
            ]
            metadata["source_count"] = len(sources)
        if citations and "citations" not in metadata:
            metadata["citations"] = list(citations)[:8]
        diagnostics = safe_context.get("retrieval_diagnostics") or {}
        if diagnostics and "retrieval_diagnostics" not in metadata:
            metadata["retrieval_diagnostics"] = diagnostics
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

                # Build a compact, safe ToolResultMessage for the next LLM step.
                tool_msg_payload = _build_tool_message_payload(result)
                # If the tool returned content (e.g. artifact.read), allow up to
                # 8000 chars so translated_config / long text isn't silently
                # truncated before it reaches the LLM.
                trunc_limit = 12000 if "content" in tool_msg_payload else 2000
                tool_msg = ToolResultMessage(
                    content=json.dumps(tool_msg_payload, ensure_ascii=False)[:trunc_limit],
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

    safe_context_text = _safe_context_prompt_text(getattr(context, "safe_context", None))
    if safe_context_text:
        messages.append(RuntimeContextMessage(content=safe_context_text).to_llm_message())

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


def _safe_context_prompt_text(safe_context: dict | None) -> str:
    """Project safe_context into a compact prompt block.

    The provider only receives messages, so RuntimeLoop must explicitly include
    the safe, summarized context it wants the model to use. Keep this projection
    narrow: no raw source/deployable config and no arbitrary workspace payloads.
    """
    if not isinstance(safe_context, dict) or not safe_context:
        return ""

    projected = {}
    scalar_keys = (
        "workspace_id",
        "session_id",
        "intent",
        "capability_id",
        "source_config_artifact_id",
        "last_result_summary",
        "job_summary",
    )
    for key in scalar_keys:
        if key in safe_context and safe_context[key] not in (None, "", [], {}):
            projected[key] = _safe_prompt_value(safe_context[key])

    for key in ("artifact_refs", "memory_hits", "knowledge_hits", "context_sources", "context_warnings", "citations"):
        value = safe_context.get(key)
        if value:
            projected[key] = _safe_prompt_value(value, max_items=5)

    workspace_state = safe_context.get("workspace_state")
    if isinstance(workspace_state, dict):
        state = {}
        for key, value in workspace_state.items():
            if _is_prompt_safe_workspace_state_key(key) and value not in (None, "", [], {}):
                state[key] = _safe_prompt_value(value, max_items=3)
            if len(state) >= 8:
                break
        if state:
            projected["workspace_state"] = state

    if not projected:
        return ""
    text = json.dumps(projected, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) > 5000:
        text = text[:5000] + "...[truncated]"
    return "[Safe Context]\nUse this summarized context when answering. If it is insufficient, say what is missing.\n" + text


def _safe_prompt_value(value, max_items: int = 8, max_text: int = 600):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _is_forbidden_prompt_key(str(key)):
                continue
            result[str(key)] = _safe_prompt_value(item, max_items=3, max_text=240)
            if len(result) >= max_items:
                break
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_prompt_value(item, max_items=8, max_text=240) for item in list(value)[:max_items]]
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
        return text[:max_text] + ("...[truncated]" if len(text) > max_text else "")
    return str(value)[:max_text]


def _is_prompt_safe_workspace_state_key(key: str) -> bool:
    return not _is_forbidden_prompt_key(key)


def _is_forbidden_prompt_key(key: str) -> bool:
    lower = key.lower()
    forbidden = (
        "source_config",
        "raw_config",
        "secret",
        "password",
        "token",
        "api_key",
        "authorization",
        "credentials",
        "ssh_key",
        "private_key",
    )
    return any(part in lower for part in forbidden)


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


def _build_tool_message_payload(result) -> dict:
    """Project a ToolResult into the safe payload the LLM sees next.

    Tool handlers may return rich raw data. The model needs citation-ready
    fields such as web results and source summaries, but not arbitrary raw
    config or workspace content. Keep a small allowlist and trim aggressively.
    """
    payload = {
        "ok": bool(_safe_get(result, "ok", False)),
        "summary": _safe_prompt_text(_safe_get(result, "summary", ""), 500),
    }
    for key in ("source_count", "manual_review_count"):
        value = _safe_get(result, key, None)
        if value is not None:
            payload[key] = value

    errors = _safe_get(result, "errors", []) or []
    warnings = _safe_get(result, "warnings", []) or []
    if errors:
        payload["errors"] = [_safe_prompt_text(e, 240) for e in list(errors)[:3]]
    if warnings:
        payload["warnings"] = [_safe_prompt_text(w, 240) for w in list(warnings)[:3]]

    artifacts = _safe_get(result, "artifacts", []) or []
    if artifacts:
        payload["artifact_count"] = len(artifacts)
        payload["artifacts"] = [
            {
                "artifact_id": a.get("artifact_id", ""),
                "artifact_type": a.get("artifact_type", ""),
                "title": _safe_prompt_text(a.get("title", ""), 160),
            }
            for a in list(artifacts)[:3]
            if isinstance(a, dict)
        ]

    for source_key in ("source_summary",):
        value = _safe_get(result, source_key, None)
        if value:
            payload[source_key] = _safe_tool_value(value)

    raw = _safe_get(result, "raw", {}) or {}
    data = _safe_get(result, "data", {}) or {}
    if isinstance(raw, dict):
        _merge_llm_safe_tool_fields(payload, raw)
    if isinstance(data, dict):
        _merge_llm_safe_tool_fields(payload, data)
    return payload


def _merge_llm_safe_tool_fields(payload: dict, source: dict) -> None:
    """Merge fields from source (data/raw) into payload, skipping forbidden keys.

    v0.9.1: Replaced hardcoded whitelist with blacklist-based merging.
    All non-forbidden fields are passed through — _safe_tool_value handles
    recursive sanitization (length caps, dict/list limits, key filtering).

    Colliding keys: if source has a key that already exists in payload
    (e.g. summary, errors, warnings), the source value is stored under
    a renamed key (prefix: "result_") so domain-specific data isn't lost.
    """
    for key, value in source.items():
        if _is_forbidden_prompt_key(str(key)):
            continue
        if value in (None, "", [], {}):
            continue
        target_key = key
        # Top-level ToolResult contract fields are already in payload.
        # Rename source's version so domain-specific data isn't lost
        # (e.g. web.fetch_summary returns {"summary": "page text"},
        #  but ToolResult also has summary; the handler's version
        #  becomes result_summary and gets the full 4000-char budget).
        if key in payload and key not in ("ok",):
            target_key = f"result_{key}"
        payload[target_key] = _safe_tool_value(value)


def _safe_tool_value(value, *, max_text: int = 4000):
    if isinstance(value, dict):
        return {
            str(k): _safe_tool_value(v, max_text=1200)
            for k, v in list(value.items())[:8]
            if not _is_forbidden_prompt_key(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_tool_value(v, max_text=1200) for v in list(value)[:5]]
    return _safe_prompt_text(value, max_text)


def _safe_prompt_text(value, max_text: int) -> str:
    text = str(value)
    return text[:max_text] + ("...[truncated]" if len(text) > max_text else "")


def _build_partial_answer(tool_results: list) -> str:
    """Build partial answer when max steps exceeded."""
    if not tool_results:
        return "I've completed the analysis but need more information to provide a complete answer."
    parts = ["Here's what I've found so far:"]
    for tr in tool_results[-5:]:
        parts.append(f"- {tr.get('tool_id', 'unknown')}: {tr.get('summary', 'no result')}")
    return "\n".join(parts)
