# agent/runtime/loop.py
"""RuntimeLoop — the core turn execution engine (Codex-style agentic loop)."""

import json
from agent.protocol.message import UserMessage, SystemMessage, AssistantMessage, ToolResultMessage, RuntimeContextMessage
from agent.runtime.result import AgentResult
from agent.llm.runtime import invoke_llm

MAX_STEPS = 8


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
            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  error=str(e)[:200])
            turn.status = "failed"
            turn.errors.append(str(e)[:200])
            return AgentResult(
                ok=False, final_response=f"LLM error: {str(e)[:200]}",
                session_id=session.session_id, turn_id=turn.turn_id, trace_id=context.trace_id,
                errors=[str(e)[:200]],
                events=_collect_events(audit_events, turn.turn_id),
            )

        if audit_events:
            audit_events.emit("model_response_received", session_id=session.session_id, turn_id=turn.turn_id, step=step)
        if audit_trace:
            audit_trace.record_model_response(turn.turn_id, step,
                                              has_content=bool(resp.content),
                                              has_tool_calls=resp.has_tool_calls(),
                                              finish_reason=getattr(resp, 'finish_reason', ''))

        # Handle provider error
        if resp.error:
            if audit_events:
                audit_events.emit("turn_failed", session_id=session.session_id, turn_id=turn.turn_id,
                                  error=f"Provider error: {resp.error}")
            turn.status = "failed"
            turn.errors.append(resp.error)
            return AgentResult(
                ok=False, final_response=f"Provider unavailable: {resp.error}",
                session_id=session.session_id, turn_id=turn.turn_id, trace_id=context.trace_id,
                errors=[resp.error],
                events=_collect_events(audit_events, turn.turn_id),
            )

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
                tool_call = context.tool_router.build_tool_call(tc)

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
                    result = type('obj', (object,), {'ok': False, 'summary': str(e)[:200], 'errors': [str(e)[:200]]})()

                all_tool_results.append({
                    "tool_id": tool_call.real_tool_id,
                    "ok": result.ok,
                    "summary": getattr(result, 'summary', str(result))[:500],
                })

                tool_msg = ToolResultMessage(
                    content=json.dumps({"ok": result.ok, "summary": getattr(result, 'summary', '')}, ensure_ascii=False)[:1000],
                    tool_call_id=tc.id,
                )
                messages.append(tool_msg.to_llm_message())

            continue

        # LLM returned content (final answer)
        final_response = resp.content
        if audit_events:
            audit_events.emit("assistant_message", session_id=session.session_id, turn_id=turn.turn_id,
                              content_len=len(final_response))

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
            metadata={"model": context.model_config.get("model", ""), "steps": step},
        )

        # Persist rollout
        try:
            if services and hasattr(services, 'audit_service') and services.audit_service:
                rollout = services.audit_service.get("rollout")
                if rollout:
                    rollout.persist_turn(turn, result)
        except Exception:
            pass

        return result

    # Max steps exceeded
    turn.status = "finished"
    turn.warnings.append(f"max_steps ({MAX_STEPS}) reached — partial result")
    if audit_events:
        audit_events.emit("turn_finished", session_id=session.session_id, turn_id=turn.turn_id,
                          warning="max_steps exceeded")
    return AgentResult(
        ok=True,
        final_response=_build_partial_answer(all_tool_results),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        trace_id=context.trace_id,
        warnings=["max_steps exceeded"],
        events=_collect_events(audit_events, turn.turn_id),
    )


def _build_initial_messages(context, services) -> list:
    """Build initial message list with system prompt, snapshot, skill injections, history, user input."""
    messages = []

    # System prompt
    messages.append(SystemMessage(
        content="You are Network Agent, an AI assistant for network operations. "
                "You can use tools to help users with network configuration, queries, and analysis. "
                "Be concise and helpful. Use tools when appropriate."
    ).to_llm_message())

    # Runtime snapshot
    from agent.context.snapshot import RuntimeSnapshot
    snap = RuntimeSnapshot(**{k: v for k, v in (context.runtime_snapshot or {}).items()
                               if k in ['tool_count', 'visible_tool_count', 'enabled_skills', 'planned_skills',
                                        'enabled_modules', 'planned_modules', 'workspace_id', 'session_id', 'model']})
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


def _build_partial_answer(tool_results: list) -> str:
    """Build partial answer when max steps exceeded."""
    if not tool_results:
        return "I've completed the analysis but need more information to provide a complete answer."
    parts = ["Here's what I've found so far:"]
    for tr in tool_results[-5:]:
        parts.append(f"- {tr.get('tool_id', 'unknown')}: {tr.get('summary', 'no result')}")
    return "\n".join(parts)
