"""Tool result utilities — standardize, project, and format tool call results.

Extracted from loop.py to separate tool result formatting from the agentic loop.
"""

import json

from agent.protocol.tool_result import ToolResult


def to_standard_tool_call(call_id: str, tool_id: str, result) -> dict:
    """Build a v0.8.2 standard tool_call dict from any handler result.

    The result can be a ToolResult instance, a handler dict, or any
    object exposing attributes.
    """
    if isinstance(result, ToolResult):
        tr = result
        if not tr.call_id:
            tr.call_id = call_id
        if not tr.tool_id:
            tr.tool_id = tool_id
        metadata = dict(tr.metadata or {})
        metadata.update(_tool_namespace_metadata(tr.tool_id))
        return {
            "call_id": tr.call_id,
            "tool_id": tr.tool_id,
            "ok": tr.ok,
            "summary": tr.summary,
            "result": _safe_tool_call_result_data(tr),
            "artifacts": list(tr.artifacts or []),
            "source_count": tr.source_count,
            "manual_review_count": tr.manual_review_count,
            "errors": list(tr.errors or []),
            "warnings": list(tr.warnings or []),
            "metadata": metadata,
        }

    # Dict-like result
    if isinstance(result, dict):
        tr = ToolResult.from_handler_dict(tool_id=tool_id, call_id=call_id, d=result)
    else:
        tr = ToolResult(
            call_id=call_id,
            tool_id=tool_id,
            ok=bool(getattr(result, 'ok', False)),
            summary=str(getattr(result, 'summary', str(result))[:500]),
            artifacts=list(getattr(result, 'artifacts', []) or []),
            source_count=getattr(result, 'source_count', None),
            manual_review_count=getattr(result, 'manual_review_count', None),
            errors=list(getattr(result, 'errors', []) or []),
            warnings=list(getattr(result, 'warnings', []) or []),
            metadata=dict(getattr(result, 'metadata', {}) or {}),
            data=dict(getattr(result, 'data', {}) or {}),
        )

    metadata = dict(tr.metadata or {})
    metadata.update(_tool_namespace_metadata(tr.tool_id))
    return {
        "call_id": tr.call_id,
        "tool_id": tr.tool_id,
        "ok": tr.ok,
        "summary": tr.summary,
        "artifacts": list(tr.artifacts or []),
        "source_count": tr.source_count,
        "manual_review_count": tr.manual_review_count,
        "errors": list(tr.errors or []),
        "warnings": list(tr.warnings or []),
        "metadata": metadata,
    }


def _tool_namespace_metadata(tool_id: str) -> dict:
    try:
        from core.tools.tool_namespace import get_namespace_entry
        entry = get_namespace_entry(tool_id)
        return entry.metadata()
    except Exception:
        return {}


def enrich_metadata(metadata: dict, context) -> dict:
    """Inject selected_skills / visible_tools from TurnContext into metadata."""
    if context and getattr(context, "metadata", None):
        for k in (
            "selected_skills", "visible_tools",
            "memory_hits_count", "knowledge_hits_count",
        ):
            if k in context.metadata and k not in metadata:
                metadata[k] = context.metadata[k]
    safe_context = getattr(context, "safe_context", None) or {}
    if isinstance(safe_context, dict):
        sources = safe_context.get("context_sources") or []
        citations = safe_context.get("citations") or []
        if sources and "context_sources" not in metadata:
            metadata["context_sources"] = list(sources)[:8]
            metadata["source_summary"] = [
                {
                    "source_id": s.get("source_id", ""),
                    "title": s.get("title", ""),
                    "snippet": s.get("snippet", ""),
                    "score": s.get("score", 0),
                    "citation_id": s.get("citation_id", ""),
                    "evidence_type": s.get("evidence_type", "knowledge"),
                }
                for s in list(sources)[:8]
            ]
            metadata["source_count"] = len(sources)
        if citations and "citations" not in metadata:
            metadata["citations"] = list(citations)[:8]
        diagnostics = safe_context.get("retrieval_diagnostics") or {}
        if diagnostics and "retrieval_diagnostics" not in metadata:
            metadata["retrieval_diagnostics"] = diagnostics
        # v3.0.0+: also surface hit counts from safe_context itself if the
        # runtime context builder didn't populate ctx.metadata (defensive).
        for k in ("memory_hits_count", "knowledge_hits_count"):
            if k not in metadata:
                arr = safe_context.get(k.replace("_count", "s")) or []
                if isinstance(arr, list):
                    metadata[k] = len(arr)
    return metadata


