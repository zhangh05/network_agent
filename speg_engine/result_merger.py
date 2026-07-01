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

        Returns a structured dict that the finalizer (or caller) can use,
        including ``normalized_content`` extracted from read-type tools
        (workspace.readartifact, workspace.file read, etc.).
        """
        start = time.monotonic()

        # Group results by tool category (from tool prefix)
        grouped: dict[str, list[dict[str, Any]]] = {}
        normalized_contents: list[str] = []

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

            # ── v3.14: normalized_content extraction ────────────────
            # Extract readable text from read-type tools so the
            # finalizer has something to analyse instead of just
            # "工具执行成功".
            nc = _extract_normalized_content(node.tool, result)
            if nc:
                normalized_contents.append(nc)

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
            # v3.14: extracted readable content for finalizer analysis
            "normalized_content": normalized_contents,
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


# ── v3.14: normalized content extraction ──────────────────────────────

_READ_TOOL_PREFIXES = (
    "workspace.readartifact",
    "workspace.file",
    "workspace.knowledge",
)

_NC_EXTRACTION_KEYS = (
    "output.content",
    "output.text",
    "output.preview",
    "content",
    "preview",
    "summary",
)


def _extract_normalized_content(tool: str, result: ToolResult) -> str | None:
    """Extract readable text from read-type tool results.

    Priority order (first non-empty wins):
      1. data.output.content
      2. data.output.text
      3. data.output.preview
      4. data.content
      5. data.preview
      6. data.summary

    Only applies to workspace.readartifact, workspace.file read, and
    workspace.knowledge tools.
    """
    if not any(tool.startswith(prefix) for prefix in _READ_TOOL_PREFIXES):
        return None

    data = result.data
    if not isinstance(data, dict):
        return None

    for key_path in _NC_EXTRACTION_KEYS:
        value = _get_nested(data, key_path)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, list, tuple)):
            return str(value)
    return None


def _get_nested(d: dict[str, Any], key_path: str) -> Any:
    """Traverse nested dict by dotted key path (e.g. 'output.content')."""
    parts = key_path.split(".")
    current: Any = d
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
