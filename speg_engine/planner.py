"""
Planner — the single LLM entry point for SPEG Engine.

Input: user request + minimal static context
Output: strictly structured JSON execution graph

ONE LLM call ONLY. No reasoning, no multi-step thinking, no tool suggestions
outside the graph.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

from .models import PlanNode, SPEGConfig, StatelessContext


PLANNER_SYSTEM_PROMPT = """You are a deterministic execution planner. Your ONLY job is to output a JSON
execution graph that achieves the user's request.

RULES (non-negotiable):
1. Output ONLY valid JSON — no preamble, no explanation, no markdown fences.
2. Every tool you reference MUST exist in the available tools list below.
3. Use deps[] to express dependency: node B depends on node A if B needs A's output.
4. Nodes with NO deps (or shared deps at same depth) WILL execute in parallel.
5. Do NOT chain tools that can run independently.
6. Do NOT include reasoning, suggestions, or anything outside the JSON structure.
7. Each node MUST have: id (string), tool (string), args (object), deps (string array).
8. Node IDs must be unique and descriptive (e.g., "read_config", "ping_device", "analyze_data").
9. Keep the graph as FLAT as possible — fewer depth levels = faster execution.
10. If the request is a simple question requiring no tools, output an empty nodes array
    and put the direct user-facing answer in final_response.
11. Preserve user intent in tool args. Do not drop dates, locations, file paths,
    asset ids, regions, vendors, commands, limits, or requested output formats.
12. Use the exact args_schema fields. Do not invent alias fields.
13. When RECENT CONVERSATION HISTORY is present in the user prompt:
    a. Answer conversation-reference queries (e.g. "什么意思",
       "我上句话说了什么", "你说了什么还记得吗") directly from
       the history — do NOT invoke memory.manage or any other tool.
    b. Put the direct answer in final_response with an empty nodes array.

TOOL PLANNING PLAYBOOK:
- Weather: use web.manage with action="weather".
- Web/docs/news: use web.manage action="search".
- Page fetch/summarize: use web.manage action="page" with url.
- Files: use workspace.file action="read" to read, action="glob" to discover.
  Do NOT use "workspace.readartifact" — that tool does not exist.
- Artifacts/reports: use workspace.artifact action="read".
- PDF text: use workspace.document.pdf.extract_text.
- PCAP/packet analysis: use pcap.manage action="parse" / "session" / "filter".
- Config analysis: use config.manage action="parse" / "diff" / "extract_interfaces".
- Shell: use exec.run. Read-only commands (ping, show, cat) run directly.
  Destructive commands will be blocked or require approval.
- Devices/CMDB: use device.manage.
- Inspection: use inspection.manage action="run" → "task_get" → "report".
- Text analysis: use text.analyze.
- Data management: use data.manage.
- Knowledge: use knowledge.manage action="search" / "read".
- Subagents: use agent.manage only for independent review/search/test.
- Memory: use memory.manage action="search"; create/update only when explicitly asked.

OUTPUT SCHEMA:
{
  "nodes": [
    {
      "id": "unique_node_id",
      "tool": "canonical_tool_id",
      "args": {"param": "value"},
      "deps": ["parent_node_id"]
    }
  ],
  "final_response": "optional direct answer when nodes is empty"
}"""


class Planner:
    """Single-pass planner: 1 LLM call → 1 execution graph."""

    def __init__(
        self,
        config: SPEGConfig,
        available_tools: dict[str, dict[str, Any]],
        llm_invoke: Callable[..., str],
    ):
        self._config = config
        self._available_tools = available_tools
        self._llm_invoke = llm_invoke

    def plan(self, ctx: StatelessContext) -> list[PlanNode]:
        """Generate an execution plan from the user request.

        Returns a list of PlanNode objects.
        Raises ValueError if planner output is invalid.
        """
        start = time.monotonic()

        tools_desc = self._build_tools_description()
        user_prompt = self._build_user_prompt(ctx, tools_desc)

        raw_output = self._llm_invoke(
            system=PLANNER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            timeout=self._config.planner_timeout_ms,
        )

        # Clean output: strip markdown fences if present
        cleaned = self._clean_json_output(raw_output)
        data = self._parse_plan_json(cleaned)
        nodes = self._parse_nodes(data)
        if not nodes:
            direct = data.get("final_response", "")
            if isinstance(direct, str) and direct.strip():
                ctx.extras["direct_response"] = direct.strip()

        elapsed = (time.monotonic() - start) * 1000
        ctx.extras["planner_latency_ms"] = elapsed
        ctx.extras["planner_node_count"] = len(nodes)

        return nodes

    def _build_tools_description(self) -> str:
        lines = ["AVAILABLE TOOLS:"]
        for tool_id, meta in sorted(self._available_tools.items()):
            desc = meta.get("description", tool_id)
            schema = meta.get("args_schema", {})
            schema_str = json.dumps(schema, ensure_ascii=False) if schema else "{}"
            lines.append(f"  {tool_id}: {desc}")
            lines.append(f"    args_schema: {schema_str}")
        return "\n".join(lines)

    def _build_user_prompt(self, ctx: StatelessContext, tools_desc: str) -> str:
        # ── v3.14: Conversation context injection ──────────────────
        # Use ConversationContext.format_for_prompt() which includes
        # session_summary, recent turns, and retrieved_history.
        context_block = ""
        conv_ctx = ctx.extras.get("conversation_context")
        if conv_ctx is not None:
            try:
                context_block = conv_ctx.format_for_prompt()
            except Exception:
                context_block = ""

        # Fallback: plain conversation_history if conv_ctx not set
        if not context_block:
            conv_history = ctx.extras.get("conversation_history") or []
            if conv_history:
                from .fast_path import _build_conversation_history_block
                context_block = _build_conversation_history_block(conv_history)

        return f"""WORKSPACE: {ctx.workspace_id}
SESSION: {ctx.session_id}
CWD: {ctx.cwd}
OS: {ctx.os}

{context_block}
USER REQUEST:
{ctx.user_input}

{tools_desc}

Generate the execution graph JSON now. No explanation, no markdown — pure JSON only."""

    def _clean_json_output(self, raw: str) -> str:
        """Strip markdown code fences, trim whitespace."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _parse_plan_json(self, raw: str) -> dict[str, Any]:
        """Parse planner LLM output."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Planner output is not valid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(f"Planner output must be a JSON object, got {type(data).__name__}")
        return data

    def _parse_nodes(self, data: dict[str, Any]) -> list[PlanNode]:
        """Parse and validate planner nodes from a JSON object."""
        raw_nodes = data.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise ValueError(f"'nodes' must be a JSON array, got {type(raw_nodes).__name__}")

        nodes = []
        for i, n in enumerate(raw_nodes):
            if not isinstance(n, dict):
                raise ValueError(f"Node at index {i} must be a JSON object")

            node_id = n.get("id", "")
            if not node_id or not isinstance(node_id, str):
                raise ValueError(f"Node at index {i} missing valid 'id' field")

            tool = n.get("tool", "")
            if not tool or not isinstance(tool, str):
                raise ValueError(f"Node '{node_id}' missing valid 'tool' field")

            args = n.get("args", {})
            if not isinstance(args, dict):
                raise ValueError(f"Node '{node_id}' args must be an object")

            deps = n.get("deps", [])
            if not isinstance(deps, list):
                raise ValueError(f"Node '{node_id}' deps must be an array")

            nodes.append(PlanNode(id=node_id, tool=tool, args=args, deps=deps))

        return nodes
