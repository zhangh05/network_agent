# agent/runtime/runner.py
"""TurnRunner — the core turn execution engine, stage-pipeline architecture.

v3.10: Message trimming to prevent token explosion in long multi-step turns.

Delegates phases to:
  - ContextStage      (agent.runtime.stages.context)
  - MessageStage      (agent.runtime.stages.messages)
  - ModelStage        (agent.runtime.stages.model)
  - ToolExecutionPipeline (agent.runtime.tool_execution.pipeline)
  - result_builder    (agent.runtime.result_builder)
  - RuntimeEventBus   (agent.runtime.runtime_events)
"""

# v3.8: Message trimming constants
MAX_MESSAGE_TURNS = 12  # keep last N user+assistant+tool turn groups

import json
import logging

from agent.protocol.message import UserMessage, AssistantMessage, RuntimeContextMessage
from agent.runtime.result import AgentResult
from agent.runtime.turn_state import TurnRuntimeState
from agent.runtime.runtime_events import RuntimeEventBus
from agent.runtime.stages.context import ContextStage
from agent.runtime.stages.messages import MessageStage
from agent.runtime.stages.model import ModelStage, _ModelBlocked, _ProviderError
from agent.runtime.stages.persistence import PersistenceStage
from agent.runtime.tool_execution.pipeline import ToolExecutionPipeline
from agent.runtime.tool_execution.retry_policy import (
    detect_repeated_tool_failure,
    should_retry_for_required_tools,
    required_tool_retry_prompt,
    TurnRetryPolicy,
)
from agent.runtime.tool_execution.output_policy import check_output_policy
from agent.runtime.result_builder import (
    build_success_result,
    build_error_result,
    build_partial_result,
    build_blocked_result,
    _final_response_or_tool_summary,
)
from agent.runtime.hook_runner import run_pre_turn_hooks
from agent.runtime.token_manager import TokenLimitExceeded
from agent.runtime.query_engine import StreamEmitter, StreamEvent, classify_error, ErrorType, build_trace_id
from agent.runtime.tool_result_utils import enrich_metadata
from agent.runtime.tool_decision import build_tool_decision as _build_tool_decision

logger = logging.getLogger(__name__)


