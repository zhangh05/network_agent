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
            dry_run = context.dry_run_default
        dry_run = dry_run or False

        # ── Build invocation ──
        invocation = ToolInvocation(
            tool_id=tool_id,
            arguments=arguments,
            workspace_id=context.workspace_id if context else None,
            run_id=context.run_id if context else None,
            job_id=context.job_id if context else None,
            dry_run=dry_run,
            requested_by=context.requested_by if context else "",
        )

        # ── Execute through full pipeline ──
        return self._executor.execute(invocation)

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
