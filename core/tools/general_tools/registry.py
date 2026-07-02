"""Registry for split general tools.

This module is a thin pass-through to the canonical registry, which is the
truth source for tool metadata and dispatch. Removed _reg() definitions,
GENERAL_TOOL_INPUT_SCHEMAS, and _finalize_tool_output helpers have been
removed — they were dead code superseded by canonical_registry.py.
"""
from copy import deepcopy


def register_all_general_tools(registry):
    """Register all general tools into a ToolRegistry.

    This is a thin pass-through to the canonical registry, which is the truth
    source for tool metadata and dispatch.
    """
    from core.tools.canonical_registry import to_tool_specs

    for spec, handler in to_tool_specs():
        try:
            registry.register_tool(deepcopy(spec), handler)
        except ValueError:
            # Already registered (e.g. by register_builtin_tools) — skip.
            continue
    return registry
