# agent/runtime/runner.py
"""TurnRunner — the core turn execution engine, stage-pipeline architecture.

Delegates phases to:
  - ContextStage      (agent.runtime.stages.context)
  - MessageStage      (agent.runtime.stages.messages)
  - ModelStage        (agent.runtime.stages.model)
  - ToolExecutionPipeline (agent.runtime.tool_execution.pipeline)
  - result_builder    (agent.runtime.result_builder)
  - RuntimeEventBus   (agent.runtime.runtime_events)
"""

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
)
from agent.runtime.tool_execution.output_policy import check_output_policy
from agent.runtime.result_builder import (
    build_success_result,
    build_error_result,
    build_partial_result,
    build_blocked_result,
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

        # ── Turn started ──
        events.turn_started(
            trace_id=fallback_trace_id,
            user_input=self.turn.op.user_input if self.turn.op else "",
        )
        self.turn.status = "running"

        # ── Context stage ──
        ContextStage().run(state)

        if not getattr(state.context, 'trace_id', None):
            state.context.trace_id = fallback_trace_id

        # ── Pre-turn hooks ──
        if run_pre_turn_hooks(self.session, self.turn, state.context):
            self.turn.status = "blocked"
            return build_blocked_result(state, "pre_turn_hook")

        # ── Messages stage ──
        MessageStage().run(state)

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

            # Model invocation
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
                tool_stop = pipeline.run(state, resp, events)

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
                events.assistant_message(len(state.final_response), reasoning_stripped)

            # Output policy check
            output_policy_ok = check_output_policy(state.final_response, self.turn)
            state.metadata["output_policy_ok"] = output_policy_ok

            PersistenceStage().append_final_messages(state)

            events.turn_completed()
            self.turn.status = "finished"
            self.turn.final_response = state.final_response
            events.final(state.final_response)

            # ── Finalization kernels (output/memory/observability/truth) ──
            try:
                from agent.runtime.state.hooks import _run_finalization_kernels
                if "runtime_state_snapshot" not in state.context.metadata:
                    from agent.runtime.state.snapshot import RuntimeStateSnapshotter
                    from agent.runtime.state.resolver import RuntimeStateResolver
                    runtime_state = RuntimeStateResolver().resolve(state.context)
                    RuntimeStateSnapshotter().snapshot(state.context, runtime_state)
                _run_finalization_kernels(state.context)
            except Exception:
                logger.warning("finalization_kernels_failed (success path)", exc_info=True)

            return build_success_result(state)

        # Max steps exceeded or tool stop — both use partial result path
        self.turn.status = "finished"
        self.turn.warnings.append(f"max_steps ({state.max_steps}) reached — partial result")
        events.turn_failed("max_steps exceeded")
        events.error("max_steps", f"已达到最大步数 ({state.max_steps})，返回部分结果")

        # ── Finalization kernels for partial/error paths ──
        from agent.runtime.state.hooks import _run_finalization_kernels
        if "runtime_state_snapshot" not in state.context.metadata:
            from agent.runtime.state.snapshot import RuntimeStateSnapshotter
            from agent.runtime.state.resolver import RuntimeStateResolver
            runtime_state = RuntimeStateResolver().resolve(state.context)
            RuntimeStateSnapshotter().snapshot(state.context, runtime_state)
        _run_finalization_kernels(state.context)

        return build_partial_result(state, "max_steps")
