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
from tool_runtime.builtins import register_builtin_tools
from tool_runtime.trace_metadata import build_trace_metadata_from_tool_result

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
