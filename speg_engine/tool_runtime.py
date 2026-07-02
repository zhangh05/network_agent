"""
Stateless Tool Runtime — pure function style execution.

Key rules:
  - Tool must be pure function style: execute_tool(name, args) → result
  - No hidden shared state
  - No implicit context access
  - All independent executions are concurrent
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .models import ExecutionNode, ExecutionStatus, SPEGConfig, StatelessContext, ToolResult

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class ToolRuntime:
    """Stateless tool execution runtime.

    Tools are registered as handler functions. Each handler receives
    arguments and returns results — no shared state, no implicit context.
    """

    def __init__(self, config: SPEGConfig):
        self._config = config
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool_id: str, handler: ToolHandler) -> None:
        """Register a tool handler.

        Handler signature: handler(args: dict) → result | Awaitable[result]
        """
        self._handlers[tool_id] = handler

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self._handlers

    async def execute_node(
        self,
        node: ExecutionNode,
        ctx: StatelessContext,
        dep_results: dict[str, ToolResult],
    ) -> ToolResult:
        """Execute a single node with dependency injection.

        Args:
            node: The compiled execution node
            ctx: Minimal stateless context
            dep_results: Resolved results of this node's dependencies

        Returns:
            ToolResult with success/failure and data

        v3.10: the handler result is normalized so that ``ok=False``
        in the returned dict maps to ``ToolResult.success=False``.
        This is what lets the retry policy, dependency gate, and
        tool-call aggregation see the real outcome — previously
        SPEG always returned ``success=True`` whenever the handler
        didn't raise, even when its inner data said the call had
        failed. The behavior now mirrors the production tool
        runtime at ``tool_runtime.executor``: the handler's
        explicit ``ok`` (or ``success``) field drives success.
        """
        start = time.monotonic()

        if node.tool not in self._handlers:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"Tool '{node.tool}' has no registered handler",
                error_code="TOOL_NOT_REGISTERED",
                latency_ms=elapsed,
                retry_count=0,
            )

        # Inject dependency results into args
        merged_args = self._merge_dep_results(node.args, dep_results)

        try:
            handler = self._handlers[node.tool]
            # Run with timeout
            result = await asyncio.wait_for(
                self._invoke_handler(handler, merged_args),
                timeout=self._config.single_node_timeout_ms / 1000,
            )
            elapsed = (time.monotonic() - start) * 1000
            return _normalize_result(node, result, elapsed)
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"Tool execution timed out after {self._config.single_node_timeout_ms}ms",
                error_code="TOOL_TIMEOUT",
                latency_ms=elapsed,
                retry_count=node.retry_count,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"{type(e).__name__}: {e}",
                error_code="TOOL_EXCEPTION",
                latency_ms=elapsed,
                retry_count=node.retry_count,
            )

    async def execute_layer(
        self,
        nodes: list[ExecutionNode],
        ctx: StatelessContext,
        dep_results: dict[str, ToolResult],
    ) -> dict[str, ToolResult]:
        """Execute all nodes in a layer concurrently.

        All nodes at the same depth run fully parallel via asyncio.gather.
        """
        if not nodes:
            return {}

        tasks = {
            node.id: asyncio.create_task(
                self.execute_node(node, ctx, dep_results)
            )
            for node in nodes
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        layer_results: dict[str, ToolResult] = {}
        for node_id, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                layer_results[node_id] = ToolResult(
                    node_id=node_id,
                    tool="unknown",
                    success=False,
                    error=f"{type(result).__name__}: {result}",
                )
            else:
                layer_results[node_id] = result

        return layer_results

    async def _invoke_handler(self, handler: ToolHandler, args: dict[str, Any]) -> Any:
        """Invoke a handler, supporting both sync and async handlers."""
        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def _merge_dep_results(
        self,
        args: dict[str, Any],
        dep_results: dict[str, ToolResult],
    ) -> dict[str, Any]:
        """Inject dependency results into node arguments.

        If an arg value is a special reference like "$dep.node_id.data",
        replace it with the actual dependency result.
        """
        merged = dict(args)
        for key, value in list(merged.items()):
            if isinstance(value, str) and value.startswith("$dep."):
                # Resolve dependency: "$dep.node_id.data"
                parts = value.replace("$dep.", "").split(".", 1)
                dep_id = parts[0]
                if dep_id in dep_results:
                    dep_result = dep_results[dep_id]
                    if len(parts) > 1 and parts[1] == "data":
                        merged[key] = dep_result.data
                    else:
                        merged[key] = dep_result.data
        return merged


# ── Module-level result normalizer ──────────────────────────────────────

# Default error code surfaced when the handler explicitly reports
# failure without naming one. Surfaced so the retry policy and the
# downstream-skip gate can discriminate it from a timeout / raise.
_HANDLER_NOT_OK_DEFAULT_CODE = "TOOL_RETURNED_NOT_OK"


def _stringify_errors(errors: Any) -> str:
    """Best-effort flattening of an ``errors`` payload into a
    single human-readable string for ``ToolResult.error``.

    Accepts ``list`` / ``dict`` / ``str`` / scalar. Returns "" if
    nothing useful is present.
    """
    if not errors:
        return ""
    if isinstance(errors, str):
        return errors
    if isinstance(errors, list):
        parts = [_stringify_errors(e) for e in errors if e not in (None, "")]
        return "; ".join(p for p in parts if p)
    if isinstance(errors, dict):
        import json as _json
        try:
            return _json.dumps(errors, ensure_ascii=False, default=str)
        except Exception:
            return str(errors)
    return str(errors)


def _resolve_success_flag(handler_result: Any) -> bool:
    """Read ``ok`` / ``success`` from a handler result.

    Resolution order:
      1. ``ok`` if present (bool) — preferred signal.
      2. ``success`` if present (bool) — legacy fallback.
      3. default True — handler did not declare a verdict; the
         runtime treats absence-of-error as success.

    Returns the resolved boolean.
    """
    if not isinstance(handler_result, dict):
        return True
    if "ok" in handler_result:
        return bool(handler_result["ok"])
    if "success" in handler_result:
        return bool(handler_result["success"])
    return True


def _resolve_error_code(handler_result: Any) -> str:
    """Read ``error_code`` / ``code`` from a handler result. Empty
    string if neither is present."""
    if not isinstance(handler_result, dict):
        return ""
    code = handler_result.get("error_code") or handler_result.get("code")
    return str(code) if code else ""


def _resolve_error_message(handler_result: Any) -> str:
    """Read the human-readable error string. Falls back across
    ``errors`` / ``error`` / ``message``."""
    if not isinstance(handler_result, dict):
        return ""
    err = handler_result.get("error") or handler_result.get("message")
    if err:
        return str(err)
    errors = handler_result.get("errors")
    if errors:
        return _stringify_errors(errors)
    return ""


def _normalize_result(
    node: ExecutionNode,
    handler_result: Any,
    elapsed_ms: float,
) -> ToolResult:
    """Build a ``ToolResult`` from a handler return value, honoring
    the handler's own ``ok``/``success``/``error`` declaration.

    This is the single point where the SPEG layer decides whether a
    handler that didn't raise was actually successful. A handler
    that returned ``{"ok": false, ...}`` now correctly produces
    ``ToolResult.success=False`` so the retry policy, the DAG
    dependency gate, the audit / trace pipeline, and the final
    tool-call aggregation all see the real outcome.
    """
    success = _resolve_success_flag(handler_result)
    error_code = _resolve_error_code(handler_result) if not success else ""
    if not error_code:
        error_code = _HANDLER_NOT_OK_DEFAULT_CODE if not success else ""
    error_message = _resolve_error_message(handler_result) if not success else ""

    return ToolResult(
        node_id=node.id,
        tool=node.tool,
        success=success,
        data=handler_result,
        error=error_message or None,
        error_code=error_code or "",
        latency_ms=elapsed_ms,
        retry_count=node.retry_count,
    )