class TurnRunner:
    """Execute a single turn through the stage pipeline."""

    def __init__(self, session, turn, services=None, restricted_tool_router=None):
        self.session = session
        self.turn = turn
        self.services = services
        self.restricted_tool_router = restricted_tool_router

    def run(self) -> AgentResult:
        from agent.runtime.loop import _resolve_max_steps, MAX_STEPS

        # ── Build state ──
        audit_events = (self.services.audit_service["events"]
                        if self.services and hasattr(self.services, 'audit_service') and self.services.audit_service
                        else None)
        audit_trace = (self.services.audit_service["trace"]
                       if self.services and hasattr(self.services, 'audit_service') and self.services.audit_service
                       else None)
        emitter = StreamEmitter()
        fallback_trace_id = build_trace_id()

        state = TurnRuntimeState(
            session=self.session,
            turn=self.turn,
            services=self.services,
            restricted_tool_router=self.restricted_tool_router,
            emitter=emitter,
            audit_events=audit_events,
            audit_trace=audit_trace,
        )

        events = RuntimeEventBus(state)

        # ── v3.10: Durable TaskState ──
        ws_id = getattr(self.session, 'workspace_id', '') or ''
        sid = getattr(self.session, 'session_id', '')
        run_id = getattr(state.turn, 'turn_id', '')
        _save_mid = None  # mid-execution save function
        try:
            from agent.runtime.durable import TaskState, RuntimeStep, RuntimeEvent as RTEvent
            from agent.runtime.durable.store import save_task, append_event as _append_rt_event
            from agent.runtime.durable.control import checkpoint_task, create_checkpoint_from_state
            def _save_mid():
                try: save_task(_task)
                except Exception as e:
                    state.context.warnings.append(f"durable_task_creation_failed: {str(e)[:100]}")
            _task = TaskState.new(
                workspace_id=ws_id, session_id=sid, run_id=run_id,
                user_goal=self.turn.op.user_input if self.turn.op else "",
            )
            _task.update_status("running")
            _task_run_id = run_id
            # v3.10: Write task_id back to state so approval/callers can find it
            state.task_id = _task.task_id
            _append_rt_event(RTEvent(
                event_id=f"evt-{_task.task_id}-start",
                task_id=_task.task_id, workspace_id=ws_id, session_id=sid, run_id=run_id,
                type="task_started", status="ok",
                title="Task started", summary=_task.user_goal[:200],
            ))
            _ctx_step = _task.add_step(RuntimeStep(
                step_id=f"step-{_task.task_id}-ctx",
                task_id=_task.task_id, kind="message", title="Context built",
            ))
            _ctx_step.mark_started()
            _save_mid()
            # v3.10 Phase 3: checkpoint at task start
            checkpoint_task(_task.task_id, ws_id, reason="task_started")
        except Exception:
            _task = None
            _task_run_id = ""

        # ── Turn started ──
        events.turn_started(
            trace_id=fallback_trace_id,
            user_input=self.turn.op.user_input if self.turn.op else "",
        )
        self.turn.status = "running"

        # ── Context stage ──
        ContextStage().run(state)
        if self.turn.status == "blocked":
            if _task:
                try:
                    reason = state.context.metadata.get("user_prompt_block_reason", "user_prompt_submit_hook")
                    _ctx_step.mark_finished(ok=False, summary=f"Blocked: {reason}")
                    _task.update_status("failed")
                    _task.errors.append(f"blocked_by_user_prompt_submit: {reason}"[:200])
                    checkpoint_task(_task.task_id, ws_id, reason="user_prompt_blocked")
                    save_task(_task)
                except Exception as e:
                    state.context.warnings.append(f"durable_task_blocked_save_failed: {str(e)[:100]}")
            return build_blocked_result(
                state,
                state.context.metadata.get("user_prompt_block_reason", "user_prompt_submit_hook"),
                hook_event="user_prompt_submit",
            )

        # v3.10: mark context step done
        if _task:
            _ctx_step.mark_finished(ok=True, summary="Context built")
            _save_mid()
            checkpoint_task(_task.task_id, ws_id, reason="context_built")

        if not getattr(state.context, 'trace_id', None):
            state.context.trace_id = fallback_trace_id

        # ── Pre-turn hooks ──
        if run_pre_turn_hooks(self.session, self.turn, state.context):
            self.turn.status = "blocked"
            return build_blocked_result(state, "pre_turn_hook")

        # ── Messages stage ──
        MessageStage().run(state)

        # ── v3.3: Auto-checkpoint before agentic loop ──
        try:
            from agent.runtime.auto_checkpoint import apply_checkpoint_guard
            apply_checkpoint_guard(self.session, self.turn, 0, state.context)
        except Exception:
            pass

        # ── Resolve max steps ──
        _is_sub_agent_turn = bool(getattr(self.session, 'is_sub_agent', False))
        state.max_steps = _resolve_max_steps(
            session=self.session, turn=self.turn, is_sub_agent=_is_sub_agent_turn,
        )
        if state.max_steps != MAX_STEPS:
            self.turn.warnings.append(
                f"max_steps_override: {state.max_steps} (default={MAX_STEPS})"
            )

        # ── Agentic loop ──
        pipeline = ToolExecutionPipeline()
        model_stage = ModelStage()
        _tool_stop_requested = False

        while state.step < state.max_steps:
            state.step += 1

            # v3.8: Message trimming — keep last N user+assistant turns to prevent token explosion
            _trim_messages_if_needed(state)

            # Model invocation
            # v3.10: model step + checkpoint
            _model_step = None
            if _task:
                try:
                    _model_step = RuntimeStep(
                        step_id=f"step-{_task.task_id}-model-{state.step}",
                        task_id=_task.task_id, kind="model", title=f"Model call #{state.step}",
                    )
                    _task.add_step(_model_step)
                    _model_step.mark_started()
                    _save_mid()
                    checkpoint_task(_task.task_id, ws_id, reason=f"model_step_{state.step}")
                except Exception:
                    pass
            try:
                resp = model_stage.run(state, events)
            except TokenLimitExceeded as e:
                from agent.runtime.hook_runner import run_error_hook
                run_error_hook(self.session, "token_limit",
                               {"error": str(e), "estimated": e.estimated, "max_context": e.max_context},
                               state.context)
                events.error(ErrorType.TOKEN_LIMIT, f"Token limit exceeded: {str(e)}")
                self.turn.status = "failed"
                self.turn.warnings.append(f"token_limit_exceeded: {e}")
                events.turn_failed("token_limit_exceeded")
                # v3.10: persist on failure
                if _task:
                    try:
                        _task.update_status("failed")
                        _task.errors.append(str(e)[:200])
                        checkpoint_task(_task.task_id, ws_id, reason="token_limit_failure")
                        save_task(_task)
                    except Exception as e:
                        state.context.warnings.append(f"durable_task_creation_failed: {str(e)[:100]}")
                return build_error_result(
                    state,
                    "上下文超过模型限制，请压缩上下文或开启 compact 后重试。",
                    classify_error(e),
                    {"estimated_tokens": e.estimated, "max_context_tokens": e.max_context, "limit_ratio": e.ratio},
                    tool_decision={"needed": False, "reason": "Token limit exceeded before LLM could process."},
                    no_tool_reason="token_limit_exceeded: 上下文超过模型限制",
                )

            except _ModelBlocked:
                events.error("pre_model_blocked", "PRE_MODEL hook denied LLM call")
                self.turn.status = "failed"
                self.turn.warnings.append("pre_model_blocked: LLM call blocked by hook")
                return build_error_result(
                    state,
                    "请求被系统策略拒绝，请联系管理员检查 hook 配置。",
                    "permission_denied",
                    {"hook_event": "pre_model_blocked"},
                    tool_decision={"needed": False, "reason": "LLM call blocked by pre-model hook."},
                    no_tool_reason="blocked_by_hook: LLM 调用被 pre-model hook 阻止",
                )

            except _ProviderError as pe:
                e = pe.original
                error_str = str(e)[:200]
                is_timeout = "timeout" in error_str.lower() or "timed out" in error_str.lower()
                events.error(classify_error(e), error_str)
                events.turn_failed(error_str)
                self.turn.status = "failed"
                self.turn.errors.append(error_str)
                # v3.10: persist provider error
                if _task:
                    try:
                        _task.update_status("failed")
                        _task.errors.append(f"provider_error: {error_str[:180]}")
                        save_task(_task)
                    except Exception:
                        pass
                user_msg = ("LLM 服务请求超时，请稍后重试。" if is_timeout
                            else "LLM 服务暂不可用，请稍后重试。")
                try:
                    from agent.llm.config import record_recent_failure
                    record_recent_failure(f"llm_invoke_error: {error_str[:100]}",
                                          "provider_timeout" if is_timeout else "provider_error")
                except Exception as _cf_err:
                    logger.warning("record_recent_failure (sync path) failed: %s", _cf_err)
                return build_error_result(
                    state, user_msg, classify_error(e),
                    {"provider_error_type": "provider_timeout" if is_timeout else "provider_error",
                     "retryable": is_timeout},
                    tool_decision={"needed": False, "reason": "LLM provider error prevented tool selection."},
                    no_tool_reason="provider_error: LLM 服务不可用",
                )

            # Handle provider error in response
            if resp.error:
                provider_meta = resp.metadata or {}
                error_type = provider_meta.get("error_type", "provider_error")
                is_timeout = error_type == "provider_timeout"
                retryable = provider_meta.get("retryable", is_timeout)

                events.error(error_type, resp.error[:200])
                events.turn_failed(f"Provider error ({error_type}): {resp.error}")
                self.turn.status = "failed"
                self.turn.errors.append(resp.error)

                # v3.10: persist resp.error
                if _task:
                    try:
                        _task.update_status("failed")
                        _task.errors.append(f"provider_response_error: {resp.error[:180]}")
                        save_task(_task)
                    except Exception:
                        pass

                user_msg = ("LLM 服务请求超时，请稍后重试。系统已保留本轮事件记录。" if is_timeout
                            else f"LLM 服务暂不可用：{resp.error[:200]}")
                try:
                    from agent.llm.config import record_recent_failure
                    record_recent_failure(user_msg, "provider_timeout" if is_timeout else "provider_error")
                except Exception as _cf_err:
                    logger.warning("record_recent_failure (streaming path) failed: %s", _cf_err)
                return build_error_result(
                    state, user_msg, error_type,
                    {"provider_error_type": error_type, "retryable": retryable,
                     "provider_error_detail": provider_meta.get("error_detail", "")},
                    tool_decision={"needed": False, "reason": "Provider error."},
                    no_tool_reason="provider_error: LLM 服务异常",
                )

            # Handle tool calls
            if resp.has_tool_calls():
                # v3.10: mark model step + checkpoint
                if _model_step:
                    _model_step.mark_finished(ok=True, summary="Produced tool calls")
                    _save_mid()

                # v3.10: tool steps
                if _task:
                    for tc in resp.tool_calls:
                        try:
                            tname = tc.name if hasattr(tc, 'name') else str(tc)
                            _ts = _task.add_step(RuntimeStep(
                                step_id=f"step-{_task.task_id}-tool-{state.step}",
                                task_id=_task.task_id, kind="tool",
                                title=f"Tool: {tname[:40]}",
                            ))
                            _ts.mark_started()
                            _save_mid()
                            checkpoint_task(_task.task_id, ws_id, reason="tool_start")
                        except Exception:
                            pass

                tool_stop = pipeline.run(state, resp, events)

                # v3.10: mark tool steps done
                if _task:
                    for ts in _task.steps:
                        if ts.kind == "tool" and ts.status == "running":
                            ts.mark_finished(ok=True, summary="Tool completed")
                    _save_mid()

                if tool_stop:
                    _tool_stop_requested = True
                    state.final_response = "Tool execution was stopped by a post-tool hook."
                    break

                # Repeated tool failure detection
                repeated_failure = detect_repeated_tool_failure(state.all_tool_results)
                if repeated_failure:
                    tool_id = repeated_failure.get("tool_id", "unknown")
                    summary = repeated_failure.get("summary") or "工具连续返回相同错误。"
                    message = f"任务已停止：{tool_id} 连续执行失败。{summary}"
                    self.turn.status = "failed"
                    self.turn.warnings.append(f"repeated_tool_failure: {tool_id}")
                    events.error("repeated_tool_failure", message)
                    return build_error_result(
                        state, message, ErrorType.TOOL_ERROR,
                        {"terminal_reason": "repeated_tool_failure", "steps": state.step},
                        tool_decision=_build_tool_decision(state.all_tool_results, state.context),
                    )

                continue

            # LLM returned content (final answer)
            # Required tool retry (only on empty content, step 1)
            if not resp.content and should_retry_for_required_tools(state.context, state.all_tool_results, state.step):
                state.messages.append(RuntimeContextMessage(
                    content=required_tool_retry_prompt(state.context)
                ).to_llm_message())
                state.context.metadata["required_tool_retry_used"] = True
                events.model_retry_required_tool(state.step)
                continue

            if not _tool_stop_requested:
                from agent.llm.runtime import sanitize_provider_output
                state.final_response, reasoning_stripped = sanitize_provider_output(resp.content)
                state.final_response = _final_response_or_tool_summary(
                    state.final_response,
                    state.all_tool_results,
                )
                events.assistant_message(len(state.final_response), reasoning_stripped)

            # Output policy check
            output_policy_ok = check_output_policy(state.final_response, self.turn)
            state.metadata["output_policy_ok"] = output_policy_ok

            PersistenceStage().append_final_messages(state)

            events.turn_completed()
            self.turn.status = "finished"
            self.turn.final_response = state.final_response
            events.final(state.final_response)

            # v3.10: final step + checkpoint + persist
            if _task:
                try:
                    _task.add_step(RuntimeStep(
                        step_id=f"step-{_task.task_id}-final", task_id=_task.task_id,
                        kind="final", title="Answer delivered",
                        summary=state.final_response[:200],
                    )).mark_finished(ok=True, summary=state.final_response[:200])
                    _task.update_status("succeeded")
                    _append_rt_event(RTEvent(
                        event_id=f"evt-{_task.task_id}-done",
                        task_id=_task.task_id, workspace_id=ws_id, session_id=sid, run_id=_task_run_id,
                        type="task_finished", status="succeeded",
                        title="Task finished", summary=state.final_response[:200],
                    ))
                    checkpoint_task(_task.task_id, ws_id, reason="task_finished")
                    save_task(_task)
                except Exception:
                    pass

            # v3.10: Build trajectory + eval after successful turn
            _build_and_eval_trajectory(_task, ws_id, state)

            # Record tool co-occurrence graph after successful turn
            _record_tool_graph(state)

            return build_success_result(state)

        # Max steps exceeded or tool stop — both use partial result path
        self.turn.status = "finished"
        self.turn.warnings.append(f"max_steps ({state.max_steps}) reached — partial result")
        events.turn_failed("max_steps exceeded")
        events.error("max_steps", f"已达到最大步数 ({state.max_steps})，返回部分结果")

        return build_partial_result(state, "max_steps")


