# agent/runtime/stages/messages.py
"""MessageStage — build initial messages, apply manual compact, get tools."""

from agent.runtime.message_builder import build_initial_messages


class MessageStage:
    """Phase 2: build messages, apply compaction, enumerate visible tools."""

    def run(self, state):
        # 1. Build initial messages
        state.messages = build_initial_messages(state.context, state.services)

        # 2. Apply manual compact
        _apply_manual_compact(state.session, state.turn, state.messages)

        # 3. Get model-visible tools
        state.tools = []
        if state.context.tool_router:
            try:
                state.tools = state.context.tool_router.model_visible_tools()
            except Exception:
                pass


def _apply_manual_compact(session, turn, messages):
    """Apply manual compact flag from /compact command."""
    _sess_meta = getattr(session, 'metadata', None)
    if not isinstance(_sess_meta, dict):
        _sess_meta = {}
    manual_compact_requested = _sess_meta.get('manual_compact_requested', False)
    if not manual_compact_requested:
        try:
            from workspace.run_store import WS_ROOT as _wsr
            from workspace.atomic_io import safe_read_json
            from workspace.ids import validate_workspace_id, validate_session_id
            ws_id = validate_workspace_id(session.workspace_id) if session.workspace_id else "default"
            sess_id = validate_session_id(session.session_id)
            meta_path = _wsr / ws_id / "sessions" / sess_id / "meta.json"
            disk_meta = safe_read_json(meta_path, default={}) or {}
            if isinstance(disk_meta, dict):
                manual_compact_requested = bool(disk_meta.get('manual_compact_requested', False))
        except Exception:
            pass

    if not manual_compact_requested:
        return

    try:
        from agent.runtime.context_compactor import (
            compact_messages,
            CompactionStrategy,
            build_compaction_metric,
        )
        from agent.hooks import HookEvent

        original_message_count = len(messages)
        strategy = CompactionStrategy.FAST_EVICTION

        # PRE_COMPACT hook
        try:
            from agent.hooks_integration import get_hook_registry
            registry = get_hook_registry()
            state = {"session": session, "turn": turn}
            pre_outcome = registry.run_hooks(
                HookEvent.PRE_COMPACT,
                state,
                {
                    "strategy": strategy.value,
                    "trigger": "manual",
                    "threshold_pct": 0.0,
                    "original_messages": original_message_count,
                    "manual_compact": True,
                },
                target="context",
            )
            if pre_outcome.should_stop:
                turn.warnings.append("manual_compact_skipped: pre_compact_hook stopped")
                return
        except Exception:
            pass

        compacted, meta = compact_messages(
            messages,
            keep_recent=6,
            strategy=strategy,
            trigger="manual",
            threshold_pct=0.0,
        )
        if meta.get('compacted'):
            messages[:] = compacted
            if hasattr(session, 'metadata'):
                session.metadata['manual_compact_requested'] = False
                session.metadata['manual_compact_applied'] = True

            metric = build_compaction_metric(
                meta,
                strategy=strategy,
                trigger="manual",
                threshold_pct=0.0,
                original_messages=original_message_count,
            )
            metric_dict = metric.to_dict()

            if hasattr(turn, 'metadata'):
                for k, v in metric_dict.items():
                    turn.metadata[k] = v
                turn.metadata['reference_context_item_id'] = metric.reference_context_item_id

            try:
                from workspace.run_store import WS_ROOT as _wsr2
                from workspace.atomic_io import safe_read_json, atomic_write_json
                from workspace.ids import validate_workspace_id, validate_session_id
                ws_id2 = validate_workspace_id(session.workspace_id) if session.workspace_id else "default"
                sess_id2 = validate_session_id(session.session_id)
                meta_path2 = _wsr2 / ws_id2 / "sessions" / sess_id2 / "meta.json"
                disk_meta2 = safe_read_json(meta_path2, default={}) or {}
                if isinstance(disk_meta2, dict):
                    disk_meta2.pop('manual_compact_requested', None)
                    disk_meta2['manual_compact_applied'] = True
                    disk_meta2['last_compaction'] = metric_dict
                    disk_meta2['reference_context_item_id'] = metric.reference_context_item_id
                    atomic_write_json(meta_path2, disk_meta2)
            except Exception:
                pass

            # POST_COMPACT hook
            try:
                registry.run_hooks(
                    HookEvent.POST_COMPACT,
                    state,
                    metric_dict,
                    target="context",
                )
            except Exception:
                pass

            turn.warnings.append(
                f"manual_compact_applied[{strategy.value}]: "
                f"{meta.get('compacted_message_count')} msgs, "
                f"tokens {meta.get('original_estimated_tokens')} → "
                f"{meta.get('compacted_estimated_tokens')} "
                f"({metric.duration_ms}ms, ref={metric.reference_context_item_id or '-'})"
            )
    except Exception as e:
        turn.warnings.append(f"manual_compact_failed: {e}")
