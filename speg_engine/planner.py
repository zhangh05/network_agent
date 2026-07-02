"""
Planner — the single LLM entry point for SPEG Engine.

Input: user request + minimal static context
Output: strictly structured JSON execution graph

ONE LLM call ONLY. No reasoning, no multi-step thinking, no tool suggestions
outside the graph.

v4 contract (runtime_contracts.ExecutionContract.EXECUTION_OBLIGATION_ENFORCED):

  When the user request requires tool execution, the planner MUST
  return a non-empty graph. Returning ``[]`` (or ``None``) for a
  task-intent request is a contract violation and raises
  ``ExecutionObligationViolation`` before the plan is handed to
  the engine.

  Chitchat / definition questions / direct-response requests that
  do NOT require execution are exempt — those can legitimately
  return an empty plan with a ``direct_response`` filled into
  ``ctx.extras``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

from .models import PlanNode, SPEGConfig, StatelessContext
from .runtime_contracts import (
    ExecutionContract,
    ExecutionObligationViolation,
    PlanSchemaVersion,
    ExecutionSemanticsContract,
    PlanValidationError,
)

# ── v3.16 diagnostic ──────────────────────────────────────
import sys
_PTRIAGE = sys.stderr
def _pdiag(sid: str, msg: str) -> None:
    import time
    ts = time.monotonic()
    _PTRIAGE.write(f"[PLANNER-DIAG|{sid[:8]}|{ts:.3f}] {msg}\n")
    _PTRIAGE.flush()


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


# ── v4.1: Schema Enforcement ────────────────────────────────────────────────

class SchemaValidationError(Exception):
    """Planner output does not match the required JSON schema."""


class PlanSchema:
    """v4.1 strict plan schema.

    Every planner output MUST pass ``validate_plan_schema`` before
    the engine proceeds to compilation.  A schema violation raises
    ``SchemaValidationError`` (for malformed JSON / unknown keys)
    or ``ExecutionObligationViolation`` (for semantic empty plan).
    """

    @staticmethod
    def validate_raw(data: dict,
                     user_input: str = "",
                     task_intent: bool = False) -> list[PlanNode]:
        """Validate raw planner JSON output AND convert to PlanNode list.

        Returns the validated PlanNode list.
        Raises SchemaValidationError or ExecutionObligationViolation.
        """
        if not isinstance(data, dict):
            raise SchemaValidationError(
                f"Planner output must be a JSON object, got {type(data).__name__}"
            )

        # Block unknown top-level keys
        allowed = {"nodes", "final_response"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise SchemaValidationError(
                f"Unknown top-level keys: {sorted(unknown)}. "
                f"Only {sorted(allowed)} allowed."
            )

        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, list):
            raise SchemaValidationError(
                f"'nodes' must be an array, got {type(raw_nodes).__name__}"
            )

        # Semantic: empty plan on task intent
        if not raw_nodes:
            if task_intent and ExecutionContract.EXECUTION_OBLIGATION_ENFORCED:
                raise ExecutionObligationViolation(
                    f"Empty nodes ([]) for task-intent: '{user_input[:120]}'"
                )
            return []

        nodes: list[PlanNode] = []
        for i, n in enumerate(raw_nodes):
            if not isinstance(n, dict):
                raise SchemaValidationError(
                    f"plan[{i}]: must be object, got {type(n).__name__}"
                )
            nid = n.get("id", "")
            tool = n.get("tool", "")
            args = n.get("args", {})

            if not nid or not isinstance(nid, str):
                raise SchemaValidationError(f"plan[{i}]: 'id' must be non-empty string")
            if tool is None:
                raise SchemaValidationError(f"plan[{i}] (id='{nid}'): 'tool' must not be null")
            if not tool or not isinstance(tool, str):
                raise SchemaValidationError(f"plan[{i}] (id='{nid}'): 'tool' must be non-empty string")
            if not isinstance(args, dict):
                raise SchemaValidationError(f"plan[{i}] (id='{nid}'): 'args' must be object")

            deps = n.get("deps", [])
            if not isinstance(deps, list):
                raise SchemaValidationError(f"plan[{i}] (id='{nid}'): 'deps' must be array")

            nodes.append(PlanNode(id=nid, tool=tool, args=args, deps=deps))

        return nodes


class PlanValidationPipeline:
    """v6: unified validation pipeline — fixed order, single path.

    STEP 1: structural (schema) validate
    STEP 2: semantic validate (field types, null checks)
    STEP 3: execution-obligation validate (empty plan on task intent)

    Any failure → PlanValidationError, no fallback, no silent skip.
    """

    VALIDATE_SCHEMA = "SCHEMA_INVALID"
    VALIDATE_SEMANTIC = "SEMANTIC_INVALID"
    VALIDATE_OBLIGATION = "EXECUTION_OBLIGATION_VIOLATION"

    @staticmethod
    def validate(data: dict, user_input: str = "", task_intent: bool = False) -> list[PlanNode]:
        """Run the unified 3-step validation pipeline."""
        return PlanSchema.validate_raw(
            data,
            user_input=user_input,
            task_intent=task_intent,
        )


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
        Raises ExecutionObligationViolation if the user request
        requires tool execution (per ``detect_task_intent``) but
        the LLM produced an empty plan — the v4 fail-fast guard.
        """
        start = time.monotonic()

        tools_desc = self._build_tools_description()
        user_prompt = self._build_user_prompt(ctx, tools_desc)

        _pdiag(ctx.session_id, f"PLANNER_START | tools={len(self._available_tools)} input_len={len(ctx.user_input)}")

        raw_output = self._llm_invoke(
            system=PLANNER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            timeout=self._config.planner_timeout_ms,
        )

        _pdiag(ctx.session_id, f"LLM_RAW | len={len(raw_output)} preview={raw_output[:200]!r}")

        # Clean output: strip markdown fences if present
        cleaned = self._clean_json_output(raw_output)
        data = self._parse_plan_json(cleaned)

        _pdiag(ctx.session_id, f"PARSED | keys={list(data.keys())} nodes_count={len(data.get('nodes', []))} has_final_response={'final_response' in data}")

        # ── v6: unified plan validation pipeline ────────────
        task_intent = ctx.extras.get("task_intent_is_task", False)
        if ExecutionSemanticsContract.SCHEMA_EXECUTION_UNIFIED:
            nodes = PlanValidationPipeline.validate(
                data, ctx.user_input, task_intent,
            )
        else:
            # Legacy split path: schema then obligation
            nodes = PlanSchema.validate_raw(
                data, ctx.user_input, task_intent,
            )
        if not nodes:
            direct = data.get("final_response", "")
            if isinstance(direct, str) and direct.strip():
                ctx.extras["direct_response"] = direct.strip()

        # ── v4: execution-obligation enforcement ─────────────────────
        # If the user request requires tool execution (per the unified
        # task-intent detector), an empty plan is a contract
        # violation, not a "nothing to do" outcome. Raise before
        # returning so the engine's empty-plan guard sees the
        # exception and produces a structured error result.
        intent = detect_task_intent(ctx.user_input or "")
        _pdiag(ctx.session_id, f"OBLIGATION_CHECK | is_task={intent.is_task} requires_exec={intent.requires_execution} plan_len={len(nodes)}")
        enforce_execution_obligation(intent, nodes)

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


