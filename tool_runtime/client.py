# tool_runtime/client.py
"""ToolRuntimeClient — standard, controlled, auditable interface for invoking tools.

Designed for Module / Service layers (NOT direct Agent invocation).
All invocations go through ToolPolicy, ToolExecutor, redaction, and audit.

Example:
    client = get_default_tool_runtime_client()
    ctx = ToolRuntimeContext(workspace_id="default", module="config_translation")
    result = client.invoke("parser.parse_config_text", {"config_text": cfg}, context=ctx)
"""

from typing import Optional

from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult
from tool_runtime.registry import ToolRegistry
from tool_runtime.policy import ToolPolicy
from tool_runtime.executor import ToolExecutor
from tool_runtime.context import ToolRuntimeContext


class ToolRuntimeClient:
    """Standard client for invoking tools through the full safety pipeline.

    Does NOT bypass ToolPolicy. Does NOT write Memory. Does NOT call LLM.
    Uses independent ToolInvocation / ToolResult (not legacy agent/state.py fields).
    """

    def __init__(self, registry: ToolRegistry, policy: ToolPolicy = None):
        self._registry = registry
        self._policy = policy or ToolPolicy()
        self._executor = ToolExecutor(self._registry, self._policy)

    def invoke(
        self,
        tool_id: str,
        arguments: dict = None,
        *,
        dry_run: bool = None,
        context: ToolRuntimeContext = None,
    ) -> ToolResult:
        """Invoke a tool through the full safety pipeline.

        Args:
            tool_id: The tool to invoke (e.g. "parser.parse_config_text").
            arguments: Tool arguments dict.
            dry_run: Override dry_run. If None, uses context.dry_run_default.
            context: Optional ToolRuntimeContext for workspace/run/job/caller info.

        Returns:
            ToolResult with status, redacted output, audit metadata.
            Never raises — all errors are captured in ToolResult.
        """
        arguments = arguments or {}

        # ── Resolve dry_run ──
        if dry_run is None and context is not None:
            dry_run = getattr(context, "dry_run_default", False)
        dry_run = dry_run or False

        # ── Build invocation ──
        invocation = ToolInvocation(
            tool_id=tool_id,
            arguments=arguments,
            workspace_id=getattr(context, "workspace_id", None) if context else None,
            run_id=getattr(context, "run_id", None) if context else None,
            job_id=getattr(context, "job_id", None) if context else None,
            dry_run=dry_run,
            requested_by=getattr(context, "requested_by", "") if context else "",
            approval_id=getattr(context, "approval_id", None) if context else None,
        )

        # ── Execute through full pipeline ──
        result = self._executor.execute(invocation)
        self._append_trace_event(result, context)
        return result

    def list_tools(self) -> list:
        """List all registered tools as metadata dicts (no handler callables)."""
        return self._registry.list_tools()

    def get_tool(self, tool_id: str) -> Optional[dict]:
        """Get tool metadata by id. Returns dict (no handler)."""
        spec = self._registry.get_tool(tool_id)
        return spec.as_dict() if spec else None

    @property
    def tool_count(self) -> int:
        return self._registry.count()

    def _append_trace_event(self, result: ToolResult, context: ToolRuntimeContext = None):
        """Append safe ToolResult metadata to an existing observability trace."""
        if not context or not context.trace_id:
            return
        try:
            from observability.store import append_event
            from tool_runtime.trace_metadata import build_trace_metadata_from_tool_result

            meta = build_trace_metadata_from_tool_result(result)
            meta.update({
                "workspace_id": getattr(context, "workspace_id", "") or "",
                "run_id": getattr(context, "run_id", "") or "",
                "job_id": getattr(context, "job_id", "") or "",
                "capability": getattr(context, "capability", "") or "",
                "skill": getattr(context, "skill", "") or "",
                "module": getattr(context, "module", "") or "",
            })
            status = "success" if result.status in ("succeeded", "dry_run") else "failed"
            append_event(getattr(context, "trace_id", ""), {
                "trace_id": getattr(context, "trace_id", ""),
                "run_id": getattr(context, "run_id", ""),
                "workspace_id": getattr(context, "workspace_id", "default"),
                "event_type": "tool_runtime",
                "name": f"tool:{result.tool_id}",
                "status": status,
                "duration_ms": result.duration_ms,
                "summary": f"tool:{result.tool_id}: {result.status}",
                "metadata": meta,
                "redaction_applied": True,
            }, ws_id=context.workspace_id or "default")
        except Exception:
            return
