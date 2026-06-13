# agent/tools/registry.py
"""ToolRegistry — wraps ToolRuntimeClient, filters disabled/forbidden."""

from agent.tools.schemas import ToolSpec


class ToolRegistry:
    def __init__(self):
        self._specs: dict = {}       # tool_id → ToolSpec
        self._tool_client = None
        self._handlers: dict = {}    # tool_id → callable (capability-layer handlers)

    @classmethod
    def from_runtime_client(cls, client) -> "ToolRegistry":
        """Build registry from existing ToolRuntimeClient."""
        reg = cls()
        reg._tool_client = client
        try:
            raw_tools = client.list_tools()
            for t in raw_tools:
                spec = ToolSpec(
                    tool_id=t.get("tool_id", ""),
                    name=t.get("tool_id", ""),
                    category=t.get("category", ""),
                    description=t.get("description", ""),
                    risk_level=t.get("risk_level", "low"),
                    enabled=t.get("enabled", True),
                    requires_approval=t.get("requires_approval", False),
                    input_schema=t.get("input_schema", {}),
                    callable_by_llm=t.get("callable_by_llm", True),
                    forbidden=t.get("forbidden", False),
                    source=t.get("source", "runtime"),
                )
                reg._specs[spec.tool_id] = spec
        except Exception:
            pass
        return reg

    def list_all(self) -> list:
        return list(self._specs.values())

    def list_model_visible(self) -> list:
        """Tools visible to LLM: enabled + not forbidden + callable_by_llm."""
        return [s for s in self._specs.values()
                if s.enabled and not s.forbidden and s.callable_by_llm]

    def register_capability_tools(self, capability_registry) -> int:
        """Register capability tools from a CapabilityRegistry.

        Only enabled capabilities contribute tools. For each tool ref:
        - status == "enabled"  → registered as an enabled ToolSpec with
          the resolved handler (callable_by_llm preserved)
        - status == "planned"  → SKIPPED (planned tools are not injected)

        Returns the number of newly registered tool_ids.
        """
        if capability_registry is None:
            return 0
        registered = 0
        for tool_ref in capability_registry.enabled_tools():
            if tool_ref.status != "enabled":
                continue
            handler = _resolve_capability_handler(tool_ref.handler_ref)
            if handler is None:
                raise RuntimeError(
                    f"Failed to resolve handler for capability tool "
                    f"{tool_ref.tool_id!r}: {tool_ref.handler_ref!r}"
                )
            existing = self._specs.get(tool_ref.tool_id)
            if existing is not None and str(getattr(existing, "source", "")).startswith("capability:"):
                raise RuntimeError(f"Duplicate capability tool_id: {tool_ref.tool_id!r}")
            spec = ToolSpec(
                tool_id=tool_ref.tool_id,
                name=tool_ref.tool_id,
                category="capability",
                description=tool_ref.description,
                risk_level=tool_ref.risk_level,
                enabled=True,
                requires_approval=tool_ref.requires_approval,
                input_schema=dict(tool_ref.input_schema),
                callable_by_llm=tool_ref.callable_by_llm,
                forbidden=tool_ref.forbidden,
                source=f"capability:{tool_ref.tool_id}",
            )
            self._specs[spec.tool_id] = spec
            # v1.0.3.5: resolve and register capability handler so
            # dispatch() can find it. handler_ref is a dotted-path
            # string like "agent.modules.knowledge.tools:tool_handler_query".
            if not hasattr(self, '_handlers'):
                self._handlers = {}
            self._handlers[spec.tool_id] = handler
            registered += 1
        return registered

    def get(self, tool_id: str) -> ToolSpec:
        return self._specs.get(tool_id)

    def dispatch(self, tool_id: str, args: dict, context=None) -> dict:
        """Execute tool via capability handler or ToolRuntimeClient."""
        # Check capability-layer handlers first
        if tool_id in self._handlers:
            try:
                return self._handlers[tool_id](args, context)
            except Exception as e:
                return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}

        # Fall through to ToolRuntimeClient
        if self._tool_client is None:
            return {"ok": False, "status": "failed", "summary": "No tool client", "errors": ["no tool client"]}
        try:
            # v1.0.3.5: Adapt Agent Runtime's TurnContext (or any context-like
            # object) into the ToolRuntimeContext that ToolRuntimeClient expects.
            tc = _adapt_context_for_tool_runtime(context)
            result = self._tool_client.invoke(tool_id, args, context=tc)
            return _tool_runtime_result_to_dict(result)
        except Exception as e:
            return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}


def _resolve_capability_handler(handler_ref: str):
    """Import a capability handler by its dotted-path ref.

    Format: "module.path:variable_name"
    Returns the callable or None if resolution fails.
    """
    if not handler_ref or ":" not in handler_ref:
        return None
    mod_path, var_name = handler_ref.rsplit(":", 1)
    try:
        import importlib
        mod = importlib.import_module(mod_path)
        return getattr(mod, var_name, None)
    except Exception:
        return None


def _adapt_context_for_tool_runtime(ctx):
    """Project an Agent Runtime TurnContext (or similar) into a
    ToolRuntimeContext so the tool execution layer never receives
    an object it doesn't understand."""
    from tool_runtime.context import ToolRuntimeContext
    if isinstance(ctx, ToolRuntimeContext):
        return ctx
    if ctx is None:
        return ToolRuntimeContext()
    if isinstance(ctx, (str, bytes, int, float, bool, dict)):
        return ctx
    return ToolRuntimeContext(
        workspace_id=getattr(ctx, "workspace_id", ""),
        run_id=getattr(ctx, "turn_id", getattr(ctx, "run_id", "")),
        trace_id=getattr(ctx, "trace_id", ""),
        job_id=getattr(ctx, "job_id", ""),
        capability=getattr(ctx, "metadata", {}).get("capability_id", "") if hasattr(ctx, "metadata") else "",
        skill=_first(getattr(ctx, "metadata", {}).get("selected_skills", [])) if hasattr(ctx, "metadata") else "",
        module=getattr(ctx, "metadata", {}).get("active_module", "") if hasattr(ctx, "metadata") else "",
        requested_by="agent:runtime_loop",
        dry_run_default=False,
    )


def _first(lst):
    return lst[0] if lst else ""


def _tool_runtime_result_to_dict(result) -> dict:
    """Project ToolRuntimeResult into the agent ToolResult adapter shape."""
    if isinstance(result, dict):
        raw = dict(result)
    elif hasattr(result, "as_dict"):
        raw = result.as_dict()
    else:
        raw = {
            "status": getattr(result, "status", "failed"),
            "summary": getattr(result, "summary", ""),
            "errors": getattr(result, "errors", []) or [],
            "warnings": getattr(result, "warnings", []) or [],
        }
    status = raw.get("status", getattr(result, "status", "failed"))
    raw["ok"] = status in ("succeeded", "dry_run")
    raw.setdefault("summary", getattr(result, "summary", "") if not isinstance(result, dict) else "")
    raw.setdefault("errors", getattr(result, "errors", []) if not isinstance(result, dict) else [])
    raw.setdefault("warnings", getattr(result, "warnings", []) if not isinstance(result, dict) else [])
    if not isinstance(result, dict) and hasattr(result, "output"):
        raw.setdefault("output", result.output)
    return raw