def _record_tool_graph(state) -> None:
    """Record tool co-occurrence data from the completed turn."""
    try:
        tool_ids = [tc.get("tool_id", "") for tc in (state.all_tool_results or []) if tc.get("ok")]
        if tool_ids:
            from agent.runtime.tool_planning.graph import record_tool_sequence
            record_tool_sequence(tool_ids)
    except Exception:
        pass


def _trim_messages_if_needed(state) -> None:
    """Trim old messages to prevent token explosion. Keeps last MAX_MESSAGE_TURNS turn groups.
    
    v3.8: System message + last N user/assistant/tool groups preserved.
    """
    if not hasattr(state, 'messages') or len(state.messages) <= MAX_MESSAGE_TURNS * 3:
        return
    
    # Keep system message + last N*3 messages (user+assistant+tool per turn)
    system_msgs = [m for m in state.messages if _message_role(m) == "system"]
    non_system = [m for m in state.messages if _message_role(m) != "system"]
    
    if len(non_system) > MAX_MESSAGE_TURNS * 3:
        trimmed = non_system[-(MAX_MESSAGE_TURNS * 3):]
        state.messages = system_msgs + trimmed
        from agent.protocol.message import RuntimeContextMessage
        state.messages.append(RuntimeContextMessage(content=(
            f"Earlier messages trimmed to last {MAX_MESSAGE_TURNS} turns to stay within context window."
        )).to_llm_message())