def build_tool_message_payload(result) -> dict:
    """Project a ToolResult into the safe payload the LLM sees next."""
    summary = _safe_get(result, "summary", "") or ""
    if not summary:
        summary = _auto_summary(result)
    payload = {
        "ok": bool(_safe_get(result, "ok", False)),
        "summary": _safe_prompt_text(summary, 1200),
    }
    for key in ("source_count", "manual_review_count"):
        value = _safe_get(result, key, None)
        if value is not None:
            payload[key] = value

    errors = _safe_get(result, "errors", []) or []
    warnings = _safe_get(result, "warnings", []) or []
    if errors:
        payload["errors"] = [_safe_prompt_text(e, 240) for e in list(errors)[:3]]
    if warnings:
        payload["warnings"] = [_safe_prompt_text(w, 240) for w in list(warnings)[:3]]

    artifacts = _safe_get(result, "artifacts", []) or []
    if artifacts:
        payload["artifact_count"] = len(artifacts)
        payload["artifacts"] = [
            {
                "artifact_id": a.get("artifact_id", ""),
                "artifact_type": a.get("artifact_type", ""),
                "title": _safe_prompt_text(a.get("title", ""), 160),
            }
            for a in list(artifacts)[:3]
            if isinstance(a, dict)
        ]

    for source_key in ("source_summary",):
        value = _safe_get(result, source_key, None)
        if value:
            payload[source_key] = _safe_tool_value(value)

    raw = _safe_get(result, "raw", {}) or {}
    data = _safe_get(result, "data", {}) or {}
    if isinstance(data, dict):
        _merge_llm_safe_tool_fields(payload, data)
    if isinstance(raw, dict):
        _merge_llm_safe_tool_fields(payload, raw)
    return payload


def _merge_llm_safe_tool_fields(payload: dict, source: dict) -> None:
    """Merge fields from source (data/raw) into payload, skipping forbidden keys."""
    for key, value in source.items():
        if _is_forbidden_prompt_key(str(key)):
            continue
        if value in (None, "", [], {}):
            continue
        target_key = key
        if key in payload and key not in ("ok",):
            target_key = f"result_{key}"
        payload[target_key] = _safe_tool_value(value, key_hint=target_key)


_OUTPUT_TEXT_KEYS = {
    "stdout", "stderr", "output", "text", "content", "preview",
    "result_stdout", "result_stderr", "result_output", "result_text",
    "result_content", "results", "items", "chunks", "hits",
}


def _safe_tool_value(value, *, max_text: int = 8000, key_hint: str = ""):
    key_lower = str(key_hint or "").lower()
    if key_lower in _OUTPUT_TEXT_KEYS or key_lower.endswith(("_stdout", "_stderr", "_output")):
        max_text = max(max_text, 12000)
    if isinstance(value, dict):
        return {
            str(k): _safe_tool_value(v, max_text=4000, key_hint=str(k))
            for k, v in list(value.items())[:20]
            if not _is_forbidden_prompt_key(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_tool_value(v, max_text=4000, key_hint=key_hint) for v in list(value)[:30]]
    return _safe_prompt_text(value, max_text)


def _safe_prompt_text(value, max_text: int) -> str:
    text = str(value)
    if len(text) <= max_text:
        return text
    if max_text < 1200:
        return text[:max_text] + f"...[truncated, {len(text)} chars total]"
    marker = f"\n...[truncated middle, {len(text)} chars total]...\n"
    keep = max(0, max_text - len(marker))
    head = max(keep * 2 // 3, keep // 2)
    tail = keep - head
    return text[:head] + marker + text[-tail:]


def _safe_tool_call_result_data(tr: ToolResult) -> dict:
    """Extract safe content/data for frontend display (not LLM context)."""
    result: dict = {}
    if tr.content:
        result["content"] = str(tr.content)[:5000]
    data = dict(tr.data or {})
    raw = dict(tr.raw or {})
    # Merge data/raw keys that are safe for display
    for k, v in {**raw, **data}.items():
        if _is_forbidden_prompt_key(str(k)):
            continue
        if isinstance(v, str):
            result[k] = v[:2000]
        elif isinstance(v, (int, float, bool)):
            result[k] = v
        elif isinstance(v, (list, tuple)):
            result[k] = f"[{len(v)} items]"
        elif isinstance(v, dict):
            result[k] = f"{{{len(v)} keys}}"
        if len(result) > 15:
            break
    return result


def _auto_summary(result) -> str:
    """Generate a summary when the handler didn't provide one."""
    data = _safe_get(result, "data", {}) or {}
    raw = _safe_get(result, "raw", {}) or {}
    for key in ("count", "rows", "columns", "total", "valid", "exists",
                "size", "archived", "deleted", "indexed", "reindexed",
                "status", "classification"):
        val = _safe_get(result, key, None) or data.get(key) or raw.get(key)
        if val is not None:
            return f"{key}={val}"
    tool_id = str(_safe_get(result, "tool_id", ""))
    if "workspace.artifact" in tool_id:
        return f"Listed {raw.get('count', '?')} artifacts"
    if "workspace.artifact" in tool_id:
        return f"Read artifact {raw.get('artifact_id', '?')}"
    if "search" in tool_id or "query" in tool_id:
        return f"Found {raw.get('count', '?')} results"
    if "system.session.get" in tool_id:
        return f"Listed {raw.get('count', '?')} sessions"
    if "system.run.get" in tool_id:
        return f"Listed {raw.get('count', '?')} runs"
    ok = bool(_safe_get(result, "ok", False))
    return "Completed" if ok else "Failed"


def _safe_get(obj, attr: str, default=None):
    """Safely get attribute or key from result object/dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    if hasattr(obj, attr):
        return getattr(obj, attr)
    return default


def _is_forbidden_prompt_key(key: str) -> bool:
    lower = key.lower()
    forbidden = (
        "source_config", "raw_config", "secret", "password",
        "token", "api_key", "authorization", "credentials",
        "ssh_key", "private_key",
    )
    return any(part in lower for part in forbidden)
