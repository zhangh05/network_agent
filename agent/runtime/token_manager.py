"""Token manager — track usage, enforce limits, trigger compaction.

Extracted from loop.py to centralize token tracking and limit enforcement.

v3.1.1: CompactionStrategy + structured metrics + PRE/POST_COMPACT hooks
"""

from agent.runtime.token_tracker import estimate_messages, record_llm_call
from agent.runtime.context_compactor import (
    should_compact,
    compact_messages,
    CompactionStrategy,
    CompactionMetric,
    build_compaction_metric,
)


class TokenLimitExceeded(Exception):
    def __init__(self, estimated: int, max_context: int, ratio: float):
        self.estimated = estimated
        self.max_context = max_context
        self.ratio = ratio
        super().__init__(f"Context tokens ({estimated}) exceed 90% of model limit ({max_context}) at ratio {ratio}")


def check_token_limit(messages, context, session, turn, step):
    """Phase 2: try compact first, then raise TokenLimitExceeded if still over 90%."""
    if not isinstance(messages, list):
        return
    try:
        max_context = int(getattr(context, 'model_config', {}).get('max_context_tokens', 128000) or 128000)

        # ── Phase 2: try compact before hard reject ──
        if should_compact(messages, max_context, threshold=0.75):
            from agent.hooks_integration import get_hook_registry
            from agent.hooks import HookEvent

            strategy = CompactionStrategy.FAST_EVICTION
            original_message_count = len(messages)

            # ── PRE_COMPACT hook (Codex pattern): can stop compaction ──
            registry = get_hook_registry()
            state = _build_hook_state(session, context)
            pre_outcome = registry.run_hooks(
                HookEvent.PRE_COMPACT,
                state,
                {
                    "strategy": strategy.value,
                    "trigger": "auto",
                    "threshold_pct": 75.0,
                    "original_messages": original_message_count,
                    "max_context_tokens": max_context,
                },
                target="context",
            )
            if pre_outcome.should_stop:
                turn.warnings.append("compaction_skipped: pre_compact_hook stopped")
                return

            compacted, meta = compact_messages(
                messages,
                keep_recent=15,
                strategy=strategy,
                trigger="auto",
                threshold_pct=75.0,
            )

            if meta.get("compacted"):
                messages[:] = compacted

                # ── Build structured metric ──
                metric = build_compaction_metric(
                    meta,
                    strategy=strategy,
                    trigger="auto",
                    threshold_pct=75.0,
                    original_messages=original_message_count,
                )
                metric_dict = metric.to_dict()

                turn.warnings.append(
                    f"context_compacted[{strategy.value}]: "
                    f"{meta.get('compacted_message_count', 0)} msgs, "
                    f"tokens {meta.get('original_estimated_tokens', '?')} → "
                    f"{meta.get('compacted_estimated_tokens', '?')} "
                    f"({metric.duration_ms}ms, ref={metric.reference_context_item_id or '-'})"
                )

                # Persist on turn metadata
                if hasattr(turn, 'metadata'):
                    for k, v in metric_dict.items():
                        turn.metadata[k] = v
                    # Reference context item lives at top-level for easy access
                    turn.metadata['reference_context_item_id'] = metric.reference_context_item_id

                # ── POST_COMPACT hook (Codex pattern) ──
                try:
                    post_outcome = registry.run_hooks(
                        HookEvent.POST_COMPACT,
                        state,
                        metric_dict,
                        target="context",
                    )
                    if post_outcome.should_stop:
                        turn.warnings.append("compaction_post_hook_signaled_stop")
                except Exception:
                    pass
                # Emit COMPACT stream event with full metric
                from agent.runtime.query_engine import StreamEvent
                emitter = getattr(context, '_stream_emitter', None)
                if emitter:
                    emitter.emit(StreamEvent.COMPACT, metric_dict)

        # ── Hard limit after compact ──
        estimated = estimate_messages(messages)
        if estimated > max_context * 0.9:
            raise TokenLimitExceeded(
                estimated=estimated,
                max_context=max_context,
                ratio=round(estimated / max_context, 2),
            )
    except TokenLimitExceeded:
        raise
    except Exception:
        pass


def track_llm_usage(session, turn, resp, messages, context, step):
    """Record token usage after each LLM call."""
    try:
        input_est = estimate_messages(messages)
        output_est = estimate_messages([resp.content]) if resp.content else 0
        model = getattr(context, 'model_config', {}).get('model', '') or ''
        provider = getattr(context, 'model_config', {}).get('provider', '') or ''
        ws_id = getattr(session, 'workspace_id', '') or ''
        if not ws_id:
            return
        record_llm_call(
            workspace_id=ws_id,
            session_id=getattr(session, 'session_id', ''),
            run_id=getattr(turn, 'turn_id', ''),
            turn_id=getattr(turn, 'turn_id', ''),
            provider=provider,
            model=model,
            input_tokens=input_est,
            output_tokens=output_est,
        )
    except Exception:
        pass


def _build_hook_state(session, context=None):
    """Build a minimal state dict for hook integration."""
    return {
        "intent": "assistant_chat",
        "workspace_id": getattr(session, 'workspace_id', '') or '',
        "session_id": getattr(session, 'session_id', ''),
        "active_module": "",
        "context": {},
        "skill_results": {},
    }
