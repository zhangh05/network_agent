# agent/runtime/stages/context.py
"""ContextStage — build turn context, hydrate history, run prompt hook."""

from agent.runtime.context_builder import build_turn_context
from agent.runtime.context_history import DEFAULT_HISTORY_WINDOW, hydrate_history_from_store
from agent.runtime.hook_runner import run_user_prompt_submit_hook


class ContextStage:
    """Phase 1: build context, inject router, hydrate history, run prompt hook."""

    def run(self, state):
        # 1. Build context
        state.context = build_turn_context(state.session, state.turn, state.services)

        # 2. Fallback trace id
        from agent.runtime.query_engine import build_trace_id
        if not getattr(state.context, 'trace_id', None):
            state.context.trace_id = build_trace_id()
        state.context._stream_emitter = state.emitter

        # 3. Inject restricted tool router
        if state.restricted_tool_router is not None:
            state.context.tool_router = state.restricted_tool_router

        # 4. Hydrate history
        hydrate_history_from_store(state.session, state.context, k=DEFAULT_HISTORY_WINDOW)

        # 5. Emit context_built (via events bus)
        from agent.runtime.runtime_events import RuntimeEventBus
        events = RuntimeEventBus(state)
        events.context_built()

        # 6. User prompt submit hook
        if run_user_prompt_submit_hook(state.session, state.context):
            reason = state.context.metadata.get("user_prompt_block_reason", "user_prompt_submit_hook")
            state.turn.status = "blocked"
            state.turn.warnings.append(f"user_prompt_blocked: {reason}")
