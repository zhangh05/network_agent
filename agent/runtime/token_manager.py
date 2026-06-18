"""Token manager — track usage, enforce limits, trigger compaction.

Extracted from loop.py to centralize token tracking and limit enforcement.
"""

from agent.runtime.token_tracker import estimate_messages, record_llm_call
from agent.runtime.context_compactor import should_compact, compact_messages


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
            compacted, meta = compact_messages(messages, keep_recent=6)
            if meta.get("compacted"):
                messages[:] = compacted
                turn.warnings.append(
                    f"context_compacted: {meta.get('compacted_message_count', 0)} messages "
                    f"compacted, tokens {meta.get('original_estimated_tokens', '?')} → "
                    f"{meta.get('compacted_estimated_tokens', '?')}"
                )
                if hasattr(turn, 'metadata'):
                    for k in ('compacted', 'compacted_message_count',
                              'original_estimated_tokens', 'compacted_estimated_tokens'):
                        if k in meta:
                            turn.metadata[k] = meta[k]
                # ── v2.1: ON_COMPACT hook ──
                try:
                    from agent.hooks_integration import get_hook_registry
                    from agent.hooks import HookEvent
                    registry = get_hook_registry()
                    if registry._hooks:
                        state = _build_hook_state(session, context)
                        registry.run_hooks(
                            HookEvent.ON_COMPACT,
                            state,
                            {"compacted_message_count": meta.get("compacted_message_count", 0),
                             "original_estimated_tokens": meta.get("original_estimated_tokens", 0),
                             "compacted_estimated_tokens": meta.get("compacted_estimated_tokens", 0)},
                            target="context",
                        )
                except Exception:
                    pass
                # Emit COMPACT stream event
                from agent.runtime.query_engine import StreamEvent
                emitter = getattr(context, '_stream_emitter', None)
                if emitter:
                    emitter.emit(StreamEvent.COMPACT, {
                        "compacted_message_count": meta.get("compacted_message_count", 0),
                        "original_estimated_tokens": meta.get("original_estimated_tokens", 0),
                        "compacted_estimated_tokens": meta.get("compacted_estimated_tokens", 0),
                    })

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
        record_llm_call(
            workspace_id=getattr(session, 'workspace_id', 'default') or 'default',
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
        "workspace_id": getattr(session, 'workspace_id', 'default') or 'default',
        "session_id": getattr(session, 'session_id', ''),
        "active_module": "",
        "context": {},
        "skill_results": {},
    }
