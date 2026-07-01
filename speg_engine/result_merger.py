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
        normalized_contents: list[dict[str, Any]] = []

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
            # v3.14: structured normalized_content
            "normalized_content": normalized_contents,
            # v3.14 legacy: flat content strings for backward compat
            "normalized_content_texts": [
                nc.get("content", "") for nc in normalized_contents
            ],
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

# Tools that produce readable content for finalizer analysis.
_NC_TOOL_PREFIXES = (
    "workspace.readartifact",
    "workspace.file",
    "workspace.knowledge",
    "workspace.artifact",
    "workspace.document.pdf.extract_text",
    "pcap.manage",
    "config.manage",
    "exec.run",
    "inspection.manage",
    "text.analyze",
    "data.manage",
    "knowledge.manage",
)

# Priority-ordered extraction keys (first non-empty wins).
_NC_EXTRACTION_KEYS = (
    "output.content",
    "output.text",
    "output.preview",
    "output.stdout",
    "output.stderr",
    "output.results_markdown",
    "output.findings",
    "output.report_url",
    "output.result",
    "output.data",
    "content",
    "text",
    "preview",
    "stdout",
    "stderr",
    "summary",
    "findings",
    "results",
    "artifacts",
)

# Inner unwrap keys for nested ToolResult payloads.
_NC_UNWRAP_KEYS = ("output", "content", "result", "data")


def _extract_normalized_content(tool: str, result: ToolResult) -> dict | None:
    """Extract structured readable text from tool results.

    Returns a dict: {node_id, tool, action, content_type, content, source_path}
    or None if no extractable content was found.
    """
    if not any(tool.startswith(prefix) for prefix in _NC_TOOL_PREFIXES):
        return None

    data = result.data
    if not isinstance(data, dict):
        return None

    # Step 1: Try to get the action from args/result metadata
    action = _infer_action(data)

    # Step 2: Unwrap nested payloads
    unwrapped = data
    for key in _NC_UNWRAP_KEYS:
        inner = unwrapped.get(key)
        if isinstance(inner, dict) and inner:
            unwrapped = inner

    # Step 3: Extract content by priority
    content = None
    content_type = ""
    for key_path in _NC_EXTRACTION_KEYS:
        value = _get_nested(unwrapped, key_path)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            content = value.strip()
            content_type = key_path
            break
        if isinstance(value, (int, float, list, tuple, dict)):
            content = str(value)
            content_type = key_path
            break

    if content is None:
        return None

    # Step 4: Extract source_path or artifact_id if available
    source_path = _get_nested(data, "args.file") or _get_nested(data, "args.path") or ""
    artifact_id = _get_nested(data, "args.artifact_id") or ""

    return {
        "node_id": result.node_id,
        "tool": tool,
        "action": action,
        "content_type": content_type,
        "content": content,
        "source_path": str(source_path) if source_path else "",
        "artifact_id": str(artifact_id) if artifact_id else "",
    }


def _infer_action(data: dict) -> str:
    """Infer the action from result data (e.g. 'read', 'search', 'run')."""
    for key in ("action", "args.action", "output.action"):
        val = _get_nested(data, key)
        if isinstance(val, str) and val:
            return val
    return ""


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
