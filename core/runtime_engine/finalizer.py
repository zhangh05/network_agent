"""
Finalizer — optional single LLM call to synthesize results.

Rules:
  - MAX 1 synthesis LLM call
  - No reasoning, no tool calls
  - Pure summary/response generation from structured execution results
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .models import SSOTRuntimeConfig, StatelessContext


FINALIZER_SYSTEM_PROMPT = """You are a final response synthesizer. Your job is to produce a clear,
concise response that COMPLETES the user's original request based on tool execution results.

TASK COMPLETION CONTRACT (non-negotiable):
1. Your target is the ORIGINAL USER REQUEST. You must answer what the user asked.
2. If the user asked to analyse / summarise / draw conclusions / inspect / diagnose /
   generate a report / read and judge — you MUST provide analytical conclusions,
   not just "工具执行成功" or "readartifact completed" or "收到".
3. Tool execution success IS NOT the same as task completion. The user did not ask
   "did the tool run?" — they asked for analysis results.
4. If normalized_content is present, base your analysis on it. Quote relevant data
   points from the content in your response.
5. If normalized_content is empty but the user clearly asked for analysis, explain
   what is missing and why you cannot complete the request.
6. Never output only:
   - "收到" / "已完成" / "工具调用成功" / "No tools were executed" /
     "readartifact completed" / "没有更多信息"
   unless the user's original request was literally "did the tool run?"

OTHER RULES:
- Summarize tool results directly — no preamble, no meta-commentary.
- Use structured data fields before summaries. Prefer ``data_unwrapped`` and
  ``normalized_content`` when present.
- If a result has content such as forecast_daily, current, results_markdown,
  findings, report_url, stdout, artifacts, or next_actions, answer from those fields.
- Do NOT include reasoning or chain-of-thought.
- If tools failed, report failures clearly and explain impact on the user's request.
- For weather forecasts, include every requested day returned by forecast_daily
  up to the user's requested horizon; do not collapse a 10-day request to one day.
- For inspection results, include completion status, counts, critical/warning/info
  findings, failed/skipped devices, next actions, and the HTML report link when present.
- Output format: plain text, well-structured with clear sections if multi-result."""


FINALIZER_RETRY_SYSTEM_PROMPT = """**RETRY — Your previous response was incomplete.**

You are a final response synthesizer. Your previous attempt to answer was rejected
because it was a placeholder response ("收到", "已完成", "工具执行成功" etc.).

MANDATORY REQUIREMENTS:
1. Complete the ORIGINAL USER REQUEST. If they asked for analysis, GIVE ANALYSIS.
2. Base your answer on normalized_content and execution results.
3. You MUST include: a conclusion, key findings, and (if applicable) recommendations.
4. Never output: "收到", "已完成", "工具调用成功", "No tools were executed", or similar.
5. If you truly cannot complete the request, state explicitly what is missing and why.

