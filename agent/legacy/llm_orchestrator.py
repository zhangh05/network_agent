# agent/nodes/llm_orchestrator.py
"""LLM Orchestrator — agentic loop where LLM is the brain.

LLM receives all 53+ tool definitions, decides which to call,
Tool Runtime executes safely, results feed back to LLM for
further decisions or final response.
"""

import json
import re
import time
from typing import List, Optional

from agent.state import NetworkAgentState
from agent.llm.schemas import LLMRequest, LLMMessage, LLMResponse, LLMToolCall
from agent.llm.tool_adapter import to_llm_tool_name, from_llm_tool_name

MAX_ORCHESTRATION_STEPS = 10


def orchestrate(state: NetworkAgentState) -> NetworkAgentState:
    """LLM-driven agentic loop: LLM decides tools -> execute -> loop -> final answer.

    Uses Task/Turn model for lifecycle tracking (inspired by Codex).
    Each LLM decision cycle is a Turn; the entire user request is a Task.
    """
    from agent.task import Task
    from agent.turn import Turn

    # Initialize Task tracking
    task = Task(
        intent=state.intent or "unknown",
        user_input=state.user_input or "",
        workspace_id=state.workspace_id or "default",
        session_id=getattr(state, "session_id", ""),
    )
    task.start()
    state.context.setdefault("task", {})
    state.context["task"] = task.as_dict()

    ws_id = state.workspace_id or "default"
    user_input = state.user_input or ""

    # 1. If LLM is disabled, handle ALL queries deterministically
    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()
    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        _handle_llm_disabled(state, ws_id)
        task.complete({"mode": "deterministic"})
        state.context["task"] = task.as_dict()
        return state

    # 2b. Module intents (translate_config, etc.) → direct adapter execution
    MODULE_INTENTS = {"translate_config", "context_qa"}
    if state.intent in MODULE_INTENTS:
        _execute_module_direct(state, task, ws_id)
        state.context["task"] = task.as_dict()
        return state

    # 3. Normal LLM orchestration flow

    # ── Pre-turn compaction check ──
    from context.compaction import should_compact, compact_session_history, estimate_tokens
    context_size = estimate_tokens(str(state.context.get("safe_llm_context", {})))
    compact_needed, cur_tokens, budget = should_compact(context_size, cfg.get("model", "default"))
    if compact_needed:
        logger.info("Pre-turn compaction triggered: %d/%d tokens", cur_tokens, budget)
        from context.compaction import compact_llm_context
        state.context["safe_llm_context"] = compact_llm_context(
            state.context.get("safe_llm_context", {}),
            cfg.get("model", "default"),
        )
        state.context.setdefault("compaction_meta", {})
        state.context["compaction_meta"]["pre_turn"] = {
            "original_tokens": cur_tokens, "budget": budget,
        }

    # 2. Build tool definitions
    from agent.llm.tool_adapter import list_tools_for_orchestrator, build_system_prompt_with_tools
    tools = list_tools_for_orchestrator()

    # 3. Build messages with session history
    system_prompt = build_system_prompt_with_tools(ws_id)
    messages = [LLMMessage(role="system", content=system_prompt)]

    # Load recent conversation history if session exists
    session_id = getattr(state, 'session_id', None)
    if session_id:
        try:
            from workspace.session_store import get_session_messages
            history = get_session_messages(session_id, ws_id)
            recent = history[-8:]  # Last 4 turns (8 messages) max
            for m in recent:
                role = m.get("role", "user")
                content = (m.get("content") or "")[:1000]
                if role in ("user", "assistant"):
                    messages.append(LLMMessage(role=role, content=content))
        except Exception:
            pass

    messages.append(LLMMessage(role="user", content=user_input))

    # 4. Agentic loop
    from agent.llm.runtime import invoke_llm

    all_tool_results = []
    final_answer = ""
    step = 0

    while step < MAX_ORCHESTRATION_STEPS:
        step += 1

        # Track this turn
        turn = Turn(task.record_turn())

        try:
            resp = invoke_llm(
                task="assistant_chat",
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            turn.fail(str(e)[:200])
            final_answer = _build_partial_answer(all_tool_results, str(e)[:200])
            break

        if resp.error:
            if step == 1:
                final_answer = f"LLM error: {resp.error}"
            else:
                final_answer = _build_partial_answer(all_tool_results, resp.error)
            break

        if resp.has_tool_calls():
            # Build ONE assistant message with ALL tool calls (OpenAI protocol)
            assistant_msg = LLMMessage(
                role="assistant",
                content=resp.content if resp.content else "",
                tool_calls=[{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                } for tc in resp.tool_calls],
            )
            messages.append(assistant_msg)

            for tc in resp.tool_calls:
                # ── Map LLM-safe name back to real tool_id ──
                real_tool_id = from_llm_tool_name(tc.name)

                # ── PreToolUse hook (can deny or rewrite input) ──
                from agent.hooks_integration import run_pre_tool_hooks
                allowed, updated_args, deny_reason = run_pre_tool_hooks(
                    state, real_tool_id, tc.arguments
                )
                if not allowed:
                    tool_result = {"ok": False, "status": "denied_by_hook",
                                   "summary": deny_reason, "errors": [deny_reason], "warnings": []}
                else:
                    effective_args = updated_args if updated_args else tc.arguments
                    tool_result = _execute_tool(real_tool_id, effective_args, ws_id, state)

                turn.record_tool_call(real_tool_id, tc.arguments, tool_result)

                # ── PostToolUse hook (can stop the turn) ──
                from agent.hooks_integration import run_post_tool_hooks
                should_continue, feedback = run_post_tool_hooks(state, real_tool_id, tool_result)
                if feedback:
                    tool_result["hook_feedback"] = feedback

                all_tool_results.append({
                    "tool_id": real_tool_id,
                    "arguments": tc.arguments,
                    "ok": tool_result.get("ok", False),
                    "summary": _truncate(tool_result.get("summary", ""), 500),
                    "errors": tool_result.get("errors", [])[:5],
                })
                tool_msg = LLMMessage(
                    role="tool",
                    content=json.dumps(tool_result, ensure_ascii=False)[:1000],
                    tool_call_id=tc.id,
                )
                messages.append(tool_msg)

            continue

        final_answer = _clean_response(resp.content)
        turn.complete(final_answer)

        # ── Stop hook: can block completion (force continue) ──
        from agent.hooks_integration import run_stop_hooks
        should_stop, block_reason = run_stop_hooks(state)
        if not should_stop:
            logger.info("Stop hook blocked completion: %s", block_reason)
            # Inject the block reason as context for next turn
            messages.append(LLMMessage(
                role="system",
                content=f"Hook feedback: {block_reason}. Please continue.",
            ))
            continue

        break

    # 6. Set result and complete task
    if not final_answer:
        final_answer = _build_partial_answer(all_tool_results, "no response")
        state.warnings.append(f"orchestration max steps ({MAX_ORCHESTRATION_STEPS}) reached")
        task.fail("max_steps_reached")
    else:
        task.complete({"turn_count": step, "tool_calls": len(all_tool_results)})

    state.context["task"] = task.as_dict()
    state.tool_results = {
        "ok": True,
        "answer": final_answer,
        "tool_calls": all_tool_results,
        "steps": step,
        "mode": "llm_orchestrated",
    }
    state.skill_results = state.tool_results
    state.final_response = final_answer

    return state


def _record_module_event(state: NetworkAgentState, event_type: str, skill: str,
                         capability_id: str, status: str = "started",
                         summary: str = "") -> None:
    """Record a module_call event in trace_events.

    Used by _execute_module_direct() to record module execution lifecycle.
    """
    state.trace_events.append({
        "event_id": f"{skill}_{event_type}_{len(state.trace_events)}",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": event_type,
        "name": skill,
        "status": status,
        "duration_ms": 0.0,
        "summary": summary or f"{event_type}: {skill}",
        "metadata": {
            "skill": skill,
            "capability_id": capability_id,
            "intent": state.intent,
        },
        "redaction_applied": False,
    })


def _execute_module_direct(state: NetworkAgentState, task: "Task", ws_id: str) -> None:
    """Execute a module intent directly (translate_config, etc.) within Task/Turn lifecycle.

    Unlike the LLM agentic loop, module intents call the registered adapter
    directly. But they still get:
    - Task/Turn tracking
    - PreTurn/PostTurn/Stop hooks
    - Result recording in skill_results
    """
    from agent.turn import Turn
    import importlib

    skill = state.selected_skill or ""
    capability_id = state.context.get("capability_id", "")

    # ── Create a Turn for this direct execution ──
    turn = Turn(task.record_turn())

    # ── PreTurn hooks ──
    from agent.hooks_integration import run_pre_turn_hooks
    should_continue, context_injections, block_reason = run_pre_turn_hooks(state, turn.turn_number)
    if context_injections:
        state.context.setdefault("hook_context", []).extend(context_injections)

    if not should_continue:
        state.error = f"PreTurn hook blocked: {block_reason}"
        state.skill_results = {"ok": False, "error": state.error}
        task.fail(state.error)
        return

    # ── Record module_call_start event ──
    _record_module_event(state, "module_call_start", skill, capability_id)

    # ── Execute adapter (same logic as skill_executor's old path) ──
    if not skill:
        state.error = "No skill selected"
        task.fail(state.error)
        _record_module_event(state, "module_call_end", skill, capability_id, status="failed", summary=state.error)
        return

    try:
        from registry.loader import get_skill
        spec = get_skill(skill)
        if not spec:
            state.error = f"skill_spec_not_found: {skill}"
            task.fail(state.error)
            _record_module_event(state, "module_call_end", skill, capability_id, status="failed", summary=state.error)
            return

        if spec.status == "planned":
            state.skill_results = {"ok": False, "error": f"Intent '{state.intent}' is planned"}
            state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")
            task.complete({"mode": "planned"})
            _record_module_event(state, "module_call_end", skill, capability_id, status="skipped", summary="planned")
            return

        if spec.status == "disabled":
            state.error = f"Skill '{skill}' is disabled"
            task.fail(state.error)
            _record_module_event(state, "module_call_end", skill, capability_id, status="failed", summary="disabled")
            return

        # Resolve entrypoint
        entrypoint_fn = spec.entrypoint_function or ""
        for cap in (spec.capabilities or []):
            if isinstance(cap, dict) and cap.get("capability_id") == capability_id:
                fn = cap.get("function", "")
                if fn:
                    entrypoint_fn = fn
                break

        adapter_path = spec.adapter_path or ""
        if adapter_path and entrypoint_fn:
            mod_path = adapter_path.replace(".py", "").replace("/", ".")
            mod = importlib.import_module(mod_path)
            func = getattr(mod, entrypoint_fn)
            result = func(payload=state.payload)
        else:
            result = {"ok": False, "error": f"No adapter for {skill}"}

    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

    # ── Record result ──
    state.skill_results = result if isinstance(result, dict) else {"ok": True, "data": result}
    state.tool_results = state.skill_results

    if not result.get("ok"):
        state.error = result.get("error", "execution_failed")
        task.fail(state.error)
        _record_module_event(state, "module_call_end", skill, capability_id, status="failed", summary=state.error)
    else:
        turn.record_tool_call(skill, state.payload, result)
        _record_module_event(state, "module_call_end", skill, capability_id, status="succeeded",
                            summary=str(result.get("summary", ""))[:200])

    # ── PostTurn hooks ──
    from agent.hooks_integration import run_post_turn_hooks
    force_continue, post_context = run_post_turn_hooks(
        state, turn.turn_number, str(result.get("summary", ""))[:200]
    )
    if post_context:
        state.context.setdefault("hook_context", []).extend(post_context)

    # ── Stop hooks ──
    from agent.hooks_integration import run_stop_hooks
    should_stop, block_reason = run_stop_hooks(state)
    if not should_stop:
        logger.info("Stop hook blocked module completion: %s", block_reason)

    turn.complete(str(state.skill_results.get("summary", ""))[:200])
    task.complete({"mode": "module_direct", "skill": skill})


def _execute_tool(tool_id: str, arguments: dict, workspace_id: str, state: NetworkAgentState) -> dict:
    """Execute a tool through the Tool Runtime safety pipeline.

    Args:
        tool_id: The tool to invoke
        arguments: Tool arguments
        workspace_id: Workspace ID for isolation
        state: Current agent state (used to build ToolRuntimeContext)
    """
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext

        client = get_default_tool_runtime_client()

        # Build ToolRuntimeContext for proper workspace isolation, trace, and audit
        ctx = ToolRuntimeContext(
            workspace_id=workspace_id,
            run_id=state.request_id,
            trace_id=state.trace_id,
            requested_by=f"orchestrator:{state.intent}",
        )

        result = client.invoke(
            tool_id=tool_id,
            arguments=arguments,
            context=ctx,
        )
        return {
            "ok": result.status in ("succeeded", "dry_run"),
            "status": result.status,
            "summary": result.summary,
            "output": _safe_dict(result.output),
            "errors": result.errors[:10],
            "warnings": result.warnings[:10],
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}


def _truncate(text, max_len: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s[:max_len] + ("..." if len(s) > max_len else "")


def _clean_response(text: str) -> str:
    """Remove provider reasoning markup from LLM output.

    Delegates to agent.llm.runtime.sanitize_provider_output for canonical cleanup.
    """
    if not text:
        return ""
    from agent.llm.runtime import sanitize_provider_output
    cleaned, _ = sanitize_provider_output(text)
    if cleaned:
        return cleaned
    # If all content was inside think tags, return a fallback message
    if text.strip():
        return "思考过程已过滤。请重新描述您的问题。"
    return text.strip()


def _build_partial_answer(tool_results: list, error: str) -> str:
    """Build a partial answer when LLM fails after some tool calls."""
    if not tool_results:
        return f"LLM error: {error}"
    successes = [r for r in tool_results if r.get("ok")]
    msg = f"部分工具执行完成（{len(successes)}/{len(tool_results)} 成功），但 LLM 处理出错：{error}"
    for r in tool_results[:3]:
        msg += f"\n- {r.get('tool_id', '')}: {'OK' if r.get('ok') else 'FAILED'}"
    return msg


def _handle_llm_disabled(state: NetworkAgentState, workspace_id: str):
    """Handle tool-related queries when LLM is disabled.

    Deterministic logic to:
    1. Answer tool capability questions (tool count, catalog)
    2. Execute low-risk tool calls directly
    3. Block high-risk tool calls
    """
    user_input = (state.user_input or "").lower().strip()

    # ── 1. Tool capability questions ──
    _TOOL_QUERY_KEYWORDS = [
        "多少tool", "多少 tool", "工具数量", "tool 数量",
        "tool count", "how many tool", "tool catalog",
        "工具目录", "有哪些tool", "有哪些 tool",
        "你能做什么", "你能调用", "能力",
    ]
    if any(kw in user_input for kw in _TOOL_QUERY_KEYWORDS):
        try:
            from tool_runtime.integration import get_default_tool_runtime_client
            client = get_default_tool_runtime_client()
            tools = client.list_tools()
            count = client.tool_count
            # Build catalog dict matching what tests expect
            by_risk = {}
            by_category = {}
            auto_callable = 0
            for t in tools:
                risk = t.get("risk_level", "unknown")
                by_risk[risk] = by_risk.get(risk, 0) + 1
                cat = t.get("category", "unknown")
                by_category[cat] = by_category.get(cat, 0) + 1
                if risk == "low":
                    auto_callable += 1
            catalog = {
                "count": count,
                "auto_callable_count": auto_callable,
                "by_risk": by_risk,
                "by_category": by_category,
                "tools": tools[:20],
            }
            state.skill_results = {
                "ok": True,
                "mode": "tool_catalog",
                "tool_catalog": catalog,
            }
            state.tool_results = state.skill_results
            return
        except Exception as e:
            state.warnings.append(f"tool_catalog failed: {str(e)[:100]}")
            # fall through to general response

    # ── 2. Tool invocation requests ──
    _INVOKE_PATTERNS = [
        r"调用\s+(\S+)", r"invoke\s+(\S+)", r"执行\s+(\S+)",
        r"run\s+(\S+)", r"call\s+(\S+)", r"帮我调用\s+(\S+)",
    ]
    import re as _re
    tool_id = None
    for pattern in _INVOKE_PATTERNS:
        m = _re.search(pattern, user_input, _re.IGNORECASE)
        if m:
            tool_id = m.group(1).strip()
            break

    if tool_id:
        try:
            from tool_runtime.integration import get_default_tool_runtime_client
            from tool_runtime.schemas import ToolInvocation

            client = get_default_tool_runtime_client()
            tool_spec = client.get_tool(tool_id)

            if tool_spec and tool_spec.get("risk_level") in ("high", "forbidden"):
                state.tool_results = {
                    "ok": False,
                    "mode": "tool_runtime_blocked",
                    "tool_id": tool_id,
                    "reason": "approval_required",
                    "risk_level": tool_spec.get("risk_level"),
                }
                state.skill_results = state.tool_results
                return

            # Low/medium risk: execute
            invocation = ToolInvocation(
                tool_id=tool_id,
                arguments={},
                workspace_id=workspace_id,
                requested_by="deterministic:llm_disabled",
            )
            result = client._executor.execute(invocation)
            state.tool_results = {
                "ok": result.status in ("succeeded", "dry_run"),
                "mode": "tool_runtime",
                "tool_id": tool_id,
                "status": result.status,
                "summary": result.summary,
                "output": _safe_dict(result.output) if hasattr(result, "output") else {},
                "errors": result.errors[:5] if hasattr(result, "errors") else [],
                "warnings": result.warnings[:5] if hasattr(result, "warnings") else [],
                "duration_ms": result.duration_ms if hasattr(result, "duration_ms") else 0,
            }
            state.skill_results = state.tool_results
            state.context.setdefault("tool_invocations", []).append({
                "tool_id": tool_id,
                "status": result.status,
                "summary": (result.summary or "")[:200],
            })
            return

        except Exception as e:
            state.tool_results = {
                "ok": False,
                "mode": "tool_runtime",
                "tool_id": tool_id,
                "status": "failed",
                "error": str(e)[:200],
            }
            state.skill_results = state.tool_results
            return

    # ── 3. General chat: mark LLM as disabled ──
    state.context.setdefault("llm", {})["enabled"] = False
    state.context["llm"]["provider_type"] = "disabled"
    # Set deterministic response for composer
    state.tool_results = {
        "ok": True,
        "mode": "assistant_chat",
        "answer": "LLM is disabled. I can still help with tool calls and deterministic tasks."
    }
    state.skill_results = state.tool_results

def _safe_dict(d: dict) -> dict:
    """Return a sanitized shallow copy."""
    if not d:
        return {}
    result = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 1000:
            result[k] = v[:1000] + "..."
        else:
            result[k] = v
    return result


