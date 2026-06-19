# agent/runtime/tool_execution/pipeline.py
"""ToolExecutionPipeline — orchestrates tool chain via ActionExecutor.

v3: ActionExecutor is the PRIMARY tool execution path.
Flow: pre_tool_hook → ActionPlanner.plan → ActionExecutor.execute
      → action_result_to_tool_result → post_tool_hook → append_tool_result.
"""

import json

from agent.protocol.tool_result import ToolResult
from agent.runtime.hook_runner import run_pre_tool_hook, run_post_tool_hook

from agent.runtime.tool_execution.result_stage import ResultStage, append_tool_result
from agent.runtime.tool_execution.unknown_tool_stage import handle_unknown_tool
from agent.runtime.tool_execution.catalog_stage import expand_tools_from_catalog_result

from agent.runtime.actions.planner import ActionPlanner
from agent.runtime.actions.executor import ActionExecutor
from agent.runtime.actions.result import action_result_to_tool_result
from agent.runtime.state.hooks import complete_runtime_state_after_actions


class ToolExecutionPipeline:
    """Orchestrate the full tool chain for a set of tool calls."""

    def __init__(self):
        self._result = ResultStage()
        self._action_planner = ActionPlanner()
        self._action_executor = ActionExecutor()

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

        _complete_runtime_state(state)
        return tool_stop_requested

    def _execute_single(self, state, tool_call, tc, events, step):
        """Execute a single tool call through ActionExecutor.

        Returns (result, should_skip, should_stop).
        """
        tid = tool_call.real_tool_id

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
            return result, True, False

        if hook_input and isinstance(hook_input, dict):
            tool_call.arguments.update(hook_input)

        call_id = tc.id if hasattr(tc, 'id') else tc.get("id", "")
        llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")
        turn_id = getattr(state.turn, 'turn_id', '')
        action_plan = self._action_planner.plan(
            tool_call_id=call_id,
            tool_name=llm_name,
            tool_id=tid,
            arguments=dict(tool_call.arguments),
            turn_id=turn_id,
            raw_call=tc,
            context=getattr(state, 'context', None),
        )

        action_result = self._action_executor.execute(
            action_plan,
            tool_call=tool_call,
            ctx=getattr(state, 'context', None),
            state=state,
            events=events,
            step=step,
        )

        result = action_result_to_tool_result(action_result)

        if action_result.status in ("blocked", "approval_pending"):
            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, True, False

        post_stop = run_post_tool_hook(state.session, tid, result, state.turn)
        if post_stop:
            state.turn.warnings.append(f"post_tool_stop: {tid} stopped by hook")
            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, False, True

        append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
        return result, False, False


def _complete_runtime_state(state) -> None:
    try:
        complete_runtime_state_after_actions(
            getattr(state, "context", None),
            session=getattr(state, "session", None),
        )
    except Exception:
        ctx = getattr(state, "context", None)
        if ctx is not None:
            ctx.metadata.setdefault("runtime_state_warnings", []).append("post_action_state_update_failed")
