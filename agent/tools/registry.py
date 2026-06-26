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
        """Build registry from existing ToolRuntimeClient.

        v2.3.3: Only registers canonical tools (those present in
        TOOL_NAMESPACE). Non-canonical tool IDs that predate the v3.0
        canonical namespace are silently dropped.
        """
        reg = cls()
        reg._tool_client = client
        try:
            from tool_runtime.tool_namespace import TOOL_NAMESPACE
            raw_tools = client.list_tools()
            for t in raw_tools:
                tool_id = t.get("tool_id", "")
                # v2.3.3: skip non-canonical tool IDs not in the namespace
                if tool_id not in TOOL_NAMESPACE:
                    continue
                spec = ToolSpec(
                    tool_id=tool_id,
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
                    permission_action=t.get("permission_action", ""),
                    metadata=t.get("metadata", {}) or {},
                )
                try:
                    from tool_runtime.tool_namespace import enrich_spec
                    spec = enrich_spec(spec)
                except Exception:
                    pass
                reg._specs[spec.tool_id] = spec
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception(
                "ToolRegistry.from_runtime_client: list_tools() failed — "
                "core tools (web.*, host.*, workspace.*) will not be registered. "
                "Error: %s", exc
            )
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

        v2.3.3: Non-canonical capability tool IDs (e.g. knowledge.read_chunk) are
        filtered out when a canonical equivalent already exists in the
        registry, preventing duplicate tool entries.

        Returns the number of newly registered tool_ids.
        """
        if capability_registry is None:
            return 0
        from tool_runtime.tool_namespace import TOOL_NAMESPACE
        registered = 0
        for tool_ref in capability_registry.enabled_tools():
            if tool_ref.status != "enabled":
                continue
            # v2.3.3: skip non-canonical capability tools that duplicate runtime tools
            if tool_ref.tool_id not in TOOL_NAMESPACE:
                continue
            # v3.2.4: Skip tool registration entirely if _tool_client already
            # has this tool registered in CANONICAL_REGISTRY. Capability tool
            # refs often have empty input_schemas, which would overwrite the
            # canonical registry's full schema and cause the LLM to see tools
            # without parameters (e.g. device.get without asset_id field).
            # Must check BEFORE resolving handler_ref to avoid failures on
            # dummy handler_refs (e.g. knowledge.search uses canonical handler).
            if self._tool_client is not None:
                try:
                    existing_handler = self._tool_client._registry.get_handler(tool_ref.tool_id)
                except Exception:
                    existing_handler = None
            else:
                existing_handler = None
            
            if existing_handler is not None:
                continue  # Already registered in canonical registry — keep original spec
            
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
                permission_action=getattr(tool_ref, 'permission_action', '') or "read",
            )
            try:
                from tool_runtime.tool_namespace import enrich_spec
                spec = enrich_spec(spec)
            except Exception:
                pass
            self._specs[spec.tool_id] = spec
            # Register capability handler (now only for tools NOT in canonical registry)
            if not hasattr(self, '_handlers'):
                self._handlers = {}
            self._handlers[spec.tool_id] = handler
            registered += 1
        return registered

    def get(self, tool_id: str) -> ToolSpec:
        try:
            from tool_runtime.tool_governance import resolve_governed_tool_id
            tool_id = resolve_governed_tool_id(tool_id).handler_id
        except Exception:
            pass
        return self._specs.get(tool_id)

    def dispatch(self, tool_id: str, args: dict, context=None) -> dict:
        """Execute tool via handler (direct call, no policy for agent-internal use)."""
        try:
            from tool_runtime.tool_governance import resolve_governed_tool_id
            tool_id = resolve_governed_tool_id(tool_id).handler_id
        except Exception:
            pass
        # Check capability-layer handlers first
        if not hasattr(self, '_handlers'):
            self._handlers = {}
        if tool_id in self._handlers:
            try:
                return self._handlers[tool_id](args, context)
            except Exception as e:
                return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}

        # For general tools: dispatch through runtime client's handler directly,
        # bypassing ToolPolicy (agent-internal dispatch is already gated by LLM
        # tool selection and risk-level visibility). The handler provides its
        # own safety enforcement (e.g. command allowlists).
        if self._tool_client is None:
            return {"ok": False, "status": "failed", "summary": "No tool client", "errors": ["no tool client"]}
        try:
            handler = self._tool_client._registry.get_handler(tool_id)
            if handler is None:
                return {"ok": False, "status": "failed", "summary": f"Tool not found: {tool_id}",
                        "errors": [f"tool_not_found: {tool_id}"]}
            from tool_runtime.schemas import ToolInvocation
            # Extract real workspace context — no more hardcoded defaults
            ws_id = "default"
            run_id = ""
            job_id = ""
            session_id = ""
            requested_by = "agent"
            if context:
                ws_id = getattr(context, 'workspace_id', 'default') or 'default'
                run_id = getattr(context, 'turn_id', '') or getattr(context, 'run_id', '') or ''
                job_id = getattr(context, 'job_id', '') or ''
                session_id = getattr(context, 'session_id', '') or ''
                requested_by = getattr(context, 'requested_by', 'agent') or 'agent'
            inv = ToolInvocation(
                tool_id=tool_id, arguments=args,
                workspace_id=ws_id, run_id=run_id, job_id=job_id,
                dry_run=False, requested_by=requested_by,
            )
            raw = handler(inv)
            if isinstance(raw, dict):
                return raw
            return raw.to_dict() if hasattr(raw, 'to_dict') else {"ok": False, "error": "unknown handler result"}
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