OTHER RULES:
- Use structured data fields before summaries. Prefer data_unwrapped and normalized_content.
- If tools failed, explain impact on the user's request.
- Output format: plain text, well-structured with clear sections if multi-result."""


class Finalizer:
    """Optional single-call LLM response synthesizer."""

    def __init__(
        self,
        config: SSOTRuntimeConfig,
        llm_invoke: Callable[..., str],
    ):
        self._config = config
        self._llm_invoke = llm_invoke

    async def finalize(
        self,
        ctx: StatelessContext,
        merged_results: dict[str, Any],
        is_retry: bool = False,
    ) -> str:
        """Generate a synthesized response from merged execution results.

        Returns:
            Plain text final response.
        """
        if not self._config.enable_finalizer:
            return self._build_default_response(merged_results)

        start = time.monotonic()

        try:
            user_prompt = self._build_finalizer_prompt(ctx, merged_results)
            system_msg = FINALIZER_SYSTEM_PROMPT
            if is_retry:
                system_msg = FINALIZER_RETRY_SYSTEM_PROMPT
            response = self._llm_invoke(
                system=system_msg,
                user=user_prompt,
                temperature=0.0,
                timeout=self._config.finalizer_timeout_ms,
            )
            elapsed = (time.monotonic() - start) * 1000
            ctx.extras["finalizer_latency_ms"] = elapsed
            return response.strip()
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            ctx.extras["finalizer_latency_ms"] = elapsed
            return self._build_default_response(merged_results)

    def _build_finalizer_prompt(
        self,
        ctx: StatelessContext,
        merged: dict[str, Any],
    ) -> str:
        import json

        # ── Conversation history block ──
        context_block = ctx.extras.get("conversation_history_block") or ""

        # Truncate merged results to avoid blowing context window
        _MAX_RESULTS_CHARS = 12000
        results_json = json.dumps(merged, ensure_ascii=False, default=str, indent=2)
        if len(results_json) > _MAX_RESULTS_CHARS:
            results_json = results_json[:_MAX_RESULTS_CHARS] + "\n...[results truncated to fit context budget]"

        # ── v3.14: normalized_content for analysis tools ────────────
        nc_block = ""
        normalized = merged.get("normalized_content") or []
        if normalized:
            nc_lines = ["NORMALIZED CONTENT (base your analysis on this):"]
            for i, nc in enumerate(normalized, 1):
                if isinstance(nc, str):
                    # Legacy flat string format
                    content = nc[:4000] if len(nc) > 4000 else nc
                    nc_lines.append(f"--- Content block {i} ---")
                    nc_lines.append(content)
                elif isinstance(nc, dict):
                    content = nc.get("content", "")
                    content = content[:4000] if len(content) > 4000 else content
                    tool = nc.get("tool", "?")
                    action = nc.get("action", "")
                    label = f"--- [{tool}]" + (f" action={action}" if action else "") + f" ---"
                    nc_lines.append(label)
                    nc_lines.append(content)
            nc_lines.append("--- End of normalized content ---\n")
            nc_block = "\n".join(nc_lines) + "\n"

        return f"""ORIGINAL USER REQUEST:
{ctx.user_input}

{context_block}
{nc_block}EXECUTION RESULTS ({merged['total_nodes']} nodes, {merged['success_count']} success, {merged['failure_count']} failed):

{results_json}

Synthesize a final response for the user. Remember: your goal is to COMPLETE the user's
original request. If they asked for analysis, provide analysis — not just "tools ran".
If normalized_content is present above, use it as the primary data source for your analysis."""

    def _build_default_response(self, merged: dict[str, Any]) -> str:
        """Build a simple structured response without LLM.

        v3.14: never returns just "No tools were executed." — that
        signal must be accompanied by a failure / incomplete indication.
        """
        total = merged["total_nodes"]
        success = merged["success_count"]
        failed = merged["failure_count"]

        lines = []
        if total == 0:
            lines.append("[TASK_INCOMPLETE] No tools were executed for this request.")

        grouped = merged.get("results_by_category", {})
        for category, items in grouped.items():
            lines.append(f"\n## {category}")
            for item in items:
                status = "OK" if item["success"] else "FAILED"
                data_preview = str(item.get("data", ""))[:200] if item.get("data") else "—"
                lines.append(f"  [{status}] {item['node_id']}: {data_preview}")

        if failed > 0:
            lines.append(f"\n{failed} tool(s) failed.")

        if total == 0:
            lines.append("\nThe system was unable to plan and execute any tools for your request. "
                          "This may indicate that no matching tools are available.")

        return "\n".join(lines).strip()


def _history_block_without_import(history: list[dict[str, str]]) -> str:
    """Format conversation_history entries into a prompt-ready block.

    A local copy so finalizer does not import from fast_path at module
    level (which would create a two-way dependency).  fast_path is only
    imported by engine.py which owns the orchestration.
    """
    if not history:
        return ""
    lines = ["RECENT CONVERSATION HISTORY:"]
    for i, entry in enumerate(history, 1):
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        lines.append(f"  [{i}] {role}: {content}")
    lines.append("")
    return "\n".join(lines)
