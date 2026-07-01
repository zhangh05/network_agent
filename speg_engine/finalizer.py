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

from .models import SPEGConfig, StatelessContext


FINALIZER_SYSTEM_PROMPT = """You are a final response synthesizer. Your job is to produce a clear,
concise response to the user based on tool execution results.

RULES:
1. Summarize the tool results directly — no preamble, no meta-commentary.
2. Do NOT suggest additional tools or next steps.
3. Do NOT include reasoning or chain-of-thought.
4. If tools failed, report failures clearly and concisely.
5. Output format: plain text, well-structured with clear sections if multi-result."""


class Finalizer:
    """Optional single-call LLM response synthesizer."""

    def __init__(
        self,
        config: SPEGConfig,
        llm_invoke: Callable[..., str],
    ):
        self._config = config
        self._llm_invoke = llm_invoke

    async def finalize(
        self,
        ctx: StatelessContext,
        merged_results: dict[str, Any],
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
            response = self._llm_invoke(
                system=FINALIZER_SYSTEM_PROMPT,
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

        results_json = json.dumps(merged, ensure_ascii=False, default=str, indent=2)

        return f"""ORIGINAL USER REQUEST:
{ctx.user_input}

EXECUTION RESULTS ({merged['total_nodes']} nodes, {merged['success_count']} success, {merged['failure_count']} failed):

{results_json}

Synthesize a final response for the user. Be concise and direct."""

    def _build_default_response(self, merged: dict[str, Any]) -> str:
        """Build a simple structured response without LLM."""
        total = merged["total_nodes"]
        success = merged["success_count"]
        failed = merged["failure_count"]

        lines = []
        if total == 0:
            lines.append("No tools were executed.")

        grouped = merged.get("results_by_category", {})
        for category, items in grouped.items():
            lines.append(f"\n## {category}")
            for item in items:
                status = "OK" if item["success"] else "FAILED"
                data_preview = str(item.get("data", ""))[:200] if item.get("data") else "—"
                lines.append(f"  [{status}] {item['node_id']}: {data_preview}")

        if failed > 0:
            lines.append(f"\n{failed} tool(s) failed.")

        return "\n".join(lines).strip()
