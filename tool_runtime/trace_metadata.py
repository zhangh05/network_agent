"""Safe Tool Runtime trace metadata helpers."""

from tool_runtime.schemas import ToolResult


def build_trace_metadata_from_tool_result(result: ToolResult) -> dict:
    """Build allowlisted metadata for trace/observability stores."""
    policy = result.policy_decision
    try:
        from tool_runtime.tool_namespace import get_canonical_tool_id, get_namespace_entry
        canonical_tool_id = get_canonical_tool_id(result.tool_id)
        entry = get_namespace_entry(result.tool_id)
        legacy_tool_ids = list(entry.legacy_tool_ids)
    except Exception:
        canonical_tool_id = result.tool_id
        legacy_tool_ids = [result.tool_id]
    return {
        "invocation_id": result.invocation_id,
        "tool_id": result.tool_id,
        "requested_tool_id": result.tool_id,
        "canonical_tool_id": canonical_tool_id,
        "execution_tool_id": result.tool_id,
        "legacy_alias_used": result.tool_id != canonical_tool_id,
        "legacy_tool_ids": legacy_tool_ids[:20],
        "status": result.status,
        "duration_ms": result.duration_ms,
        "dry_run": result.status == "dry_run",
        "redacted": result.redacted,
        "policy_allowed": policy.allowed if policy else None,
        "policy_reason": (policy.reason[:200] if policy and policy.reason else ""),
        "risk_level": policy.risk_level if policy else "",
        "artifact_ids": list(result.artifact_ids or [])[:50],
    }
