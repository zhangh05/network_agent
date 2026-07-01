"""
Async Execution Engine — the core parallel runtime of SPEG.

Executes a validated DAG layer by layer:
  layer_0 → parallel execution of all nodes
  layer_1 → parallel execution of all nodes
  ...
  layer_N

Each layer runs ALL nodes concurrently via asyncio.gather.
Nodes only execute once all their dependencies (previous layers) are done.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    SPEGConfig,
    SPEGResult,
    StatelessContext,
    ToolResult,
)
from .tool_runtime import ToolRuntime


class ExecutionEngine:
    """Async parallel DAG execution engine.

    Executes the DAG depth-first: all nodes at depth 0 run in parallel,
    then depth 1, etc. Each layer uses asyncio.gather for full parallelism.
    """

    MAX_RETRIES = 1  # Hard limit per spec

    def __init__(self, config: SPEGConfig, tool_runtime: ToolRuntime):
        self._config = config
        self._runtime = tool_runtime

    async def execute(
        self,
        dag: ExecutionDAG,
        ctx: StatelessContext,
    ) -> dict[str, ToolResult]:
        """Execute the full DAG asynchronously.

        v3.10 (tool retry): adds a per-layer dependency check — if
        any node in a deeper layer has a dep that ended up failed
        or skipped, the node is marked ``skipped`` with reason
        ``dependency_failed`` and the tool handler is not invoked.

        Returns:
            Dict mapping node_id → ToolResult for all nodes.
        """
        from .models import ExecutionStatus
        start = time.monotonic()
        all_results: dict[str, ToolResult] = {}

        for depth in range(dag.max_depth + 1):
            layer_nodes = dag.get_layer(depth)
            if not layer_nodes:
                continue

            # v3.10: dependency gate. A node is skipped when any
            # of its dependencies is FAILED or SKIPPED — the
            # tool handler must NOT run on a stale dep result.
            runnable: list = []
            for node in layer_nodes:
                skip_reason = _dependency_skip_reason(node, all_results)
                if skip_reason is not None:
                    skip_result = ToolResult(
                        node_id=node.id,
                        tool=node.tool,
                        success=False,
                        error=skip_reason,
                        error_code="DEPENDENCY_FAILED",
                        metadata={"skip_reason": "dependency_failed"},
                    )
                    node.status = ExecutionStatus.SKIPPED
                    node.error = skip_reason
                    node.result = None
                    node.finished_at = time.monotonic()
                    all_results[node.id] = skip_result
                    continue
                runnable.append(node)
                node.status = ExecutionStatus.RUNNING
                node.started_at = time.monotonic()

            if not runnable:
                continue

            # Execute all nodes in this layer in parallel.
            layer_results = await self._runtime.execute_layer(
                runnable, ctx, all_results
            )

            # Process results: handle failures with retry + isolation
            for node in runnable:
                result = layer_results.get(node.id)
                if result is None:
                    result = ToolResult(
                        node_id=node.id,
                        tool=node.tool,
                        success=False,
                        error="No result returned from execution",
                        error_code="TOOL_EXCEPTION",
                    )

                if not result.success:
                    result = await self._handle_failure(node, ctx, all_results, layer_results)

                # Update node state
                node.result = result.data
                node.error = result.error
                node.status = (
                    ExecutionStatus.SUCCESS if result.success
                    else ExecutionStatus.FAILED
                )
                node.latency_ms = result.latency_ms
                node.finished_at = time.monotonic()
                all_results[node.id] = result

        execution_latency = (time.monotonic() - start) * 1000
        ctx.extras["execution_latency_ms"] = execution_latency

        return all_results

    async def _handle_failure(
        self,
        node: ExecutionNode,
        ctx: StatelessContext,
        all_results: dict[str, ToolResult],
        layer_results: dict[str, ToolResult],
    ) -> ToolResult:
        """Handle node failure per the v3.10 retry policy.

        Steps:
          1. Look up the ToolContract for ``node.tool``.
          2. Extract ``error_code`` / ``error_message`` from the
             original ``ToolResult``.
          3. Consult ``should_retry_tool_failure()`` — this is the
             single policy entry point shared with the engine-level
             stage-10 retry path. It refuses to retry:
                - missing contracts
                - policy / safety errors
                - non-idempotent tools
                - mutating side effects
                - non-transient error codes
                - already-exhausted retry budget
                - budget-exceeded
          4. If retry is allowed:
                - increment ``node.retry_count``
                - sleep ``backoff_ms`` (default 200ms)
                - re-invoke the tool handler via ``execute_node``
                - record a ``tool_retry`` event into the trace
                - update ``node_results`` so downstream nodes see the
                  post-retry result
          5. If retry is refused (or the retry itself fails), return
             the original failure to the caller so the layer / DAG
             can mark downstream nodes as ``skipped``.
        """
        from .contracts import get_contract
        from .tool_retry_policy import should_retry_tool_failure

        original = layer_results.get(node.id) or ToolResult(
            node_id=node.id,
            tool=node.tool,
            success=False,
            error="No result returned from execution",
        )

        contract = get_contract(node.tool)
        error_code = (original.error_code or "").strip().upper()
        if not error_code:
            # Best-effort: infer TOOL_TIMEOUT from the message so
            # the policy has something to discriminate on when the
            # handler forgot to set the field.
            err = (original.error or "").lower()
            if "timeout" in err or "timed out" in err:
                error_code = "TOOL_TIMEOUT"
            elif "rate" in err and "limit" in err:
                error_code = "RATE_LIMITED"
            elif "connection" in err and "reset" in err:
                error_code = "CONNECTION_RESET"
            else:
                error_code = "TOOL_EXCEPTION"

        decision = should_retry_tool_failure(
            node=node,
            tool_contract=contract,
            error_code=error_code,
            error_message=original.error or "",
            config_max_retries=(
                int(getattr(contract, "max_retries", 0) or 0)
                if contract is not None else 0
            ),
            global_max_retries_per_node=self._config.max_retries_per_node,
            budget_ok=True,  # ExecutionEngine does not own the
                             # budget — the engine-level path enforces
                             # it before retrying.
        )

        # Stash the decision on the node so the engine / audit /
        # trace hooks can read it without re-running the policy.
        node.last_retry_decision = decision
        if not decision.retry_allowed:
            return original

        # Apply backoff (200ms for attempt 0).
        await asyncio.sleep(decision.backoff_ms / 1000.0)

        node.retry_count += 1
        node.status = ExecutionStatus.RETRYING

        retry_result = await self._runtime.execute_node(
            node, ctx, all_results,
        )
        retry_result.retry_count = node.retry_count

        # Annotate the ToolResult with retry provenance so audit /
        # metadata can surface it.
        retry_result.metadata = dict(retry_result.metadata or {})
        retry_result.metadata["retried"] = True
        retry_result.metadata["retry_count"] = node.retry_count
        retry_result.metadata["retry_reason"] = decision.reason
        retry_result.metadata["retry_backoff_ms"] = decision.backoff_ms
        retry_result.metadata["retry_error_code"] = decision.error_code
        retry_result.metadata["retry_original_error"] = (
            decision.notes.get("original_error", "")
        )

        if retry_result.success:
            return retry_result

        # Retry attempted but the second call also failed — return
        # the new failure (not the original) so audit captures the
        # final state.
        return retry_result


# ── Module-level helpers ───────────────────────────────────────────────

def _dependency_skip_reason(node: Any, all_results: dict) -> str | None:
    """Return a skip reason if any of ``node.deps`` ended up failed
    or skipped, else ``None``.

    A node is eligible to run only when every dep is either absent
    or succeeded. The tool handler must NOT run on a stale dep
    result.
    """
    deps = getattr(node, "deps", None) or []
    for dep_id in deps:
        dep = all_results.get(dep_id)
        if dep is None:
            continue
        if dep.success:
            continue
        return f"dependency_failed: dep '{dep_id}' did not succeed"
    return None
