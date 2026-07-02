"""
Planner — the single LLM entry point for SSOT Runtime Engine.

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

from .models import PlanNode, SSOTRuntimeConfig, StatelessContext
from .runtime_contracts import (
    ExecutionContract,
    ExecutionObligationViolation,
    PlanSchemaVersion,
    ExecutionSemanticsContract,
    PlanValidationError,
)


PLANNER_SYSTEM_PROMPT = """You are a deterministic execution planner. Your ONLY job is to select
and invoke the tools needed to achieve the user's request.

RULES (non-negotiable):
1. Invoke ALL independent tools in a single response (parallel execution).
2. Only invoke tools that directly help achieve the user's request.
3. If the request requires NO tools (chitchat, definitions, conversation
   references), invoke NO tools — just provide a brief direct answer.
4. When RECENT CONVERSATION HISTORY is present, answer conversation-reference
   queries (e.g. "什么意思", "我上句话说了什么") directly — do NOT invoke any tools.
5. Preserve user intent in tool arguments. Do not drop dates, locations,
   file paths, asset ids, regions, vendors, commands, limits, or output formats.
6. Use the exact parameter names from each tool's definition. Never invent aliases.
7. Keep the tool set minimal — fewer tools = faster execution.

If NO tools are needed, respond with text only (no tool calls)."""


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
        config: SSOTRuntimeConfig,
        available_tools: dict[str, dict[str, Any]],
        llm_invoke: Callable[..., str],
    ):
        self._config = config
        self._available_tools = available_tools
        self._llm_invoke = llm_invoke

    def plan(self, ctx: StatelessContext) -> list[PlanNode]:
        """Generate an execution plan from the user request.

        Sends available tools via Function Calling (not text dump).
        Returns a list of PlanNode objects.
        """
        start = time.monotonic()

        user_prompt = self._build_user_prompt(ctx)
        tools = self._build_openai_tools()

        raw_output = self._llm_invoke(
            system=PLANNER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            timeout=self._config.planner_timeout_ms,
            tools=tools,
        )


        # Clean output: strip markdown fences if present
        cleaned = self._clean_json_output(raw_output)
        data = self._parse_plan_json(cleaned)


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
        enforce_execution_obligation(intent, nodes)

        elapsed = (time.monotonic() - start) * 1000
        ctx.extras["planner_latency_ms"] = elapsed
        ctx.extras["planner_node_count"] = len(nodes)

        return nodes

    def _build_openai_tools(self) -> list[dict[str, Any]]:
        """Build OpenAI Function Calling tool definitions from available tools."""
        from agent.llm.tool_adapter import tool_spec_to_openai_function
        tools = []
        for tool_id, meta in sorted(self._available_tools.items()):
            tools.append(tool_spec_to_openai_function({
                "tool_id": tool_id,
                "input_schema": meta.get("args_schema", {}),
                "description": meta.get("description", ""),
                "risk_level": meta.get("risk_level", "low"),
            }))
        return tools

    def _build_user_prompt(self, ctx: StatelessContext) -> str:
        # ── Conversation history block ──
        context_block = ctx.extras.get("conversation_history_block") or ""

        return f"""WORKSPACE: {ctx.workspace_id}
SESSION: {ctx.session_id}
CWD: {ctx.cwd}
OS: {ctx.os}

{context_block}
USER REQUEST:
{ctx.user_input}

Select the appropriate tools from the available function list to achieve this request.
If no tools are needed, respond with a direct answer."""

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


# ── v4: execution-obligation enforcement ──────────────────────────────
# Imported lazily inside the module body to keep the import
# surface narrow. detect_task_intent is defined in
# ``core.runtime_engine.engine`` and is a pure function with no I/O, so
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
