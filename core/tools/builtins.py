# core/tools/builtins.py
"""Built-in low-risk tools.

One baseline tool is provided:
  1. workspace.artifact       — list artifact summaries (no full content)

All tools are risk_level=low and dry_run_supported=True. They are
scope-limited to workspace state; remote device access is intentionally
not provided here (use exec.run(target=ssh|telnet) for that).
"""

from core.tools.schemas import ToolSpec, ToolInvocation
from core.tools.registry import ToolRegistry


def _enrich_result(invocation, d):
    out = dict(d)
    if "tool_id" not in out:
        out["tool_id"] = getattr(invocation, "tool_id", "")
    if "status" not in out:
        out["status"] = "ok" if out.get("ok") else "failed"
    if "errors" not in out and not out.get("ok"):
        msg = out.get("error") or out.get("summary") or "failed"
        out["errors"] = [msg]
    if "summary" not in out:
        out["summary"] = "Completed."
    return out

# ═══════════════════════════════════
# Tool Handlers
# ═══════════════════════════════════

def _handler_artifact_list(invocation: ToolInvocation) -> dict:
    """List artifact summaries for a workspace. Returns metadata only."""
    workspace_id = invocation.arguments.get("workspace_id", invocation.workspace_id or "")
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        items = []
        # Artifacts are tracked in workspace state with refs
        art_refs = state.get("artifact_refs", []) if isinstance(state, dict) else []
        return {
            "ok": True,
            "tool_id": "workspace.artifact",
            "status": "ok",
            "summary": f"Listed {len(art_refs)} artifact references",
            "artifacts": art_refs[:50],  # limit to 50 entries
            "workspace_id": workspace_id,
            "warnings": ["Artifact list is metadata-only; no full content returned"] if art_refs else [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "tool_id": "workspace.artifact",
            "status": "failed",
            "summary": f"Failed to list artifacts: {str(exc)[:100]}",
            "artifacts": [],
            "warnings": [f"workspace.artifact failed: {str(exc)[:100]}"],
        }


# ═══════════════════════════════════
# ToolSpec Definitions
# ═══════════════════════════════════

BUILTIN_TOOLS = [
    (
        ToolSpec(
            tool_id="workspace.artifact",
            name="List Artifacts",
            description="List artifact metadata summaries for a workspace. Use when: user wants to browse available artifacts before reading one. Read-only. No full content returned — use workspace.workspace.artifact for previews. Returns artifact_id, title, type for each entry.",
            category="artifact",
            risk_level="low",
            reads_artifact=True,
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                },
            },
        ),
        _handler_artifact_list,
    ),
]


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
