"""
Result Merger — collect DAG results and format final structured output.

Responsibilities:
  - Collect all node results from execution
  - Resolve dependency ordering
  - Format final structured output
"""

from __future__ import annotations

import time
from typing import Any

from .models import ExecutionDAG, ExecutionNode, ExecutionStatus, StatelessContext, ToolResult


class ResultMerger:
    """Collects and merges DAG execution results into structured output."""

    def merge(
        self,
        dag: ExecutionDAG,
        node_results: dict[str, ToolResult],
        ctx: StatelessContext,
    ) -> dict[str, Any]:
        """Merge all node results into structured summary.

        Returns a structured dict that the finalizer (or caller) can use.
        """
        start = time.monotonic()

        # Group results by tool category (from tool prefix)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for node in dag.nodes:
            result = node_results.get(node.id)
            if result is None:
                continue
            category = node.tool.split(".")[0]  # "exec.run" → "exec"
            if category not in grouped:
                grouped[category] = []
            grouped[category].append({
                "node_id": node.id,
                "tool": node.tool,
                "success": result.success,
                "data": result.data,
                "data_unwrapped": _unwrap_llm_payload(result.data),
                "error": result.error,
                "latency_ms": result.latency_ms,
            })

        # Build summary
        success_count = sum(1 for r in node_results.values() if r.success)
        fail_count = sum(1 for r in node_results.values() if not r.success)

        merged = {
            "total_nodes": dag.total_nodes,
            "success_count": success_count,
            "failure_count": fail_count,
            "max_depth": dag.max_depth,
            "results_by_category": grouped,
            "all_results": {
                nid: {
                    "tool": r.tool,
                    "success": r.success,
                    "data": r.data,
                    "data_unwrapped": _unwrap_llm_payload(r.data),
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                    "retry_count": r.retry_count,
                }
                for nid, r in node_results.items()
            },
        }

        elapsed = (time.monotonic() - start) * 1000
        ctx.extras["merge_latency_ms"] = elapsed

        return merged


def _unwrap_llm_payload(data: Any) -> Any:
    """Expose common nested tool payloads for final synthesis.

    ToolRuntimeClient returns a full ToolResult-shaped dict for canonical
    handlers. For merged tools that dict often contains the useful payload under
    ``output`` or ``content``. Keeping both original ``data`` and this
    unwrapped form lets the finalizer answer from structured fields without
    losing audit fidelity.
    """
    if not isinstance(data, dict):
        return data
    for key in ("output", "content"):
        nested = data.get(key)
        if isinstance(nested, dict) and nested:
            return nested
    return data
