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
            from core.tools.tool_namespace import TOOL_NAMESPACE
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
                    from core.tools.tool_namespace import enrich_spec
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

    def get(self, tool_id: str) -> ToolSpec:
        try:
            pass  # v3.9.3: handler_id == canonical_id (no alias layer)
        except Exception:
            pass
        return self._specs.get(tool_id)

    def dispatch(self, tool_id: str, args: dict, context=None) -> dict:
        """Execute tool through ToolRuntimeClient.invoke() — no direct handler call.

        v3.10: All tool execution MUST go through the full safety pipeline:
        schema→manifest→caller→policy→interrupt→executor→redaction→audit→ToolResult.
        Direct handler calls and registry dispatch bypasses are forbidden.
        """
        if self._tool_client is None:
            return {"ok": False, "status": "failed", "summary": "No tool client", "errors": ["no tool client"]}
        try:
            # Extract caller context — no hardcoded defaults
            ws_id = ""
            run_id = ""
            job_id = ""
            requested_by = ""
            if context:
                ws_id = getattr(context, 'workspace_id', '') or ''
                session_id = getattr(context, 'session_id', '') or ''
                run_id = getattr(context, 'turn_id', '') or getattr(context, 'run_id', '') or ''
                task_id = getattr(context, 'task_id', '') or ''
                job_id = getattr(context, 'job_id', '') or ''
                requested_by = getattr(context, 'requested_by', '') or ''

            # Caller identity is mandatory for all tool invocations.
            # Set TurnContext.requested_by (default "turn_runner") or
            # ToolRuntimeContext.requested_by for non-agent callers.
            if not requested_by:
                return {"ok": False, "status": "blocked",
                        "summary": "Tool dispatch blocked: caller identity (requested_by) is required",
                        "errors": ["caller_missing"]}

            from core.tools.context import ToolRuntimeContext
            ctx = ToolRuntimeContext(
                workspace_id=ws_id, session_id=session_id,
                run_id=run_id, task_id=task_id, job_id=job_id,
                requested_by=requested_by,
            )
            result = self._tool_client.invoke(tool_id, args, context=ctx)
            return {
                "ok": result.status == "succeeded",
                "status": result.status,
                "summary": result.summary or "",
                "output": result.output or {},
                "errors": list(result.errors or []),
                "warnings": list(result.warnings or []),
                "artifacts": list(result.artifact_ids or []),
            }
        except Exception as e:
            return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}


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
