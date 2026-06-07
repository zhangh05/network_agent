"""Safe Tool Runtime trace metadata helpers."""

from tool_runtime.schemas import ToolResult


def build_trace_metadata_from_tool_result(result: ToolResult) -> dict:
    """Build allowlisted metadata for trace/observability stores."""
    policy = result.policy_decision
    return {
        "invocation_id": result.invocation_id,
        "tool_id": result.tool_id,
        "status": result.status,
        "duration_ms": result.duration_ms,
        "dry_run": result.status == "dry_run",
        "redacted": result.redacted,
        "policy_allowed": policy.allowed if policy else None,
        "policy_reason": (policy.reason[:200] if policy and policy.reason else ""),
        "risk_level": policy.risk_level if policy else "",
        "artifact_ids": list(result.artifact_ids or [])[:50],
    }
