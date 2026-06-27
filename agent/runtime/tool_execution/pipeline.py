# agent/runtime/tool_execution/pipeline.py
"""ToolExecutionPipeline — orchestrates tool chain via ActionExecutor.

v3: ActionExecutor is the PRIMARY tool execution path.
v3.8: Parallel dispatch for independent tool_calls + retry for transient errors.
Flow: pre_tool_hook → ActionPlanner.plan → ActionExecutor.execute (with retry)
      → action_result_to_tool_result → post_tool_hook → append_tool_result.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import time

from agent.protocol.tool_result import ToolResult
from agent.runtime.hook_runner import run_pre_tool_hook, run_post_tool_hook

from agent.runtime.tool_execution.result_stage import ResultStage, append_tool_result
from agent.runtime.tool_execution.unknown_tool_stage import handle_unknown_tool
from agent.runtime.tool_execution.catalog_stage import expand_tools_from_catalog_result

from agent.runtime.actions.planner import ActionPlanner
from agent.runtime.actions.executor import ActionExecutor
from agent.runtime.actions.result import action_result_to_tool_result
from agent.runtime.state.hooks import complete_runtime_state_after_actions

# v3.8: Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # exponential: 2s, 4s, 8s
RETRYABLE_ERRORS = (
    "timeout", "timed out", "rate_limit", "rate limit",
    "overload", "429", "503", "connection", "network",
    "broken pipe", "reset by peer",
)

# v3.8: Parallel execution config
MAX_PARALLEL_TOOLS = 4  # max concurrent tool executions


class ToolExecutionPipeline:
    """Orchestrate the full tool chain for a set of tool calls."""

    def __init__(self):
        self._result = ResultStage()
        self._action_planner = ActionPlanner()
        self._action_executor = ActionExecutor()

    def run(self, state, resp, events):
        """Execute all tool calls from the model response.

        v3.8: Independent tool_calls execute in parallel via ThreadPoolExecutor.
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

        # v3.8: Parallelize independent tool_calls
        tool_calls = resp.tool_calls
        if len(tool_calls) > 1:
            # Check if any tool_call depends on previous results
            independent = self._are_independent(tool_calls)
            if independent:
                return self._run_parallel(state, tool_calls, resp, events)

        # Sequential fallback
        for tc in tool_calls:
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

            # v3.9: SSE real-time push
            try:
                from agent.runtime.session_events import push_tool_start
                sid = getattr(state.session, 'session_id', '')
                if sid:
                    push_tool_start(sid, tool_call.real_tool_id, state.step)
            except Exception:
                pass

            result, should_skip, should_stop = self._execute_single_with_retry(
                state, tool_call, tc, events, state.step)

            # v3.9: SSE push tool result
            try:
                from agent.runtime.session_events import push_tool_done
                sid = getattr(state.session, 'session_id', '')
                if sid:
                    push_tool_done(sid, tool_call.real_tool_id,
                                   result.ok if result else False,
                                   result.summary if result else "")
            except Exception:
                pass

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

        self._finalize_expanded(state, expanded_tools_this_step)
        _complete_runtime_state(state)

        # v3.9: SSE push turn completed
        try:
            from agent.runtime.session_events import push_turn_done
            sid = getattr(state.session, 'session_id', '')
            turn_id = getattr(state.turn, 'turn_id', '')
            if sid:
                push_turn_done(sid, turn_id, resp.content if resp.content else "")
        except Exception:
            pass

        return tool_stop_requested

    def _are_independent(self, tool_calls) -> bool:
        """Check if tool_calls are independent of each other (safe to parallelize).
        
        Heuristic: if any tool writes to the same workspace file or same device,
        they are NOT independent.
        """
        seen_writes = set()
        for tc in tool_calls:
            name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")
            args = tc.arguments if isinstance(tc.arguments, dict) else {}
            key = f"{name}:{args.get('filepath', '')}:{args.get('host', '')}:{args.get('asset_id', '')}"
            if key in seen_writes:
                return False
            seen_writes.add(key)
        return True

    def _run_parallel(self, state, tool_calls, resp, events):
        """Execute independent tool calls in parallel."""
        expanded_tools = []
        tool_stop_requested = False
        
        # Prepare all tool_call objects first (build_tool_call must be serial)
        prepared = []
        blocked_parallel_tools = []
        for tc in tool_calls:
            llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")
            try:
                tool_call = state.context.tool_router.build_tool_call(tc)
                # v3.10: Manifest safety check for parallel execution
                tid = getattr(tool_call, 'real_tool_id', '')
                if tid:
                    try:
                        from tool_runtime.manifest_registry import get_manifest
                        m = get_manifest(tid)
                        if m:
                            unsafe_parallel = (
                                m.destructive or
                                m.side_effects not in ("none", "read") or
                                m.idempotency != "safe_to_retry"
                            )
                            if unsafe_parallel and len(tool_calls) > 1:
                                blocked_parallel_tools.append(
                                    f"{tid}: destructive={m.destructive}, side_effects={m.side_effects}, idempotency={m.idempotency}"
                                )
                                prepared.append((tc, None, llm_name,
                                    ValueError(f"Tool {tid} not allowed in parallel: unsafe for concurrent execution")))
                                continue
                    except Exception:
                        pass
                prepared.append((tc, tool_call, llm_name, None))
            except Exception as e:
                prepared.append((tc, None, llm_name, e))

        # If any tools blocked from parallel, warn but continue with remaining tools
        if blocked_parallel_tools:
            state.turn.warnings.extend(blocked_parallel_tools)
            # If all tools blocked, skip parallel entirely
            if len([p for p in prepared if p[3] is None and p[1] is not None]) == 0:
                _complete_runtime_state(state)
                return False

        def _exec_one(state_copy, tc, tool_call, llm_name, error):
            if error:
                handle_unknown_tool(tc, llm_name, error, [], state_copy.messages,
                    state_copy.audit_events, state_copy.audit_trace,
                    state_copy.session, state_copy.turn, state_copy.step)
                return None
            
            events.tool_call_started(tool_call.real_tool_id, state.step)
            events.record_tool_call(state.step, tool_call.real_tool_id, str(tool_call.arguments)[:100])
            
            result, should_skip, should_stop = self._execute_single_with_retry(
                state_copy, tool_call, tc, events, state.step)
            
            return {
                "result": result, "should_skip": should_skip,
                "should_stop": should_stop, "tool_call": tool_call, "tc": tc,
            }

        # Deep copy state for each thread to avoid race conditions
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TOOLS, len(prepared))) as executor:
            futures = []
            for tc, tool_call, llm_name, error in prepared:
                state_copy = copy.deepcopy(state)
                futures.append(executor.submit(_exec_one, state_copy, tc, tool_call, llm_name, error))

            for future in as_completed(futures):
                r = future.result()
                if r is None:
                    continue
                if r["should_stop"]:
                    tool_stop_requested = True
                if r["should_skip"]:
                    continue
                # v3.10: Merge parallel results back into main state
                if r.get("result"):
                    append_tool_result(
                        r["result"], r.get("tool_call"), r.get("tc"),
                        state.all_tool_results, state.messages,
                    )
                added = expand_tools_from_catalog_result(
                    r["result"], state.context, state.session, state.turn, state.step,
                    state.audit_events, state.emitter)
                if added:
                    expanded_tools.extend(added)

        self._finalize_expanded(state, expanded_tools)
        _complete_runtime_state(state)
        return tool_stop_requested

    def _finalize_expanded(self, state, expanded_tools):
        if expanded_tools:
            try:
                state.tools = state.context.tool_router.model_visible_tools()
            except Exception:
                pass
            from agent.protocol.message import RuntimeContextMessage
            state.messages.append(RuntimeContextMessage(content=(
                "Tool catalog expanded the current turn with these newly visible tools: "
                + json.dumps(sorted(set(expanded_tools)), ensure_ascii=False)
                + ". Continue by calling the best matching specialized tool if it is needed."
            )).to_llm_message())

    def _execute_single_with_retry(self, state, tool_call, tc, events, step):
        """Execute with retry for transient errors. v3.10: manifest-driven retry policy."""
        tid = tool_call.real_tool_id
        if not tid:
            tid = ""

        # v3.10: Check manifest for retry permission
        can_retry = False
        max_manifest_retries = 0
        try:
            from tool_runtime.manifest_registry import get_manifest
            m = get_manifest(tid)
            if m:
                can_retry = (m.idempotency == "safe_to_retry" and not m.destructive)
                if can_retry and m.retry_policy:
                    max_manifest_retries = getattr(m.retry_policy, 'max_attempts', 1) - 1
        except Exception:
            can_retry = False

        effective_max_retries = min(MAX_RETRIES, max_manifest_retries) if can_retry else 0

        for attempt in range(effective_max_retries + 1):
            result, should_skip, should_stop = self._execute_single(
                state, tool_call, tc, events, step)
            
            if not result.ok and attempt < effective_max_retries:
                error_str = str(result.errors).lower() if result.errors else ""
                if any(k in error_str for k in RETRYABLE_ERRORS):
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    events.record_tool_result(step, tid, False,
                        f"retry {attempt+1}/{effective_max_retries} in {wait:.0f}s")
                    time.sleep(wait)
                    continue
            return result, should_skip, should_stop
        return result, should_skip, should_stop

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

        # ── Secondary visibility validation (hard policy enforcement) ──
        # tid is already canonical (resolved by tool_router.build_tool_call).
        # If the planner failed and visible_tool_ids is empty,
        # the safe fallback allows ONLY baseline read tools.
        ctx = getattr(state, 'context', None)
        if ctx is not None:
            visible_ids = getattr(ctx, 'visible_tool_ids', None)

            # Degraded mode: planner or context builder failed,
            # fall back to the minimal baseline safe tool set.
            if not visible_ids:
                from agent.runtime.tool_planning.visibility import BASELINE_READ_TOOLS
                visible_ids = list(BASELINE_READ_TOOLS)
                ctx.metadata.setdefault("fallback_visible_tool_ids_used", True)

            if tid not in visible_ids:
                violation = {
                    "tool_id": tid,
                    "step": step,
                    "visible_tool_ids": list(visible_ids),
                    "fallback_used": ctx.metadata.get("fallback_visible_tool_ids_used", False),
                }
                result = ToolResult(
                    ok=False,
                    summary=f"Tool {tid} blocked: not in visible tool set for this turn",
                    errors=[f"visibility_violation: {tid} is not in visible_tool_ids"],
                )
                events.tool_call_failed(tid, result.errors)
                events.record_tool_result(step, tid, False, result.summary)
                append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
                # ── P0: visibility violation in three places ──
                # (1) tool_results — already in all_tool_results via append
                # (2) trace event — emit explicitly
                events.error("visibility_violation", str({k: violation[k] for k in ("tool_id", "step")}))
                # (3) run/decision metadata
                ctx.metadata.setdefault("visibility_violations", []).append(violation)
                return result, True, False

        call_id = tc.id if hasattr(tc, 'id') else tc.get("id", "")
        llm_name = tc.name if hasattr(tc, 'name') else tc.get("name", "unknown")
        turn_id = getattr(state.turn, 'turn_id', '')

        # v3.8: Dynamic breakpoint — pause before matching tool for debugging
        try:
            from agent.runtime.auto_checkpoint import should_break_before_tool
            if should_break_before_tool(tid):
                events.record_tool_result(step, tid, False, f"breakpoint_hit: {tid}")
                return ToolResult(
                    ok=False, summary=f"Breakpoint hit for {tid} — execution paused.",
                    errors=[f"dynamic_breakpoint: {tid}"],
                ), True, False
        except Exception:
            pass

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
            # If approval_pending, wait for the user to approve via popup (ApprovalStore).
            # The ApprovalGate already created the store record; we block here
            # until resolved (or timeout), then retry or fail definitively.
            if action_result.status == "approval_pending":
                result, stop_now, _ = self._wait_for_approval(
                    action_result, state, tool_call, tc, step, events,
                )
                if stop_now:
                    return result, stop_now, False

            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, True, False

        post_stop = run_post_tool_hook(state.session, tid, result, state.turn)
        if post_stop:
            state.turn.warnings.append(f"post_tool_stop: {tid} stopped by hook")
            append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
            return result, False, True

        append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
        return result, False, False

    def _wait_for_approval(self, action_result, state, tool_call, tc, step, events):
        """v3.10: Non-blocking interrupt — pass pending result through.
        Approval was already created by ApprovalStage via interrupt_before_tool."""
        result = action_result_to_tool_result(action_result)
        append_tool_result(result, tool_call, tc, state.all_tool_results, state.messages)
        return result, True, False  # stop this tool, marked as pending


def _complete_runtime_state(state) -> None:
    try:
        complete_runtime_state_after_actions(
            getattr(state, "context", None),
            session=getattr(state, "session", None),
        )
    except Exception:
        import logging
        _log = logging.getLogger(__name__)
        _log.warning("_complete_runtime_state failed", exc_info=True)
        ctx = getattr(state, "context", None)
        if ctx is not None:
            ctx.metadata.setdefault("runtime_state_warnings", []).append("post_action_state_update_failed")
