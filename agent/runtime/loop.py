# agent/runtime/loop.py
"""RuntimeLoop — the core turn execution engine (Codex-style agentic loop).

The main function run_turn() orchestrates the agentic loop. Supporting
functions have been extracted to dedicated modules:
- turn_persistence.py — run records, messages, trace events
- message_builder.py — initial message construction
- tool_result_utils.py — tool call standardization, payload formatting
- hook_runner.py — lifecycle hook execution
- token_manager.py — token tracking, limits, compaction
- tool_decision.py — decision transparency blocks
- permission_check.py — permission matrix, approval routing
"""

import json
from datetime import datetime, timezone

from agent.protocol.message import (
    UserMessage, AssistantMessage, ToolResultMessage, RuntimeContextMessage,
)
from agent.protocol.tool_result import ToolResult
from agent.runtime.result import AgentResult
from agent.llm.runtime import invoke_llm
from agent.runtime.token_tracker import estimate_messages

# ─── Imports from extracted modules ───────────────────────────────────
from agent.runtime.turn_persistence import persist_run_record
from agent.runtime.message_builder import build_initial_messages
from agent.runtime.tool_result_utils import (
    to_standard_tool_call, enrich_metadata, build_tool_message_payload,
)
from agent.runtime.hook_runner import (
    run_pre_turn_hooks, run_pre_tool_hook, run_post_tool_hook,
    run_post_turn_hooks, run_stop_hooks,
    run_pre_model_hook, run_post_model_hook, run_error_hook, run_approval_hook,
    run_user_prompt_submit_hook,
)
from agent.runtime.token_manager import check_token_limit, track_llm_usage, TokenLimitExceeded
from agent.runtime.tool_decision import (
    build_tool_decision as _build_tool_decision,
    build_no_tool_reason as _build_no_tool_reason,
    build_partial_answer as _build_partial_answer,
    collect_events as _collect_events,
)
from agent.runtime.permission_check import (
    check_tool_permission, check_shell_safety, needs_approval,
    build_permission_denied_result, build_shell_denied_result,
)

MAX_STEPS = 8


