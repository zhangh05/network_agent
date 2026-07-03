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
from .tracking import extract_tracking_payload, normalize_tracking_payload


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
        tracking_events: list[dict[str, Any]] = []
        tracking_summary: dict[str, Any] = {}

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

            # ── v3.15: normalized_content extraction ────────────────
            nc = _extract_normalized_content(node, result)
            if nc:
                normalized_contents.append(nc)
            tracking = extract_tracking_payload(result.data)
            if tracking:
                tracking_events.append({
                    "node_id": node.id,
                    "tool": node.tool,
                    "tracking": tracking,
                })
                tracking_summary = normalize_tracking_payload(tracking)

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
            "retry_summary": ctx.extras.get("retry_summary", {
                "retry_attempts": 0,
                "retried_nodes": [],
                "retry_succeeded": 0,
                "retry_failed": 0,
                "retry_blocked": 0,
            }),
            "retry_events": ctx.extras.get("retry_events", []),
            "tracking_summary": tracking_summary,
            "tracking_events": tracking_events,
        }
        if tracking_summary:
            ctx.extras["tracking_summary"] = tracking_summary
            ctx.extras["tracking_events"] = tracking_events

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
    "web.manage",
    "device.manage",
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
    "output.forecast_daily",
    "output.current",
    "output.items",
    "output.results",
    "output.assets",
    "output.findings",
    "output.report_url",
    "output.result",
    "output.data",
    "content",
    "text",
    "preview",
    "stdout",
    "stderr",
    "results_markdown",
    "forecast_daily",
    "current",
    "assets",
    "items",
    "summary",
    "findings",
    "results",
    "artifacts",
)

# Inner unwrap keys for nested ToolResult payloads.
_NC_UNWRAP_KEYS = ("output", "content", "result", "data")


def _extract_normalized_content(node, result: ToolResult) -> dict | None:
    """Extract structured readable text from tool results.

    Accepts the full ExecutionNode so source_path/artifact_id/action
    can be read from ``node.args`` (not guessed from result.data).

    Returns a dict: {node_id, tool, action, content_type, content,
                     source_path, artifact_id, success, error}
    or None if no extractable content was found.
    """
    tool = getattr(node, "tool", "")
    if not any(tool.startswith(prefix) for prefix in _NC_TOOL_PREFIXES):
        return None

    data = result.data
    if not isinstance(data, dict):
        # Non-dict data: wrap as simple content
        return {
            "node_id": result.node_id,
            "tool": tool,
            "action": _get_node_arg(node, "action"),
            "content_type": "plain",
            "content": str(data) if data else "",
            "source_path": _get_node_arg(node, "file") or _get_node_arg(node, "path"),
            "artifact_id": _get_node_arg(node, "artifact_id"),
            "success": result.success,
            "error": result.error or "",
        }

    # ── Step 1: Read from node.args (preferred) ──────────────────
    action = (_get_node_arg(node, "action") or _infer_action_from_data(data))
    source_path = (
        _get_node_arg(node, "file")
        or _get_node_arg(node, "path")
        or _get_node_arg(node, "filepath")
        or _get_nested(data, "args.file")
        or _get_nested(data, "args.path")
        or ""
    )
    artifact_id = (
        _get_node_arg(node, "artifact_id")
        or _get_nested(data, "args.artifact_id")
        or ""
    )

    # ── Step 2: Unwrap nested payloads ───────────────────────────
    unwrapped = data
    for key in _NC_UNWRAP_KEYS:
        inner = unwrapped.get(key)
        if isinstance(inner, dict) and inner:
            unwrapped = inner

    # ── Step 3: Extract content by priority ──────────────────────
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

    # ── Step 4: Failed tool? Include error for explanation ───────
    if content is None and result.error:
        content = f"[FAILED] {result.error}"
        content_type = "error"

    if content is None:
        return None

    return {
        "node_id": result.node_id,
        "tool": tool,
        "action": action,
        "content_type": content_type,
        "content": content,
        "source_path": str(source_path) if source_path else "",
        "artifact_id": str(artifact_id) if artifact_id else "",
        "success": result.success,
        "error": result.error or "",
    }


def _get_node_arg(node, key: str) -> str:
    """Safely read an arg from an ExecutionNode (or dict/object)."""
    args = getattr(node, "args", None)
    if isinstance(args, dict):
        val = args.get(key, "")
        if isinstance(val, str):
            return val
    return ""


def _infer_action_from_data(data: dict) -> str:
    """Fallback: infer action from result data."""
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