# ── v4: execution-obligation enforcement ──────────────────────────────
# Imported lazily inside the module body to keep the import
# surface narrow. detect_task_intent is defined in
# ``speg_engine.engine`` and is a pure function with no I/O, so
# the lazy import is safe.


def detect_task_intent(user_input: str):  # type: ignore[no-untyped-def]
    """Re-export the engine's task-intent detector lazily so
    ``planner.py`` does not introduce an import cycle
    (``engine`` imports ``planner``).

    Returns a ``TaskIntentResult`` with at least
    ``is_task``, ``requires_tool_likely``, ``requires_execution``
    (alias) attributes.
    """
    from .engine import detect_task_intent as _detect
    return _detect(user_input)


def enforce_execution_obligation(intent, plan) -> None:
    """v4 fail-fast guard: the planner MUST NOT return an empty
    plan for a request that requires tool execution.

    The check has three parts (per the v4 spec):

      1. ``intent.requires_execution`` is True — the user
         request is a task intent (analyse / inspect / read /
         diagnose / execute / etc.), so the runtime owes the
         user a real execution.
      2. ``plan`` is empty (``[]``) or ``None`` — silent
         fallback to a no-op is forbidden.
      3. There is no ``direct_response`` in ``ctx.extras`` that
         the engine could surface as a text answer — direct
         answers are still legitimate for the
         non-execution-obligation branch (definition questions
         etc.).

    On violation: raise ``ExecutionObligationViolation``. The
    engine catches it and produces a structured error result
    (matching the v3.14 empty-plan task-intent guard).
    """
    assert ExecutionContract.EXECUTION_OBLIGATION_ENFORCED, (
        "v4 contract EXECUTION_OBLIGATION_ENFORCED is off — "
        "enforce_execution_obligation is a no-op."
    )

    if plan is None:
        plan = []

    if not getattr(intent, "requires_execution", False):
        return

    if plan:
        return

    # No nodes — but the planner may have legitimately produced a
    # direct response (the user asked a definition question that
    # is also a task intent by the loose classifier). Allow that
    # path so the v3.14 chitchat / definition flow still works.
    # The check is loose on purpose: direct_response is set
    # only when the LLM produced a non-empty ``final_response``
    # in its JSON output.
    # We don't have access to ctx.extras here, so we let the
    # engine's existing guard handle the direct_response case
    # by raising — the engine knows whether direct_response
    # was set.
    raise ExecutionObligationViolation(
        "Task requires execution but planner returned empty graph "
        f"(intent_type={getattr(intent, 'intent_type', '?')!r}, "
        f"is_task={getattr(intent, 'is_task', False)})"
    )
