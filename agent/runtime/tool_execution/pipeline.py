# agent/runtime/tool_execution/pipeline.py
"""ToolExecutionPipeline — orchestrates tool chain: pre_tool → permission → risk → approval → dispatch → post_tool → append.

Also contains helper functions moved from loop.py:
- _execute_tool_chain
- _handle_unknown_tool, _audit_tool_failed
- _maybe_expand_tools_from_catalog_result
- _repeated_tool_failure
- _should_retry_for_required_tools, _required_tool_retry_prompt
- _check_output_policy, _preserve_tool_payload_edges
"""

import json

from agent.protocol.message import ToolResultMessage
from agent.protocol.tool_result import ToolResult
from agent.runtime.hook_runner import run_pre_tool_hook, run_post_tool_hook
from agent.runtime.query_engine import StreamEvent

from agent.runtime.tool_execution.permission_stage import PermissionStage
from agent.runtime.tool_execution.risk_stage import RiskStage
from agent.runtime.tool_execution.approval_stage import ApprovalStage
from agent.runtime.tool_execution.dispatch_stage import DispatchStage
from agent.runtime.tool_execution.result_stage import ResultStage, _append_tool_result


class ToolExecutionPipeline:
    """Orchestrate the full tool chain for a set of tool calls."""

    def __init__(self):
        self._permission = PermissionStage()
        self._risk = RiskStage()
        self._approval = ApprovalStage()
        self._dispatch = DispatchStage()
        self._result = ResultStage()

    def run(self, state, resp, events):
        """Execute all tool calls from the model response.

        Returns True if a post-tool hook requested a stop.
        """
        from agent.protocol.message import AssistantMessage

        assistant_msg = AssistantMessage(
            content=resp.content if resp.content else "",
            tool_calls=[{
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
            } for tc in resp.tool_calls],
        )
        state.messages.append(assistant_msg.to_llm_message())

        expanded_tools_this_step = []
        tool_stop_requested = False

        for tc in resp.tool_calls:
            llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")

            try:
                tool_call = state.context.tool_router.build_tool_call(tc)
            except Exception as e:
                _handle_unknown_tool(
                    tc, llm_name, e, state.all_tool_results, state.messages,
                    state.audit_events, state.audit_trace, state.session, state.turn, state.step)
                continue

            events.tool_call_started(tool_call.real_tool_id, state.step)
            events.record_tool_call(state.step, tool_call.real_tool_id, str(tool_call.arguments)[:100])

            # Execute the full chain
            result, should_skip, should_stop = self._execute_single(
                state, tool_call, tc, events, state.step)

            if should_stop:
                tool_stop_requested = True
                continue
            if should_skip:
                continue

            added_tools = _maybe_expand_tools_from_catalog_result(
                result, state.context, state.session, state.turn, state.step,
                state.audit_events, state.emitter,
            )
            if added_tools:
                expanded_tools_this_step.extend(added_tools)
                try:
                    state.tools = state.context.tool_router.model_visible_tools()
                except Exception:
                    pass

        if expanded_tools_this_step:
            from agent.protocol.message import RuntimeContextMessage
            state.messages.append(RuntimeContextMessage(content=(
                "Tool catalog expanded the current turn with these newly visible tools: "
                + json.dumps(sorted(set(expanded_tools_this_step)), ensure_ascii=False)
                + ". Continue by calling the best matching specialized tool if it is needed."
            )).to_llm_message())

        return tool_stop_requested

    def _execute_single(self, state, tool_call, tc, events, step):
        """Execute a single tool call through the chain.

        Returns (result, should_skip, should_stop).
        """
        tid = tool_call.real_tool_id

        # 1. Pre-tool hook
        hook_allowed, hook_input, hook_reason = run_pre_tool_hook(state.session, tid, tool_call.arguments)
        if not hook_allowed:
            result = ToolResult(
                ok=False,
                summary=f"Tool {tid} blocked by pre-tool hook: {hook_reason}",
                errors=[f"hook_denied: {hook_reason}"],
            )
            events.tool_call_failed(tid, result.errors)
            events.record_tool_result(step, tid, False, result.summary)
            _append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, True, False  # skip

        if hook_input and isinstance(hook_input, dict):
            tool_call.arguments.update(hook_input)

        # 2. Permission check
        denied_result, denied, requires_approval, spec, risk_level = self._permission.run(
            state, tool_call, events, step)
        if denied:
            _append_tool_result(denied_result, tool_call, tc, state.all_tool_results, state.messages)
            return denied_result, True, False  # skip

        # 3. Approval gate (includes shell safety and risk analysis)
        from agent.runtime.permission_check import needs_approval as _needs_approval
        if _needs_approval(tid, spec, risk_level, requires_approval):
            # Run risk analysis first
            risk_result, risk_blocked, arg_source, arg_risk = self._risk.run(
                state, tool_call, spec, risk_level, events, step)
            if risk_blocked:
                _append_tool_result(risk_result, tool_call, tc, state.all_tool_results, state.messages)
                return risk_result, True, False  # skip

            # Run approval
            apr_result, apr_denied = self._approval.run(
                state, tool_call, spec, risk_level, requires_approval,
                arg_source, arg_risk, events, step)
            if apr_denied:
                _append_tool_result(apr_result, tool_call, tc, state.all_tool_results, state.messages)
                return apr_result, True, False  # skip

        # 4. Dispatch
        result = self._dispatch.run(state, tool_call, events, step)

        # 5. Post-tool hook
        post_stop = run_post_tool_hook(state.session, tid, result, state.turn)
        if post_stop:
            state.turn.warnings.append(f"post_tool_stop: {tid} stopped by hook")
            _append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, False, True  # stop

        # 6. Append result
        _append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
        return result, False, False


# ─── Helper functions (moved from loop.py) ─────────────────────────────


def _handle_unknown_tool(tc, llm_name, error, all_tool_results, messages,
                         audit_events, audit_trace, session, turn, step):
    """Handle an unknown / un-parseable tool call from the LLM."""
    error_name = getattr(error, '__class__', type(error)).__name__
    if audit_events:
        audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                          tool_id=llm_name, errors=[str(error)[:200]])
    if audit_trace:
        audit_trace.record_tool_result(turn.turn_id, step, llm_name, False, str(error)[:100])

    from agent.tools.router import ToolArgumentParseError
    is_arg_parse_error = isinstance(error, ToolArgumentParseError)

    summary = (
        f"Tool arguments not parseable: {str(error)[:160]}"
        if is_arg_parse_error
        else f"Tool not visible to model: {llm_name}"
    )
    all_tool_results.append({
        "tool_id": llm_name,
        "ok": False,
        "summary": summary[:200],
    })

    if is_arg_parse_error:
        hint = (
            "The arguments you sent for this tool are not a valid JSON object. "
            "Re-issue the tool call with `arguments` as a JSON object "
            "(e.g. {\"path\": \"/tmp/x\"}). Do not wrap the entire payload "
            "in quotes or include trailing prose."
        )
    else:
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


def _maybe_expand_tools_from_catalog_result(result, context, session, turn, step,
                                             audit_events, emitter) -> list:
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
