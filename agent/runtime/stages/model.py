# agent/runtime/stages/model.py
"""ModelStage — invoke LLM with pre/post hooks, token checks, usage tracking."""

import logging

from agent.runtime.token_manager import check_token_limit, track_llm_usage, TokenLimitExceeded
from agent.runtime.hook_runner import (
    run_pre_model_hook, run_post_model_hook, run_error_hook,
)
from agent.runtime.query_engine import StreamEvent, classify_error, ErrorType
from agent.llm.runtime import invoke_llm

logger = logging.getLogger(__name__)


class ModelStage:
    """Phase 3: check tokens, run pre-model hook, call LLM, run post-model hook."""

    def run(self, state, events):
        """Run the model invocation pipeline.

        Returns the LLMResponse on success.
        Raises _ModelBlocked, _TokenLimitError, or _ProviderError on failure.
        """
        try:
            check_token_limit(state.messages, state.context, state.session, state.turn, state.step)

            if run_pre_model_hook(state.session, state.messages, state.tools, state.context, state.step):
                raise _ModelBlocked("PRE_MODEL hook denied LLM call")

            events.model_started(state.step, len(state.messages), len(state.tools))

            resp = invoke_llm(
                task="assistant_chat",
                messages=state.messages,
                tools=state.tools,
                safe_context=state.context.safe_context,
                user_input=state.context.user_input,
            )

            modified = run_post_model_hook(state.session, resp, state.context, state.step)
            if modified:
                resp.content = modified

        except TokenLimitExceeded:
            raise
        except _ModelBlocked:
            raise
        except Exception as e:
            # Provider error — run error hook then re-raise wrapped
            run_error_hook(state.session, "llm_invoke_error", {"error": str(e)[:200]}, state.context)
            raise _ProviderError(e) from e

        # Audit and track
        events.model_completed(
            state.step,
            has_content=bool(resp.content),
            has_tool_calls=resp.has_tool_calls(),
            finish_reason=getattr(resp, 'finish_reason', ''),
        )
        state.context.metadata.setdefault("model_responses", []).append({
            "step": state.step,
            "has_content": bool(resp.content),
            "has_tool_calls": resp.has_tool_calls(),
            "finish_reason": getattr(resp, "finish_reason", ""),
            "tool_call_count": len(getattr(resp, "tool_calls", []) or []),
        })

        track_llm_usage(state.session, state.turn, resp, state.messages, state.context, state.step)

        return resp


class _ModelBlocked(Exception):
    """Raised when a pre-model hook blocks the LLM call."""
    pass


class _ProviderError(Exception):
    """Wraps an LLM provider exception for the runner to handle."""
    def __init__(self, original):
        self.original = original
        super().__init__(str(original))
