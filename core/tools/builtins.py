# core/tools/builtins.py
"""Built-in low-risk tools.

No tools are currently registered here — the canonical registry
(canonical_registry.py) is the authoritative source for all tool
definitions, including workspace.artifact with its 7 merged operations
(list/read/save/tag/delete/diff/export).
"""

from core.tools.schemas import ToolSpec, ToolInvocation
from core.tools.registry import ToolRegistry


# v3.11: BUILTIN_TOOLS is now empty. The workspace.artifact tool that was
# previously registered here as a list-only stub has been retired because
# the canonical registry provides the same tool with full read/save/tag/
# delete support. Registering a duplicate would shadow the canonical
# handler and silently break those operations.
BUILTIN_TOOLS = []


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register built-in tools into the given registry.

    Returns the same registry for chaining.
    """
    for spec, handler in BUILTIN_TOOLS:
        registry.register_tool(spec, handler)
    return registry


def create_registry_with_builtins() -> ToolRegistry:
    """Create a ToolRegistry and register all built-in tools.

    Convenience factory for tests and runtime initialization.
    """
    return register_builtin_tools(ToolRegistry())
