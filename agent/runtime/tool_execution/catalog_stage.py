# agent/runtime/tool_execution/catalog_stage.py
"""Expand per-turn visible tools from a successful catalog search result."""

from agent.runtime.query_engine import StreamEvent


def expand_tools_from_catalog_result(result, context, session, turn, step,
                                     audit_events, emitter) -> list:
    """Expand per-turn visible tools from a successful catalog search result."""
    if not result or getattr(result, "tool_id", "") != "tool.catalog.search" or not getattr(result, "ok", False):
        return []
    expansion = {}
    metadata = getattr(result, "metadata", {}) or {}
    if isinstance(metadata.get("tool_catalog_expansion"), dict):
        expansion = metadata["tool_catalog_expansion"]
    data = getattr(result, "data", {}) or {}
    raw = getattr(result, "raw", {}) or {}
    load_ids = (
        expansion.get("load_tool_ids")
        or data.get("load_tool_ids")
        or raw.get("load_tool_ids")
        or []
    )
    if not load_ids or not getattr(context, "tool_router", None):
        return []
    try:
        added = context.tool_router.expand_dynamic_visibility(load_ids)
    except Exception as exc:
        if hasattr(turn, "warnings"):
            turn.warnings.append(f"tool_catalog_expand_failed: {str(exc)[:120]}")
        return []
    if not added:
        return []
    visible = sorted(set(getattr(context, "visible_tool_ids", []) or []) | set(added))
    context.visible_tool_ids = visible
    context.metadata["visible_tools"] = visible
    context.metadata.setdefault("dynamic_tool_expansions", []).append({
        "step": step,
        "query": expansion.get("query", ""),
        "added_tool_ids": added,
    })
    try:
        emitter.emit(StreamEvent.TOOL_RESULT, {
            "tool_id": "tool.catalog.search",
            "ok": True,
            "summary": f"\u5de5\u5177\u76ee\u5f55\u5df2\u8ffd\u52a0 {len(added)} \u4e2a\u5de5\u5177\u5230\u5f53\u524d\u56de\u5408\u3002",
            "added_tool_ids": added,
        })
    except Exception:
        pass
    if audit_events:
        audit_events.emit(
            "tool_catalog_expanded",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            step=step,
            added_tool_ids=added,
        )
    return added