def _message_role(message) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


# ── v3.10: Trajectory build + eval hooked into turn completion ──

def _build_and_eval_trajectory(task, ws_id: str, state) -> None:
    """Build trajectory from task state and evaluate. Writes issues back to TaskState."""
    try:
        from agent.runtime.durable.trajectory import build_trajectory, evaluate_trajectory, persist_trajectory
        traj = build_trajectory(task.task_id, ws_id)
        if not traj:
            return
        # Convert to dict
        traj_dict = traj.to_dict() if hasattr(traj, 'to_dict') else {}
        persist_trajectory(traj)
        score = evaluate_trajectory(traj_dict)
        if isinstance(score, dict) and score.get("issues"):
            for issue in score["issues"]:
                rule = issue.get("rule", "") if isinstance(issue, dict) else str(issue)
                detail = issue.get("detail", "") if isinstance(issue, dict) else ""
                task.warnings = (task.warnings or []) + [f"trajectory: {rule}: {detail}"]
            task.tool_results.append({
                "__trajectory_score__": score.get("score", 0),
                "__trajectory_issues__": [i.get("rule","") if isinstance(i,dict) else str(i) for i in score.get("issues",[])],
            })
        if state and hasattr(state, 'context') and score.get("issues"):
            ctx = getattr(state, 'context', None)
            if ctx and hasattr(ctx, 'warnings'):
                ctx.warnings.append(
                    f"Trajectory eval: score={score.get('score',0)} issues={len(score.get('issues',[]))}"
                )
    except Exception:
        pass  # best-effort: trajectory eval is non-blocking
