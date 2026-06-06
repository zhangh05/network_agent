# tool_runtime/integration.py
"""Integration helpers — factory functions and trace metadata adapter.

Provides:
  - get_default_tool_runtime_client(): default client with v0.1 builtins
  - create_tool_runtime_client(): configurable factory for testing
  - build_trace_metadata_from_tool_result(): safe trace metadata builder
"""

from tool_runtime.registry import ToolRegistry
from tool_runtime.policy import ToolPolicy
from tool_runtime.client import ToolRuntimeClient
from tool_runtime.schemas import ToolResult
from tool_runtime.builtins import register_builtin_tools

# ── Module-level default (lazy singleton) ──
_default_client: ToolRuntimeClient = None


def get_default_tool_runtime_client() -> ToolRuntimeClient:
    """Get or create the default ToolRuntimeClient with v0.1 built-in tools.

    Returns a singleton instance. Thread-safe for creation (not mutation).
    Uses independent ToolInvocation/ToolResult — does NOT import agent/state.py.
    """
    global _default_client
    if _default_client is None:
        registry = register_builtin_tools(ToolRegistry())
        policy = ToolPolicy()
        _default_client = ToolRuntimeClient(registry, policy)
    return _default_client


def create_tool_runtime_client(
    registry: ToolRegistry = None,
    policy: ToolPolicy = None,
) -> ToolRuntimeClient:
    """Create a ToolRuntimeClient with optional custom registry/policy.

    If registry is None, creates empty registry (no builtins).
    Useful for testing with mock/injected registries.
    """
    if registry is None:
        registry = ToolRegistry()
    if policy is None:
        policy = ToolPolicy()
    return ToolRuntimeClient(registry, policy)


def build_trace_metadata_from_tool_result(result: ToolResult) -> dict:
    """Build safe trace/observability metadata from a ToolResult.

    Returns a dict suitable for trace event metadata or audit log.
    Contains ONLY summary-level fields — no full output, no full arguments,
    no keys, no passwords, no paths.

    Args:
        result: A completed ToolResult.

    Returns:
        dict with safe metadata fields.
    """
    meta = {
        "invocation_id": result.invocation_id,
        "tool_id": result.tool_id,
        "status": result.status,
        "duration_ms": result.duration_ms,
        "redacted": result.redacted,
        "artifact_ids": result.artifact_ids,
        "dry_run": result.status == "dry_run",
        "warning_count": len(result.warnings),
        "error_count": len(result.errors),
        "output_keys": list(result.output.keys()) if isinstance(result.output, dict) else [],
        "summary": result.summary[:200],
    }

    # Policy decision (safe: no full arguments)
    if result.policy_decision:
        meta["policy"] = {
            "allowed": result.policy_decision.allowed,
            "risk_level": result.policy_decision.risk_level,
            "blocked_rules": result.policy_decision.blocked_rules,
            "reason": result.policy_decision.reason[:200],
        }

    return meta