def run_turn(session, turn, services=None, restricted_tool_router=None) -> AgentResult:
    """Execute a single turn: user message → LLM → tools → LLM → ... → final answer.

    Phase 3: restricted_tool_router is used by sub-agents to limit tool access.
    """
    from agent.runtime.context_builder import build_turn_context

    audit_events = services.audit_service["events"] if services and hasattr(services, 'audit_service') and services.audit_service else None
    audit_trace = services.audit_service["trace"] if services and hasattr(services, 'audit_service') and services.audit_service else None

    from agent.runtime.query_engine import build_trace_id, StreamEmitter, StreamEvent, classify_error, ErrorType
    emitter = StreamEmitter()
    _fallback_trace_id = build_trace_id()

    # 1. audit: turn_started
    if audit_events:
        audit_events.emit("turn_started", session_id=session.session_id, turn_id=turn.turn_id,
                          user_input=turn.op.user_input if turn.op else "")
    emitter.emit(StreamEvent.RUN_STARTED, {
        "session_id": session.session_id,
        "turn_id": turn.turn_id,
        "trace_id": _fallback_trace_id,
    })

    turn.status = "running"

    # 2. build context
    context = build_turn_context(session, turn, services)

    if not getattr(context, 'trace_id', None):
        context.trace_id = _fallback_trace_id
    context._stream_emitter = emitter

    if restricted_tool_router is not None:
        context.tool_router = restricted_tool_router

    # v1.0.3.1: hydrate history_window from SessionMessageStore (disk) —
    #    merge with in-memory session.history to avoid losing recent messages.
    try:
        from workspace.message_store import SessionMessageStore
        store = SessionMessageStore(session_id=session.session_id, ws_id=session.workspace_id or "default")
        memory_msgs = list(session.history[-8:]) if hasattr(session, 'history') and session.history else []
        memory_ids = {getattr(m, 'id', getattr(m, 'message_id', None)) for m in memory_msgs if hasattr(m, 'id') or hasattr(m, 'message_id')}
        if store.exists():
            window = store.get_history_window(k=8)
            if window:
                msgs = []
                seen = set()
                for m in window:
                    mid = m.get("message_id") or m.get("id") or m.get("content", "")[:40]
                    if mid and mid in seen:
                        continue
                    seen.add(mid)
                    role = m.get("role", "")
                    content = m.get("content", "")
                    if role == "user":
                        msgs.append(UserMessage(content=content))
                    elif role == "assistant":
                        msgs.append(AssistantMessage(content=content))
                    elif role == "tool":
                        msgs.append(ToolResultMessage(
                            content=json.dumps({"ok": m.get("ok", False), "summary": content[:500]}, ensure_ascii=False),
                            tool_call_id=m.get("tool_call_id", m.get("id", "")),
                        ))
                # Append in-memory msgs not already covered by disk
                for mm in memory_msgs:
                    mid = getattr(mm, 'id', getattr(mm, 'message_id', None))
                    if mid and mid in memory_ids and mid not in seen:
                        msgs.append(mm)
                # Trim to k
                context.history_window = msgs[-8:]
        elif memory_msgs:
            context.history_window = memory_msgs
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to hydrate history_window from SessionMessageStore for %s: %s",
            session.session_id, e,
        )

    if audit_events:
        audit_events.emit("context_built", session_id=session.session_id, turn_id=turn.turn_id)

    # ── v3.0.0: UserPromptSubmit hook (sanitize user input before processing) ──
    run_user_prompt_submit_hook(session, context)

    # ── v2.0: Pre-turn hooks ──
    if run_pre_turn_hooks(session, turn, context):
        turn.status = "blocked"
        result = AgentResult(
            ok=False,
            final_response="Turn blocked by pre-turn hook. Ask the user to review hook configuration.",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            trace_id=context.trace_id,
            warnings=turn.warnings,
            tool_decision={"needed": False, "reason": "Turn blocked by pre-turn hook."},
            no_tool_reason="blocked_by_hook: Turn 被 pre-turn hook 阻止",
            metadata=enrich_metadata({
                "hook_event": "pre_turn",
                "hook_blocked": True,
            }, context),
        )
        persist_run_record(session, turn, result, context)
        return result

    # 3. build messages
    messages = build_initial_messages(context, services)

    # ── v2.1: Manual compact from previous /compact command ──
    _apply_manual_compact(session, turn, messages)

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
    _tool_stop_requested = False

    while step < MAX_STEPS:
        step += 1

        # audit: model_request_started
        if audit_events:
            audit_events.emit("model_request_started", session_id=session.session_id, turn_id=turn.turn_id, step=step)
        if audit_trace:
            audit_trace.record_model_request(turn.turn_id, step, f"{len(messages)} messages", len(tools))

        # Call LLM via invoke_llm
        try:
            check_token_limit(messages, context, session, turn, step)

            if run_pre_model_hook(session, messages, tools, context, step):
                emitter.emit(StreamEvent.ERROR, {"error_type": "pre_model_blocked", "message": "PRE_MODEL hook denied LLM call"})
                turn.status = "failed"
                turn.warnings.append("pre_model_blocked: LLM call blocked by hook")
                _blocked = AgentResult(
                    ok=False,
                    final_response="请求被系统策略拒绝，请联系管理员检查 hook 配置。",
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    trace_id=context.trace_id,
                    error_type="permission_denied",
                    events=emitter.to_events(),
                    tool_decision={"needed": False, "reason": "LLM call blocked by pre-model hook."},
                    no_tool_reason="blocked_by_hook: LLM 调用被 pre-model hook 阻止",
                    metadata=enrich_metadata({"hook_event": "pre_model_blocked"}, context),
                )
                persist_run_record(session, turn, _blocked, context)
                return _blocked

            emitter.emit(StreamEvent.MODEL_STARTED, {"step": step, "message_count": len(messages), "tool_count": len(tools)})

            resp = invoke_llm(
                task="assistant_chat",
                messages=messages,
                tools=tools,
                safe_context=context.safe_context,
                user_input=context.user_input,
            )

            modified = run_post_model_hook(session, resp, context, step)
            if modified:
                resp.content = modified

        except TokenLimitExceeded as e:
            run_error_hook(session, "token_limit", {"error": str(e), "estimated": e.estimated, "max_context": e.max_context}, context)
            emitter.emit(StreamEvent.ERROR, {"error_type": ErrorType.TOKEN_LIMIT, "message": f"Token limit exceeded: {str(e)}"})
            turn.status = "failed"
            turn.warnings.append(f"token_limit_exceeded: {e}")
            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  reason="token_limit_exceeded")
            return _error_result(session, turn, context, emitter, audit_events,
                "上下文超过模型限制，请压缩上下文或开启 compact 后重试。",
                classify_error(e),
                all_tool_results, turn.warnings,
                {"needed": False, "reason": "Token limit exceeded before LLM could process."},
                "token_limit_exceeded: 上下文超过模型限制",
                {"estimated_tokens": e.estimated, "max_context_tokens": e.max_context, "limit_ratio": e.ratio})

        except Exception as e:
            run_error_hook(session, "llm_invoke_error", {"error": str(e)[:200]}, context)
            emitter.emit(StreamEvent.ERROR, {"error_type": classify_error(e), "message": str(e)[:200]})
            error_str = str(e)[:200]
            is_timeout = "timeout" in error_str.lower() or "timed out" in error_str.lower()
            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id, error=error_str)
            turn.status = "failed"
            turn.errors.append(error_str)
            # Redact raw error — never expose internal details to user
            user_msg = "LLM 服务请求超时，请稍后重试。" if is_timeout else "LLM 服务暂不可用，请稍后重试。"
            try:
                from agent.llm.config import record_recent_failure
                record_recent_failure(f"llm_invoke_error: {error_str[:100]}", "provider_timeout" if is_timeout else "provider_error")
            except Exception:
                pass
            return _error_result(session, turn, context, emitter, audit_events,
                user_msg, classify_error(e), [], turn.errors,
                {"needed": False, "reason": "LLM provider error prevented tool selection."},
                "provider_error: LLM 服务不可用",
                {"provider_error_type": "provider_timeout" if is_timeout else "provider_error", "retryable": is_timeout})

        if audit_events:
            audit_events.emit("model_response_received", session_id=session.session_id, turn_id=turn.turn_id, step=step)
        if audit_trace:
            audit_trace.record_model_response(turn.turn_id, step,
                                              has_content=bool(resp.content),
                                              has_tool_calls=resp.has_tool_calls(),
                                              finish_reason=getattr(resp, 'finish_reason', ''))
        context.metadata.setdefault("model_responses", []).append({
            "step": step,
            "has_content": bool(resp.content),
            "has_tool_calls": resp.has_tool_calls(),
            "finish_reason": getattr(resp, "finish_reason", ""),
            "tool_call_count": len(getattr(resp, "tool_calls", []) or []),
        })

        track_llm_usage(session, turn, resp, messages, context, step)

        # Handle provider error
        if resp.error:
            provider_meta = resp.metadata or {}
            error_type = provider_meta.get("error_type", "provider_error")
            is_timeout = error_type == "provider_timeout"
            retryable = provider_meta.get("retryable", is_timeout)

            emitter.emit(StreamEvent.ERROR, {"error_type": error_type, "message": resp.error[:200]})

            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  error=f"Provider error ({error_type}): {resp.error}")

            turn.status = "failed"
            turn.errors.append(resp.error)

            user_msg = "LLM 服务请求超时，请稍后重试。系统已保留本轮事件记录。" if is_timeout else f"LLM 服务暂不可用：{resp.error[:200]}"

            try:
                from agent.llm.config import record_recent_failure
                record_recent_failure(user_msg, "provider_timeout" if is_timeout else "provider_error")
            except Exception:
                pass

            return _error_result(session, turn, context, emitter, audit_events,
                user_msg, error_type, [], [resp.error],
                {"needed": False, "reason": "Provider error."},
                "provider_error: LLM 服务异常",
                {"provider_error_type": error_type, "retryable": retryable,
                 "provider_error_detail": provider_meta.get("error_detail", "")})

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

            expanded_tools_this_step = []
            for tc in resp.tool_calls:
                llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")

                try:
                    tool_call = context.tool_router.build_tool_call(tc)
                except Exception as e:
                    _handle_unknown_tool(tc, llm_name, e, all_tool_results, messages, audit_events, audit_trace, session, turn, step)
                    continue

                if audit_events:
                    audit_events.emit("tool_call_started", session_id=session.session_id, turn_id=turn.turn_id,
                                      tool_id=tool_call.real_tool_id)
                emitter.emit(StreamEvent.TOOL_CALL, {"tool_id": tool_call.real_tool_id, "step": step})
                if audit_trace:
                    audit_trace.record_tool_call(turn.turn_id, step, tool_call.real_tool_id, str(tool_call.arguments)[:100])

                # ── Runtime Chain Integrity: pre_tool → permission → approval → dispatch → post_tool → append
                result, should_skip, should_stop = _execute_tool_chain(
                    tool_call, tc, context, session, turn, step,
                    audit_events, audit_trace, emitter, all_tool_results, messages,
                )

                if should_stop:
                    _tool_stop_requested = True
                    continue
                if should_skip:
                    continue

                added_tools = _maybe_expand_tools_from_catalog_result(
                    result, context, session, turn, step, audit_events, emitter,
                )
                if added_tools:
                    expanded_tools_this_step.extend(added_tools)
                    try:
                        tools = context.tool_router.model_visible_tools()
                    except Exception:
                        pass

            if _tool_stop_requested:
                final_response = "Tool execution was stopped by a post-tool hook."
                break

            repeated_failure = _repeated_tool_failure(all_tool_results)
            if repeated_failure:
                tool_id = repeated_failure.get("tool_id", "unknown")
                summary = repeated_failure.get("summary") or "工具连续返回相同错误。"
                message = f"任务已停止：{tool_id} 连续执行失败。{summary}"
                turn.status = "failed"
                turn.warnings.append(f"repeated_tool_failure: {tool_id}")
                emitter.emit(StreamEvent.ERROR, {
                    "error_type": "repeated_tool_failure",
                    "tool_id": tool_id,
                    "message": message,
                })
                return _error_result(
                    session, turn, context, emitter, audit_events,
                    message, ErrorType.TOOL_ERROR, all_tool_results, turn.warnings,
                    _build_tool_decision(all_tool_results, context), "",
                    {"terminal_reason": "repeated_tool_failure", "steps": step},
                )

            if expanded_tools_this_step:
                messages.append(RuntimeContextMessage(content=(
                    "Tool catalog expanded the current turn with these newly visible tools: "
                    + json.dumps(sorted(set(expanded_tools_this_step)), ensure_ascii=False)
                    + ". Continue by calling the best matching specialized tool if it is needed."
                )).to_llm_message())

            continue

        # LLM returned content (final answer)
        # Only force tool retry if LLM returned empty content
        if not resp.content and _should_retry_for_required_tools(context, all_tool_results, step):
            messages.append(RuntimeContextMessage(content=_required_tool_retry_prompt(context)).to_llm_message())
            context.metadata["required_tool_retry_used"] = True
            if audit_events:
                audit_events.emit("model_retry_required_tool", session_id=session.session_id,
                                  turn_id=turn.turn_id, step=step)
            continue

        if not _tool_stop_requested:
            from agent.llm.runtime import sanitize_provider_output
            import sys as _sys
            print(f"[loop] final_answer content_len={len(resp.content or '')}, tool_calls={resp.has_tool_calls()}", file=_sys.stderr)
            final_response, reasoning_stripped = sanitize_provider_output(resp.content)
            if audit_events:
                audit_events.emit("assistant_message", session_id=session.session_id, turn_id=turn.turn_id,
                                  content_len=len(final_response), reasoning_stripped=reasoning_stripped)

        # v1.0.3.5: output policy check
        output_policy_ok = _check_output_policy(final_response, turn)

        session.history.append(UserMessage(content=context.user_input))
        session.history.append(AssistantMessage(content=final_response))

        if audit_events:
            audit_events.emit("turn_finished", session_id=session.session_id, turn_id=turn.turn_id)
        turn.status = "finished"
        turn.final_response = final_response

        emitter.emit(StreamEvent.FINAL, {"final_response": final_response[:200]})
        stream_events = emitter.to_events()
        event_times = [
            float(e.get("timestamp", 0))
            for e in stream_events
            if isinstance(e, dict) and e.get("timestamp") is not None
        ]
        timeline_summary = {
            "node_count": max(6, len(stream_events)),
            "total_duration_ms": int((max(event_times) - min(event_times)) * 1000) if len(event_times) >= 2 else 0,
            "artifact_saved_count": sum(len(getattr(tr, "artifacts", []) or []) for tr in all_tool_results),
        }

        tool_decision = _build_tool_decision(all_tool_results, context)
        no_tool_reason = _build_no_tool_reason(all_tool_results, context)

        result = AgentResult(
            ok=True,
            final_response=final_response,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            trace_id=context.trace_id,
            tool_calls=all_tool_results,
            warnings=turn.warnings,
            events=stream_events,
            tool_decision=tool_decision,
            no_tool_reason=no_tool_reason,
            metadata=enrich_metadata({
                "model": context.model_config.get("model", ""),
                "steps": step,
                "output_policy_ok": output_policy_ok,
                "timeline_summary": timeline_summary,
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

        persist_run_record(session, turn, result, context)

        try:
            from agent.llm.config import record_recent_success
            record_recent_success()
        except Exception:
            pass

        run_post_turn_hooks(session, turn, final_response)
        run_stop_hooks(session)

        return result

    # Max steps exceeded
    turn.status = "finished"
    turn.warnings.append(f"max_steps ({MAX_STEPS}) reached — partial result")
    if audit_events:
        audit_events.emit("turn_finished", session_id=session.session_id, turn_id=turn.turn_id,
                          warning="max_steps exceeded")
    emitter.emit(StreamEvent.ERROR, {"error_type": "max_steps", "steps": MAX_STEPS, "message": f"已达到最大步数 ({MAX_STEPS})，返回部分结果"})
    stream_events = emitter.to_events()
    _partial = AgentResult(
        ok=True,
        final_response=f"[partial] {_build_partial_answer(all_tool_results)}",
        session_id=session.session_id,
        turn_id=turn.turn_id,
        trace_id=context.trace_id,
        warnings=[f"max_steps ({MAX_STEPS}) reached — partial result"],
        events=stream_events,
        metadata=enrich_metadata({
            "terminal_reason": "max_steps_exceeded",
            "partial": True,
            "steps": MAX_STEPS,
        }, context),
    )
    persist_run_record(session, turn, _partial, context)
    return _partial


# ─── Helper functions ─────────────────────────────────────────────────


def _error_result(session, turn, context, emitter, audit_events,
                  final_response, error_type, tool_calls, warnings,
                  tool_decision, no_tool_reason, extra_meta) -> AgentResult:
    """Build and persist an error AgentResult."""
    err = AgentResult(
        ok=False,
        final_response=final_response,
        session_id=session.session_id,
        turn_id=turn.turn_id,
        trace_id=context.trace_id,
        tool_calls=tool_calls,
        warnings=warnings,
        error_type=error_type,
        events=emitter.to_events(),
        tool_decision=tool_decision,
        no_tool_reason=no_tool_reason,
        metadata=enrich_metadata(extra_meta, context),
    )
    persist_run_record(session, turn, err, context)
    return err


def _repeated_tool_failure(tool_results: list) -> dict | None:
    """Detect an identical failed tool result repeated back-to-back."""
    if len(tool_results) < 2:
        return None
    previous, current = tool_results[-2], tool_results[-1]
    if previous.get("ok") or current.get("ok"):
        return None
    if previous.get("tool_id") != current.get("tool_id"):
        return None
    previous_errors = tuple(previous.get("errors") or [])
    current_errors = tuple(current.get("errors") or [])
    if previous_errors != current_errors:
        return None
    if not current_errors and previous.get("summary") != current.get("summary"):
        return None
    return current


def _maybe_expand_tools_from_catalog_result(result, context, session, turn, step, audit_events, emitter) -> list[str]:
    """Expand per-turn visible tools from a successful catalog search result."""
    if not result or getattr(result, "tool_id", "") != "tool.catalog.search" or not getattr(result, "ok", False):
        return []
    expansion = {}
    metadata = getattr(result, "metadata", {}) or {}
    if isinstance(metadata.get("tool_catalog_expansion"), dict):
        expansion = metadata["tool_catalog_expansion"]
    data = getattr(result, "data", {}) or {}
    raw = getattr(result, "raw", {}) or {}
    load_ids = (
        expansion.get("load_tool_ids")
        or data.get("load_tool_ids")
        or raw.get("load_tool_ids")
        or []
    )
    if not load_ids or not getattr(context, "tool_router", None):
        return []
    try:
        added = context.tool_router.expand_dynamic_visibility(load_ids)
    except Exception as exc:
        if hasattr(turn, "warnings"):
            turn.warnings.append(f"tool_catalog_expand_failed: {str(exc)[:120]}")
        return []
    if not added:
        return []
    visible = sorted(set(getattr(context, "visible_tool_ids", []) or []) | set(added))
    context.visible_tool_ids = visible
    context.metadata["visible_tools"] = visible
    context.metadata.setdefault("dynamic_tool_expansions", []).append({
        "step": step,
        "query": expansion.get("query", ""),
        "added_tool_ids": added,
    })
    try:
        from agent.runtime.query_engine import StreamEvent
        emitter.emit(StreamEvent.TOOL_RESULT, {
            "tool_id": "tool.catalog.search",
            "ok": True,
            "summary": f"工具目录已追加 {len(added)} 个工具到当前回合。",
            "added_tool_ids": added,
        })
    except Exception:
        pass
    if audit_events:
        audit_events.emit(
            "tool_catalog_expanded",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            step=step,
            added_tool_ids=added,
        )
    return added


def _execute_tool_chain(tool_call, tc, context, session, turn, step,
                        audit_events, audit_trace, emitter,
                        all_tool_results, messages):
    """Execute the full tool chain: pre_tool → permission → approval → dispatch → post_tool → append.

    Returns: (result, should_skip, should_stop)
    """
    from agent.runtime.query_engine import StreamEvent
    tid = tool_call.real_tool_id

    # 3. Pre-tool hook
    hook_allowed, hook_input, hook_reason = run_pre_tool_hook(session, tid, tool_call.arguments)
    if not hook_allowed:
        result = ToolResult(
            ok=False,
            summary=f"Tool {tid} blocked by pre-tool hook: {hook_reason}",
            errors=[f"hook_denied: {hook_reason}"],
        )
        _audit_tool_failed(audit_events, session, turn, tid, result.errors)
        if audit_trace:
            audit_trace.record_tool_result(turn.turn_id, step, tid, False, result.summary)
        _append_tool_result(result, tool_call, tc, all_tool_results, messages)
        return result, True, False  # skip

    if hook_input and isinstance(hook_input, dict):
        tool_call.arguments.update(hook_input)

    # 3.5 Permission Matrix check
    spec = context.tool_router.registry.get(tid) if hasattr(context.tool_router, 'registry') else None
    risk_level = getattr(spec, 'risk_level', 'low') if spec else 'low'
    requires_approval, denied, _decision = check_tool_permission(tid, spec, context, turn)

    if denied:
        result = build_permission_denied_result(tid)
        _audit_tool_failed(audit_events, session, turn, tid, result.errors)
        if audit_trace:
            audit_trace.record_tool_result(turn.turn_id, step, tid, False, result.summary)
        _append_tool_result(result, tool_call, tc, all_tool_results, messages)
        return result, True, False  # skip

    # 4. Approval gate
    if needs_approval(tid, spec, risk_level, requires_approval):
        # Check shell safety
        safe, denied_word = check_shell_safety(tid, tool_call.arguments)
        if not safe:
            result = build_shell_denied_result(tid, denied_word)
            _audit_tool_failed(audit_events, session, turn, tid, ["unsafe_command_denied"])
            if audit_trace:
                audit_trace.record_tool_result(turn.turn_id, step, tid, False, "unsafe_command_denied")
            _append_tool_result(result, tool_call, tc, all_tool_results, messages)
            return result, True, False  # skip

        # v2.3.1: Tool argument risk analysis before approval
        from agent.runtime.tool_argument_risk import analyze_tool_arguments, _detect_argument_source
        arg_source = _detect_argument_source(
            tool_call.arguments,
            context.user_input if hasattr(context, 'user_input') else "",
            context.safe_context if hasattr(context, 'safe_context') else None,
        )
        arg_risk = analyze_tool_arguments(
            tool_id=tid,
            arguments=tool_call.arguments,
            argument_source=arg_source,
            user_input=context.user_input if hasattr(context, 'user_input') else "",
            risk_level=risk_level,
        )
        if arg_risk.blocked:
            _audit_tool_failed(audit_events, session, turn, tid, [arg_risk.reason])
            if audit_trace:
                audit_trace.record_tool_result(turn.turn_id, step, tid, False, "argument_risk_blocked")
            result = ToolResult(ok=False, summary=arg_risk.reason, errors=[arg_risk.reason])
            _append_tool_result(result, tool_call, tc, all_tool_results, messages)
            return result, True, False  # skip

        from agent.approval import get_approval_store
        store = get_approval_store()
        apr = store.create(
            session_id=session.session_id,
            tool_id=tid,
            arguments=tool_call.arguments,
            description=getattr(spec, 'description', '')[:200],
            risk_level=risk_level,
            # v2.3.1: Enrich approval payload with risk source info
            metadata={
                "argument_source": arg_source,
                "argument_risk": arg_risk.risk_level,
                "recommendation": arg_risk.recommendation or "",
                "reason": arg_risk.reason or "",
            },
        )
        if audit_events:
            audit_events.emit("approval_required", session_id=session.session_id,
                              turn_id=turn.turn_id, approval_id=apr.approval_id, tool_id=apr.tool_id)
        emitter.emit(StreamEvent.APPROVAL_REQUIRED, {"approval_id": apr.approval_id, "tool_id": apr.tool_id})
        run_approval_hook(session, "required", apr.approval_id, apr.tool_id, context)

        # Non-blocking: wait up to 60s for user approval
        allowed = store.wait(apr.approval_id, timeout=60.0)
        store.cleanup(apr.approval_id)

        if not allowed:
            run_approval_hook(session, "denied", apr.approval_id, apr.tool_id, context)
            result = ToolResult(
                ok=False,
                summary=f"Tool {tid} was rejected by user",
                errors=["user_rejected"],
            )
            if audit_events:
                audit_events.emit("approval_denied", session_id=session.session_id, turn_id=turn.turn_id, tool_id=apr.tool_id)
            if audit_trace:
                audit_trace.record_tool_result(turn.turn_id, step, tid, False, "user_rejected")
            _append_tool_result(result, tool_call, tc, all_tool_results, messages)
            return result, True, False  # skip
        else:
            run_approval_hook(session, "allowed", apr.approval_id, apr.tool_id, context)

    # 5. Dispatch
    try:
        result = context.tool_router.dispatch(tool_call, context)
    except Exception as e:
        result = ToolResult(ok=False, summary=str(e)[:200], errors=[str(e)[:200]])

    # 6. Audit
    if audit_events:
        if result.ok:
            audit_events.emit("tool_call_finished", session_id=session.session_id,
                              turn_id=turn.turn_id, tool_id=tid, summary=result.summary)
        else:
            audit_events.emit("tool_call_failed", session_id=session.session_id,
                              turn_id=turn.turn_id, tool_id=tid, errors=result.errors)
    if audit_trace:
        audit_trace.record_tool_result(turn.turn_id, step, tid, result.ok, result.summary)

    emitter.emit(StreamEvent.TOOL_RESULT, {
        "tool_id": tid,
        "ok": result.ok if hasattr(result, 'ok') else False,
        "summary": (result.summary if hasattr(result, 'summary') else str(result))[:200],
    })

    # 7. Post-tool hook
    post_stop = run_post_tool_hook(session, tid, result, turn)
    if post_stop:
        turn.warnings.append(f"post_tool_stop: {tid} stopped by hook")
        _append_tool_result(result, tool_call, tc, all_tool_results, messages)
        return result, False, True  # stop

    # 8. Append result
    _append_tool_result(result, tool_call, tc, all_tool_results, messages)
    return result, False, False  # normal


def _append_tool_result(result, tool_call, tc, all_tool_results, messages):
    """Append a tool result to the result list and message list.

    v2.3.2: Scan tool result payload for prompt injection before appending to messages.
    """
    all_tool_results.append(to_standard_tool_call(tool_call.call_id, tool_call.real_tool_id, result))
    tool_msg_payload = build_tool_message_payload(result)

    # v2.3.2: Injection scan on tool result before entering messages
    try:
        from agent.runtime.rag_injection_scan import scan_tool_result_payload
        # v3.0.0: knowledge tools return user-curated content — reduced scan sensitivity
        is_knowledge = tool_call.real_tool_id.startswith("knowledge.")
        src_type = "knowledge" if is_knowledge else ""
        tool_msg_payload = scan_tool_result_payload(
            tool_msg_payload,
            tool_id=tool_call.real_tool_id,
            source="tool_output",
            source_type=src_type,
        )
    except Exception:
        pass  # scan failure should not block tool result

    _has_large = any(k in tool_msg_payload for k in (
        "content", "preview", "diff", "rendered", "document",
        "table", "markdown", "mermaid", "translated_config",
        "stdout", "stderr", "output", "text", "results", "items",
        "chunks", "hits", "result_stdout", "result_stderr",
        "result_output", "result_text",
    )) or len(json.dumps(tool_msg_payload, ensure_ascii=False)) > 8000
    trunc_limit = 20000 if _has_large else 8000
    serialized_payload = json.dumps(tool_msg_payload, ensure_ascii=False)
    tool_msg = ToolResultMessage(
        content=_preserve_tool_payload_edges(serialized_payload, trunc_limit),
        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
    )
    messages.append(tool_msg.to_llm_message())


def _should_retry_for_required_tools(context, all_tool_results: list, step: int) -> bool:
    if step != 1 or all_tool_results:
        return False
    if getattr(context, "metadata", {}).get("required_tool_retry_used"):
        return False
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    if not isinstance(scene, dict) or scene.get("needs_clarification"):
        return False
    required_steps = [
        s for s in scene.get("tool_plan", []) or []
        if isinstance(s, dict) and s.get("required") and s.get("tool_candidates")
    ]
    visible = set(getattr(context, "visible_tool_ids", []) or getattr(context, "metadata", {}).get("visible_tools", []) or [])
    if not required_steps or not visible:
        return False
    return any(set(step_def.get("tool_candidates") or []) & visible for step_def in required_steps)


def _required_tool_retry_prompt(context) -> str:
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    required = []
    if isinstance(scene, dict):
        for step_def in scene.get("tool_plan", []) or []:
            if isinstance(step_def, dict) and step_def.get("required"):
                required.append({
                    "step": step_def.get("step"),
                    "goal": step_def.get("goal"),
                    "tool_candidates": step_def.get("tool_candidates"),
                })
    return (
        "The current user request requires tool execution before a final answer. "
        "Do not answer from memory or general knowledge. Call one of the exposed "
        "functions for the first required step now. Required plan: "
        + json.dumps(required[:4], ensure_ascii=False)
    )


def _preserve_tool_payload_edges(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = f'\n"...[truncated middle, {len(text)} chars total]..."\n'
    keep = max(0, limit - len(marker))
    head = max(keep * 2 // 3, keep // 2)
    tail = keep - head
    return text[:head] + marker + text[-tail:]


def _handle_unknown_tool(tc, llm_name, error, all_tool_results, messages, audit_events, audit_trace, session, turn, step):
    """Handle an unknown tool call from the LLM.

    v2.3.3: Enhanced hint with alternative tool suggestions so the LLM
    can recover rather than falling back to python.exec.
    """
    error_name = getattr(error, '__class__', type(error)).__name__
    if audit_events:
        audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                          tool_id=llm_name, errors=[str(error)[:200]])
    if audit_trace:
        audit_trace.record_tool_result(turn.turn_id, step, llm_name, False, str(error)[:100])
    all_tool_results.append({
        "tool_id": llm_name,
        "ok": False,
        "summary": f"Tool not visible to model: {llm_name}",
    })
    # v2.3.3: Suggest alternative tools based on what the LLM was trying to do
    hint = (
        "This tool is not available in your current function list. "
        "Use ONLY the tools provided. If you need to read a file, use workspace__file__read. "
        "If you need to parse a config, use network__config__parse. "
        "If a provided host exec tool is the best fit for local computation or diagnostics, "
        "call it and let the approval popup handle risk."
    )
    tool_msg = ToolResultMessage(
        content=json.dumps({
            "ok": False,
            "error": f"{error_name}: {str(error)[:200]}",
            "hint": hint,
        }, ensure_ascii=False)[:1200],
        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
    )
    messages.append(tool_msg.to_llm_message())


def _audit_tool_failed(audit_events, session, turn, tool_id, errors):
    """Emit tool_call_failed audit event."""
    if audit_events:
        audit_events.emit("tool_call_failed", session_id=session.session_id,
                          turn_id=turn.turn_id, tool_id=tool_id, errors=errors)


def _check_output_policy(final_response, turn) -> bool:
    """Check output policy and append warning if needed. Returns True if OK."""
    try:
        from prompts.policy import check_prompt_output
        out_result = check_prompt_output(final_response)
        if not out_result.is_ok:
            turn.warnings.append(f"output_policy_failed: {out_result.issues}")
            return False
        return True
    except Exception:
        return True


def _apply_manual_compact(session, turn, messages):
    """Apply manual compact flag from /compact command."""
    manual_compact_requested = getattr(session, 'metadata', {}).get('manual_compact_requested') if hasattr(session, 'metadata') else False
    if not manual_compact_requested:
        try:
            import json as _json
            from pathlib import Path
            from workspace.run_store import WS_ROOT as _wsr
            meta_path = _wsr / (session.workspace_id or 'default') / "sessions" / session.session_id / "meta.json"
            if meta_path.is_file():
                disk_meta = _json.loads(meta_path.read_text(encoding='utf-8'))
                manual_compact_requested = disk_meta.get('manual_compact_requested', False)
        except Exception:
            pass

    if not manual_compact_requested:
        return

    try:
        from agent.runtime.context_compactor import compact_messages
        compacted, meta = compact_messages(messages, keep_recent=6)
        if meta.get('compacted'):
            messages[:] = compacted
            if hasattr(session, 'metadata'):
                session.metadata['manual_compact_requested'] = False
                session.metadata['manual_compact_applied'] = True
            try:
                import json as _json
                from pathlib import Path
                from workspace.run_store import WS_ROOT as _wsr2
                meta_path2 = _wsr2 / (session.workspace_id or 'default') / "sessions" / session.session_id / "meta.json"
                if meta_path2.is_file():
                    disk_meta2 = _json.loads(meta_path2.read_text(encoding='utf-8'))
                    disk_meta2.pop('manual_compact_requested', None)
                    disk_meta2['manual_compact_applied'] = True
                    meta_path2.write_text(_json.dumps(disk_meta2, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass
            turn.warnings.append(f"manual_compact_applied: {meta.get('compacted_message_count')} msgs")
    except Exception as e:
        turn.warnings.append(f"manual_compact_failed: {e}")
