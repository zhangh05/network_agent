# agent/runtime/tool_execution/pipeline.py
"""ToolExecutionPipeline — orchestrates tool chain: pre_tool → permission → risk → approval → dispatch → post_tool → append."""

import json

from agent.protocol.message import ToolResultMessage
from agent.protocol.tool_result import ToolResult
from agent.runtime.hook_runner import run_pre_tool_hook, run_post_tool_hook
from agent.runtime.query_engine import StreamEvent

from agent.runtime.tool_execution.permission_stage import PermissionStage
from agent.runtime.tool_execution.risk_stage import RiskStage
from agent.runtime.tool_execution.approval_stage import ApprovalStage
from agent.runtime.tool_execution.dispatch_stage import DispatchStage
from agent.runtime.tool_execution.result_stage import ResultStage, append_tool_result
from agent.runtime.tool_execution.unknown_tool_stage import handle_unknown_tool
from agent.runtime.tool_execution.catalog_stage import expand_tools_from_catalog_result


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
                handle_unknown_tool(
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

            added_tools = expand_tools_from_catalog_result(
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
            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, True, False  # skip

        if hook_input and isinstance(hook_input, dict):
            tool_call.arguments.update(hook_input)

        # 2. Permission check
        denied_result, denied, requires_approval, spec, risk_level = self._permission.run(
            state, tool_call, events, step)
        if denied:
            append_tool_result(denied_result, tool_call, tc, state.all_tool_results, state.messages)
            return denied_result, True, False  # skip

        # 3. Approval gate (includes shell safety and risk analysis)
        from agent.runtime.permission_check import needs_approval as _needs_approval
        if _needs_approval(tid, spec, risk_level, requires_approval):
            # Run risk analysis first
            risk_result, risk_blocked, arg_source, arg_risk = self._risk.run(
                state, tool_call, spec, risk_level, events, step)
            if risk_blocked:
                append_tool_result(risk_result, tool_call, tc, state.all_tool_results, state.messages)
                return risk_result, True, False  # skip

            # Run approval
            apr_result, apr_denied = self._approval.run(
                state, tool_call, spec, risk_level, requires_approval,
                arg_source, arg_risk, events, step)
            if apr_denied:
                append_tool_result(apr_result, tool_call, tc, state.all_tool_results, state.messages)
                return apr_result, True, False  # skip

        # 4. Dispatch
        result = self._dispatch.run(state, tool_call, events, step)

        # 5. Post-tool hook
        post_stop = run_post_tool_hook(state.session, tid, result, state.turn)
        if post_stop:
            state.turn.warnings.append(f"post_tool_stop: {tid} stopped by hook")
            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, False, True  # stop

        # 6. Append result
        append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
        return result, False, False
