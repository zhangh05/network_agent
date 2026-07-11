"""
QueryLoop — iterative LLM + tool execution engine.

The single tool-capable runtime loop merges planning and finalization,
feeds tool results back for iterative refinement, tracks long tasks,
records retry metadata, and auto-compacts long conversations.

Optimizations:
  1. Prompt Cache — static system+tools prefix never changes
  2. Planner+Finalizer merge — one LLM call per iteration
  3. Iterative execution — tool results feed back for dynamic decisions
  4. Streaming tool exec — tools start during LLM output
  5. Auto-compact — summarise old turns when context grows
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from dataclasses import asdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .models import (
    ExecutionNode,
    ExecutionStatus,
    SSOTRuntimeConfig,
    StatelessContext,
    ToolResult,
)
from .tracking import extract_tracking_payload, normalize_tracking_payload
from agent.llm.schemas import LLMMessage, LLMResponse, LLMToolCall
from agent.llm.tool_adapter import tool_spec_to_openai_function
from .prompt_contract import (
    FINAL_RESPONSE_PROMPT,
    RUNTIME_SYSTEM_PROMPT,
    build_runtime_system_prompt,
    build_turn_message,
)


# ── Prompt Cache ────────────────────────────────────────────────────────────

# Static prefix that never changes between turns — cached by the LLM API.
# Keep this concise: the full tool catalog is already supplied through the
# function-calling tools field on every planner call.
QUERY_LOOP_SYSTEM_PROMPT = RUNTIME_SYSTEM_PROMPT
QUERY_LOOP_FINALIZER_PROMPT = FINAL_RESPONSE_PROMPT

FINAL_RESPONSE_ONLY_MARKER = "[FINAL_RESPONSE_ONLY]"


_TOOL_DEFINITION_CACHE: dict[str, List[dict]] = {}


def _tool_meta_get(meta: Any, key: str, default: Any = None) -> Any:
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _tool_registry_signature(tool_registry: dict) -> str:
    """Stable hash for the LLM-visible tool surface."""
    payload = []
    for tool_id, meta in sorted(tool_registry.items()):
        payload.append({
            "tool_id": tool_id,
            "description": _tool_meta_get(meta, "description", ""),
            "args_schema": _tool_meta_get(meta, "args_schema", _tool_meta_get(meta, "input_schema", {})),
            "risk_level": _tool_meta_get(meta, "risk_level", "low"),
        })
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_cached_tool_definitions(tool_registry: dict) -> List[dict]:
    """Build tool definitions with stable ordering for prompt caching."""
    signature = _tool_registry_signature(tool_registry)
    cached = _TOOL_DEFINITION_CACHE.get(signature)
    if cached is not None:
        return copy.deepcopy(cached)

    tools = []
    for tool_id, meta in sorted(tool_registry.items()):
        tools.append(tool_spec_to_openai_function({
            "tool_id": tool_id,
            "input_schema": _tool_meta_get(meta, "args_schema", _tool_meta_get(meta, "input_schema", {})),
            "description": _tool_meta_get(meta, "description", ""),
            "risk_level": _tool_meta_get(meta, "risk_level", "low"),
        }))
    _TOOL_DEFINITION_CACHE.clear()
    _TOOL_DEFINITION_CACHE[signature] = copy.deepcopy(tools)
    return tools


TOOL_MESSAGE_MAX_CHARS = 6000     # Per-tool output cap fed to LLM; balances article coverage vs context pressure
ARTIFACT_ANALYSIS_MAX_CHARS = 28_000
FINALIZER_TOOL_MAX_CHARS = 3000
FALLBACK_TOOL_MAX_CHARS = 1600
MAX_INLINE_STRING_CHARS = 3000    # Per-string-value cap in compacted output
MAX_INLINE_LIST_ITEMS = 8
MAX_VALIDATION_CORRECTION_ROUNDS = 3

_PRIORITY_OUTPUT_KEYS = (
    "ok", "status", "summary", "message", "error", "reason",
    "task_id", "task", "tracking", "progress", "done",
    "report_url", "html_url", "artifact_url", "url",
    "count", "total", "success", "failed", "skipped",
    "title", "name", "format",
)


def _compact_value_for_llm(value: Any, *, depth: int = 0) -> Any:
    """Compact tool outputs while preserving facts the model needs next."""
    if depth >= 4:
        text = str(value)
        return text[:MAX_INLINE_STRING_CHARS] + ("... [truncated]" if len(text) > MAX_INLINE_STRING_CHARS else "")
    if isinstance(value, str):
        return value[:MAX_INLINE_STRING_CHARS] + ("... [truncated]" if len(value) > MAX_INLINE_STRING_CHARS else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        compacted = [
            _compact_value_for_llm(item, depth=depth + 1)
            for item in value[:MAX_INLINE_LIST_ITEMS]
        ]
        if len(value) > MAX_INLINE_LIST_ITEMS:
            compacted.append({"_omitted_items": len(value) - MAX_INLINE_LIST_ITEMS})
        return compacted
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        seen: set[str] = set()
        for key in _PRIORITY_OUTPUT_KEYS:
            if key in value:
                result[key] = _compact_value_for_llm(value[key], depth=depth + 1)
                seen.add(key)
        for key, val in value.items():
            if key in seen:
                continue
            result[str(key)] = _compact_value_for_llm(val, depth=depth + 1)
        return result
    return str(value)


def _json_compact(value: Any, *, max_chars: int = TOOL_MESSAGE_MAX_CHARS) -> str:
    """JSON serialize compacted output with a hard cap."""
    compacted = _compact_value_for_llm(value)
    text = json.dumps(
        compacted,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [truncated {len(text) - max_chars} chars]"


def _compact_tool_content(content: Any, *, max_chars: int = TOOL_MESSAGE_MAX_CHARS) -> str:
    """Compact existing tool-message content without double-encoding JSON."""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return _json_compact(parsed, max_chars=max_chars)
    return _json_compact(content, max_chars=max_chars)


def _artifact_analysis_content(payload: dict[str, Any]) -> str:
    """Preserve a bounded complete text artifact for one-pass analysis."""
    preview = str(payload.get("preview") or "")
    complete = bool(payload.get("content_complete", False))
    if len(preview) > ARTIFACT_ANALYSIS_MAX_CHARS:
        preview = preview[:ARTIFACT_ANALYSIS_MAX_CHARS]
        complete = False
    compacted = _compact_value_for_llm({
        key: value for key, value in payload.items() if key != "preview"
    })
    compacted["preview"] = preview
    compacted["content_complete"] = complete
    compacted["content_returned_chars"] = len(preview)
    return json.dumps(
        compacted,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


# ── Auto-Compact ────────────────────────────────────────────────────────────

COMPACT_THRESHOLD_CHARS = 40_000  # ~10K tokens
COMPACT_KEEP_LAST_N = 6           # Keep last N messages intact
COMPACT_HEAD_N = 2                # Keep first N (system + user request)


@dataclass
class CompactInfo:
    """Structured record of a compaction event — surfaced to metrics and LLM."""
    compacted: bool = False
    before_chars: int = 0
    after_chars: int = 0
    removed: int = 0
    saved_chars: int = 0
    tools_used: list[str] = field(default_factory=list)
    tool_stats: dict[str, dict] = field(default_factory=dict)  # {tool_name: {ok: N, failed: N}}
    key_hints: list[str] = field(default_factory=list)


def _estimate_chars(messages: List[LLMMessage]) -> int:
    """Rough character count of all messages, including tool_call JSON."""
    total = 0
    for m in messages:
        content = m.content
        if isinstance(content, list):
            total += sum(len(str(p.get("text", ""))) for p in content if isinstance(p, dict))
        else:
            total += len(str(content or ""))
        if m.tool_calls:
            total += len(json.dumps(m.tool_calls, ensure_ascii=False, default=str))
    return total


def _compact_messages(messages: List[LLMMessage]) -> tuple[List[LLMMessage], CompactInfo]:
    """Compact old messages. Returns (compacted_messages, CompactInfo)."""
    info = CompactInfo()

    if len(messages) <= COMPACT_KEEP_LAST_N + COMPACT_HEAD_N:
        return messages, info

    head = messages[:COMPACT_HEAD_N]
    tail = messages[-COMPACT_KEEP_LAST_N:]
    middle = messages[len(head):-len(tail) or None]

    middle_count = len(middle)
    if middle_count <= 1:
        return messages, info

    # ── Collect tool statistics from middle messages ──
    tool_names: list[str] = []
    tool_stats: dict[str, dict] = {}
    for m in middle:
        if not m.tool_calls:
            continue
        for tc in m.tool_calls:
            name = tc.get("name", tc.get("function", {}).get("name", ""))
            if not name:
                continue
            if name not in tool_names:
                tool_names.append(name)
            if name not in tool_stats:
                tool_stats[name] = {"ok": 0, "failed": 0, "total": 0}
            tool_stats[name]["total"] += 1
            result = tc.get("result") or tc.get("output") or {}
            if isinstance(result, dict):
                if result.get("ok", True):
                    tool_stats[name]["ok"] += 1
                else:
                    tool_stats[name]["failed"] += 1

    # ── Extract key hints from tool_calls results ──
    key_hints: list[str] = []
    for m in middle:
        if not m.tool_calls:
            continue
        # Check tool result dicts for _hint
        if isinstance(m.content, str):
            for found in re.findall(r'_hint["\':\s]*["\']([^"\']+)["\']', m.content):
                key_hints.append(found)
                if len(key_hints) >= 3:
                    break
        if len(key_hints) >= 3:
            break

    # ── Build compact summary ──
    before = _estimate_chars(messages)
    summary = _build_compact_summary(middle_count, tool_names, tool_stats, key_hints)
    compacted = head + [LLMMessage(role="user", content=summary)] + tail
    after = _estimate_chars(compacted)

    info.compacted = True
    info.before_chars = before
    info.after_chars = after
    info.removed = middle_count
    info.saved_chars = before - after
    info.tools_used = tool_names
    info.tool_stats = tool_stats
    info.key_hints = key_hints
    return compacted, info


def _build_compact_summary(
    turns: int, tools: list[str], tool_stats: dict, hints: list[str],
) -> str:
    """Build an LLM-readable compact summary with tool stats and key findings."""
    parts = [f"[{turns} earlier turns compacted."]

    # Tool usage summary
    if tool_stats:
        tool_parts = []
        for name in tools[:6]:
            stats = tool_stats.get(name, {})
            ok = stats.get("ok", 0)
            failed = stats.get("failed", 0)
            if failed:
                tool_parts.append(f"{name}: {ok}✓ {failed}✗")
            else:
                tool_parts.append(f"{name}: {ok} calls")
        if tool_parts:
            parts.append("Tools: " + ", ".join(tool_parts) + ".")

    # Key findings
    if hints:
        parts.append("Key findings: " + "; ".join(hints[:3]) + ".")

    parts.append("Full context in latest messages below.]")
    return " ".join(parts)


# ── Streaming Tool Executor ─────────────────────────────────────────────────

@dataclass
class StreamingToolResult:
    tool_name: str
    call_id: str
    output: dict
    ok: bool
    error: Optional[str] = None
    latency_ms: float = 0.0


class StreamingToolExecutor:
    """Execute tools as they arrive from the LLM stream.

    Read-only tools run in parallel; write tools serialised.
    """

    _ALWAYS_READ_ONLY_TOOLS = {
        "code.search",
        "text.analyze",
        "skill.manage",
        "workspace.metadata.get",
        "workspace.document.pdf.extract_text",
        "web.manage",
    }
    _READ_ONLY_ACTIONS = {
        "agent.manage": {"list", "get", "status"},
        "device.manage": {"list", "get", "export"},
        "git.manage": {"status", "log", "diff"},
        "inspection.manage": {"list", "get", "task_get", "profiles"},
        "knowledge.manage": {"search", "read", "list", "chunk"},
        "memory.manage": {"search", "review", "profile_get"},
        "system.manage": {
            "diagnostics", "health", "selfcheck", "local_info", "tasks",
            "audit_log", "run_get", "session_get", "session_snapshot",
            "review_list",
        },
        "workspace.artifact": {"list", "read"},
        "workspace.file": {"list", "read", "read_image", "glob"},
    }

    def __init__(self, tool_runtime, config: SSOTRuntimeConfig | None = None, emitter=None):
        self._runtime = tool_runtime
        self._config = config or SSOTRuntimeConfig()
        self._emitter = emitter
        self.max_parallel_width = 0

    def _is_read_only_call(self, tool_call: LLMToolCall) -> bool:
        """Classify concurrency from the canonical tool action.

        Merged tools contain both read and write actions, so tool-id-only
        classification is unsafe. Unknown or missing actions are serialized.
        """
        normalized = tool_call.name.replace("__", ".")
        if normalized in self._ALWAYS_READ_ONLY_TOOLS:
            return True
        action = str((tool_call.arguments or {}).get("action") or "").lower()
        return action in self._READ_ONLY_ACTIONS.get(normalized, set())

    async def execute(
        self,
        tool_calls: List[LLMToolCall],
        *,
        ctx: StatelessContext | None = None,
        budget=None,
    ) -> List[StreamingToolResult]:
        """Execute tool calls. Read-only parallel, writes serialised.

        Returns results in the ORIGINAL tool_calls order so callers can
        safely zip(results, tool_calls) for idempotent-key tracking.
        """
        # Build result map keyed by call_id so we can return in original order.
        # Consecutive reads may run together, but every write is an ordering
        # barrier. Executing all reads before all writes changes semantics for
        # batches such as [read, write, read].
        result_by_id: dict[str, StreamingToolResult] = {}

        async def execute_read_group(group: list[LLMToolCall]) -> None:
            if not group:
                return
            self.max_parallel_width = max(self.max_parallel_width, len(group))
            tasks = [self._execute_one(tc, ctx=ctx, budget=budget) for tc in group]
            # return_exceptions=True: collect every result, even if some fail
            ro_results = await asyncio.gather(*tasks, return_exceptions=True)
            for tc, r in zip(group, ro_results):
                if isinstance(r, Exception):
                    result_by_id[tc.id] = StreamingToolResult(
                        tool_name=tc.name,
                        call_id=tc.id,
                        output={},
                        ok=False,
                        error=str(r),
                    )
                else:
                    result_by_id[tc.id] = r

        read_group: list[LLMToolCall] = []
        for tc in tool_calls:
            if self._is_read_only_call(tc):
                read_group.append(tc)
                continue
            await execute_read_group(read_group)
            read_group = []
            self.max_parallel_width = max(self.max_parallel_width, 1)
            result_by_id[tc.id] = await self._execute_one(tc, ctx=ctx, budget=budget)
        await execute_read_group(read_group)

        # Return in original order
        return [result_by_id[tc.id] for tc in tool_calls]

    async def _execute_one(
        self,
        tc: LLMToolCall,
        *,
        ctx: StatelessContext | None = None,
        budget=None,
    ) -> StreamingToolResult:
        """Execute a single tool call via the tool runtime client."""
        tool_id = tc.name.replace("__", ".")
        if ctx is not None and hasattr(self._runtime, "execute_node"):
            node = ExecutionNode(
                id=tc.id,
                tool=tool_id,
                args=dict(tc.arguments or {}),
                depth=0,
            )
            result = await self._runtime.execute_node(node, ctx, {})
            if not result.success:
                result = await self._maybe_retry_node(node, ctx, result, budget)
            return self._from_tool_result(result, fallback_call_id=tc.id)

        try:
            # Map LLM name (dots → underscores) back to canonical tool_id
            _t0 = time.monotonic()
            result = await asyncio.to_thread(
                self._runtime.invoke_raw, tool_id, tc.arguments
            )
            _latency = (time.monotonic() - _t0) * 1000
            return StreamingToolResult(
                tool_name=tool_id,
                call_id=tc.id,
                output=result,
                ok=result.get("ok", False),
                error=result.get("error"),
                latency_ms=float(_latency),
            )
        except Exception as e:
            return StreamingToolResult(
                tool_name=tc.name,
                call_id=tc.id,
                output={},
                ok=False,
                error=str(e),
            )

    async def _maybe_retry_node(
        self,
        node: ExecutionNode,
        ctx: StatelessContext,
        original_result: ToolResult,
        budget,
    ) -> ToolResult:
        from .contracts import get_contract
        from .tool_retry_policy import should_retry_tool_failure

        contract = get_contract(node.tool)
        current_result = original_result
        total_latency_ms = float(original_result.latency_ms or 0.0)

        while not current_result.success:
            error_code = self._retry_error_code(current_result)
            budget_ok = bool(budget.check_execution().ok) if budget is not None else True
            decision = should_retry_tool_failure(
                node=node,
                tool_contract=contract,
                error_code=error_code,
                error_message=current_result.error or "",
                config_max_retries=(
                    int(getattr(contract, "max_retries", 0) or 0)
                    if contract is not None else 0
                ),
                global_max_retries_per_node=self._config.max_retries_per_node,
                budget_ok=budget_ok,
            )
            event_index = self._record_retry_decision(ctx, node, decision)
            if not decision.retry_allowed:
                return current_result

            await asyncio.sleep(decision.backoff_ms / 1000.0)
            # A retry that was legal before backoff may no longer fit in the
            # request budget afterwards. Never start it once the deadline has
            # elapsed.
            if budget is not None and not budget.check_execution().ok:
                self._record_retry_aborted(ctx, event_index, "budget_exceeded_after_backoff")
                return current_result

            node.retry_count += 1
            retry_started = time.monotonic()
            current_result = await self._runtime.execute_node(node, ctx, {})
            retry_duration_ms = (time.monotonic() - retry_started) * 1000
            total_latency_ms += retry_duration_ms + float(decision.backoff_ms)
            current_result.retry_count = node.retry_count
            current_result.metadata = dict(current_result.metadata or {})
            current_result.metadata.update({
                "retried": True,
                "retry_count": node.retry_count,
                "retry_reason": decision.reason,
                "retry_backoff_ms": decision.backoff_ms,
                "retry_error_code": decision.error_code,
                "retry_original_error": decision.notes.get("original_error", ""),
                "retry_total_latency_ms": total_latency_ms,
            })
            self._record_retry_result(
                ctx, node, current_result,
                event_index=event_index,
                duration_ms=retry_duration_ms,
            )

        return current_result

    @staticmethod
    def _retry_error_code(result: ToolResult) -> str:
        error_code = (result.error_code or "").strip().upper()
        if error_code:
            return error_code
        err = (result.error or "").lower()
        if "timeout" in err or "timed out" in err:
            return "TOOL_TIMEOUT"
        if "rate" in err and "limit" in err:
            return "RATE_LIMITED"
        if "connection" in err and "reset" in err:
            return "CONNECTION_RESET"
        return "TOOL_EXCEPTION"

    @staticmethod
    def _record_retry_decision(ctx: StatelessContext, node: ExecutionNode, decision) -> int:
        events = list(ctx.extras.get("retry_events") or [])
        events.append({
            **decision.to_dict(),
            "node_id": node.id,
            "tool_id": node.tool,
        })
        ctx.extras["retry_events"] = events
        summary = dict(ctx.extras.get("retry_summary") or {
            "retry_attempts": 0,
            "retried_nodes": [],
            "retry_succeeded": 0,
            "retry_failed": 0,
            "retry_blocked": 0,
        })
        if not decision.retry_allowed:
            summary["retry_blocked"] = int(summary.get("retry_blocked", 0) or 0) + 1
        ctx.extras["retry_summary"] = summary
        return len(events) - 1

    @staticmethod
    def _record_retry_result(
        ctx: StatelessContext,
        node: ExecutionNode,
        result: ToolResult,
        *,
        event_index: int,
        duration_ms: float,
    ) -> None:
        summary = dict(ctx.extras.get("retry_summary") or {
            "retry_attempts": 0,
            "retried_nodes": [],
            "retry_succeeded": 0,
            "retry_failed": 0,
            "retry_blocked": 0,
        })
        summary["retry_attempts"] = int(summary.get("retry_attempts", 0) or 0) + 1
        nodes = list(summary.get("retried_nodes") or [])
        if node.id not in nodes:
            nodes.append(node.id)
        summary["retried_nodes"] = nodes
        if result.success:
            summary["retry_succeeded"] = int(summary.get("retry_succeeded", 0) or 0) + 1
        else:
            summary["retry_failed"] = int(summary.get("retry_failed", 0) or 0) + 1
        ctx.extras["retry_summary"] = summary
        events = list(ctx.extras.get("retry_events") or [])
        if 0 <= event_index < len(events):
            events[event_index] = {
                **events[event_index],
                "attempt": node.retry_count,
                "final_status": "succeeded" if result.success else "failed",
                "duration_ms": round(float(duration_ms or 0.0), 3),
                "result_error_code": result.error_code or "",
            }
            ctx.extras["retry_events"] = events

    @staticmethod
    def _record_retry_aborted(ctx: StatelessContext, event_index: int, reason: str) -> None:
        events = list(ctx.extras.get("retry_events") or [])
        if 0 <= event_index < len(events):
            events[event_index] = {
                **events[event_index],
                "retry_allowed": False,
                "blocked_by_policy": False,
                "final_status": "aborted",
                "reason": reason,
            }
            ctx.extras["retry_events"] = events
        summary = dict(ctx.extras.get("retry_summary") or {})
        summary["retry_blocked"] = int(summary.get("retry_blocked", 0) or 0) + 1
        ctx.extras["retry_summary"] = summary

    @staticmethod
    def _from_tool_result(result: ToolResult, *, fallback_call_id: str) -> StreamingToolResult:
        output = result.data if isinstance(result.data, dict) else {"data": result.data}
        if not result.success and result.error:
            output = {**(output or {}), "error": result.error}
        metadata = dict(result.metadata or {})
        if result.retry_count:
            metadata["retry_count"] = result.retry_count
        if metadata:
            output = {**(output or {}), "metadata": metadata}
        return StreamingToolResult(
            tool_name=result.tool,
            call_id=result.node_id or fallback_call_id,
            output=output or {},
            ok=bool(result.success),
            error=result.error,
            latency_ms=float(result.latency_ms or 0.0),
        )


# ── QueryLoop ────────────────────────────────────────────────────────────────

@dataclass
class QueryLoopResult:
    final_response: str
    tool_results: List[StreamingToolResult] = field(default_factory=list)
    iterations: int = 0
    total_tool_calls: int = 0
    llm_calls: int = 0
    error: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    risk_level: str = "low"
    approval_required: bool = False
    approval_nodes: list[str] = field(default_factory=list)
    approval_details: list[dict[str, Any]] = field(default_factory=list)
    hard_block: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)


class QueryLoop:
    """Iterative LLM + tool execution loop.

    Usage:
        loop = QueryLoop(config, tool_registry, tool_runtime, llm_invoke, emitter)
        result = await loop.run(ctx, budget, metrics)
    """

    def __init__(
        self,
        config: SSOTRuntimeConfig,
        tool_registry: dict[str, dict[str, Any]],
        tool_runtime,
        llm_invoke: Callable[..., Any] | None = None,
        emitter=None,
    ):
        self._config = config
        self._tool_registry = tool_registry
        self._tool_runtime = tool_runtime
        self._llm_invoke = llm_invoke
        self._emitter = emitter
        self._executor = StreamingToolExecutor(tool_runtime, config, emitter)
        self._cached_tools = _build_cached_tool_definitions(tool_registry)
        self._llm_call_count = 0

    async def run(
        self,
        ctx: StatelessContext,
        budget,
        metrics,
    ) -> QueryLoopResult:
        """Run the full query loop."""
        t_start = time.monotonic()
        all_results: List[StreamingToolResult] = []
        iterations = 0
        llm_calls = 0
        # Doom-loop detection: key=(tool, args_hash) → consecutive_failures
        failure_counts: Dict[str, int] = {}
        validation_correction_attempts = 0
        successful_call_keys: set[str] = set()
        used_call_ids: set[str] = set()
        execution_duration_ms = 0.0

        # Build initial messages (cacheable prefix)
        messages = self._build_initial(ctx)

        max_iterations = getattr(self._config, "max_query_loop_iterations", 20)

        def finish(**values) -> QueryLoopResult:
            """Build every exit projection with the same runtime metrics."""
            projected_metrics = {
                "elapsed_ms": (time.monotonic() - t_start) * 1000,
                "iterations": iterations,
                "tool_calls": len(all_results),
                "llm_calls": values.get("llm_calls", llm_calls),
                "context_estimated_chars": _estimate_chars(messages),
                "context_compacted": (
                    metrics.snapshot().context_compacted if metrics else False
                ),
                "execution_duration_ms": execution_duration_ms,
                "max_parallel_width": self._executor.max_parallel_width,
                "validation_corrections": validation_correction_attempts,
            }
            projected_metrics.update(dict(values.pop("metrics", {}) or {}))
            values.setdefault("tool_results", all_results)
            values.setdefault("iterations", iterations)
            values.setdefault("total_tool_calls", len(all_results))
            values.setdefault("llm_calls", llm_calls)
            return QueryLoopResult(metrics=projected_metrics, **values)

        # Trusted UI workflows may hand off explicit artifact ids after a
        # background task completes. Read those workspace-scoped artifacts
        # through the canonical runtime before planning, then use one
        # final-response-only LLM call when the content is complete.
        prefetch_ids = list(dict.fromkeys(
            str(value).strip()
            for value in (ctx.extras.get("prefetch_artifact_ids") or [])
            if str(value).strip()
        ))[:8]
        if prefetch_ids and self._tool_runtime.has_tool("workspace.artifact"):
            prefetch_calls = [
                LLMToolCall(
                    id=f"prefetch_artifact_{index}",
                    name="workspace.artifact",
                    arguments={"action": "read", "artifact_id": artifact_id},
                )
                for index, artifact_id in enumerate(prefetch_ids)
            ]
            used_call_ids.update(call.id for call in prefetch_calls)
            execution_started = time.monotonic()
            prefetch_results = await self._executor.execute(
                prefetch_calls,
                ctx=ctx,
                budget=budget,
            )
            execution_duration_ms += (time.monotonic() - execution_started) * 1000
            all_results.extend(prefetch_results)
            messages = self._append_tool_round(
                messages,
                prefetch_calls,
                prefetch_results,
            )
            if self._has_complete_analysis_artifact(prefetch_results):
                messages = self._append_turn_nudge(
                    messages,
                    FINAL_RESPONSE_ONLY_MARKER
                    + " Complete artifacts were prefetched above. Analyze them and "
                    "answer the original request now; do not call tools.",
                )

        while iterations < max_iterations:
            iterations += 1

            # Budget check. BudgetController is the SSOT for LLM call count;
            # local llm_calls mirrors it for QueryLoopResult only.
            budget_status = budget.check_llm_call()
            if not budget_status.ok:
                return finish(
                    final_response=(
                        "已达到 LLM 调用上限，请简化请求。"
                        if not all_results
                        else self._build_tool_result_fallback(ctx, all_results)
                    ),
                    tool_results=all_results,
                    iterations=iterations,
                    total_tool_calls=len(all_results),
                    llm_calls=budget.llm_calls,
                    error=budget_status.exceeded or "budget_exceeded",
                )

            # Auto-compact with context tracking
            _before_chars = _estimate_chars(messages)
            if _before_chars > COMPACT_THRESHOLD_CHARS:
                messages, _compact_info = _compact_messages(messages)
                if _compact_info.compacted and metrics is not None:
                    metrics.mark_compacted(_compact_info)
            if metrics is not None:
                metrics.capture_context_usage(_estimate_chars(messages))

            # Call LLM (with streaming for tool exec)
            response = await self._call_llm(messages, ctx)

            if response is None or response.error:
                final_resp: str
                if all_results:
                    final_resp = self._build_tool_result_fallback(ctx, all_results)
                elif response is not None and response.content and response.content.strip():
                    final_resp = response.content.strip()
                elif response is not None:
                    final_resp = "LLM 调用失败"
                else:
                    final_resp = "LLM 调用失败"
                return finish(
                    final_response=final_resp,
                    tool_results=all_results,
                    iterations=iterations,
                    total_tool_calls=len(all_results),
                    llm_calls=budget.llm_calls,
                    error=response.error if response else "no_response",
                )

            llm_calls = budget.llm_calls

            # Check for tool calls
            if response.tool_calls:
                # Convert to LLMToolCall objects
                tool_calls = self._parse_tool_calls(response.tool_calls)
                tool_calls = self._unique_call_ids(tool_calls, iterations, used_call_ids)

                duplicate_successes = [
                    tc for tc in tool_calls
                    if self._tool_call_key(tc) in successful_call_keys
                ]
                if duplicate_successes and len(duplicate_successes) == len(tool_calls):
                    return finish(
                        final_response=self._build_tool_result_fallback(ctx, all_results),
                        error="duplicate_successful_tool_call",
                    )
                tool_calls = [
                    tc for tc in tool_calls
                    if self._tool_call_key(tc) not in successful_call_keys
                ]
                if not tool_calls:
                    return finish(
                        final_response=self._build_tool_result_fallback(ctx, all_results),
                        tool_results=all_results,
                        iterations=iterations,
                        total_tool_calls=len(all_results),
                        llm_calls=llm_calls,
                        error="duplicate_tool_call",
                    )

                gate = self._prepare_tool_calls(ctx, tool_calls)
                if not gate["ok"]:
                    if gate.get("hard_block") or gate.get("approval_nodes") or gate.get("approval_required"):
                        return finish(
                            final_response=gate["message"],
                            tool_results=all_results,
                            iterations=iterations,
                            total_tool_calls=len(all_results),
                            llm_calls=llm_calls,
                            error=gate["error"],
                            errors=list(gate.get("errors") or []),
                            risk_level=gate.get("risk_level", "high"),
                            approval_required=bool(gate.get("approval_required", False)),
                            approval_nodes=list(gate.get("approval_nodes") or []),
                            approval_details=list(gate.get("approval_details") or []),
                            hard_block=bool(gate.get("hard_block", False)),
                        )
                    # Soft validation errors (e.g. missing_required_arg) —
                    # feed back to LLM as tool results so it can correct itself.
                    if validation_correction_attempts >= MAX_VALIDATION_CORRECTION_ROUNDS:
                        ctx.extras["validation_correction_exhausted"] = True
                        return finish(
                            final_response=(
                                "工具参数连续校验失败，已停止自动修正。\n"
                                + gate["message"]
                            ),
                            tool_results=all_results,
                            iterations=iterations,
                            total_tool_calls=len(all_results),
                            llm_calls=llm_calls,
                            error="validation_correction_exhausted",
                            errors=list(gate.get("errors") or []),
                            risk_level="low",
                        )
                    validation_correction_attempts += 1
                    if self._emitter:
                        self._emitter.emit("tool_validation_failed", {
                            "errors": gate.get("errors", []),
                            "message": gate["message"],
                            "attempt": validation_correction_attempts,
                            "max_attempts": MAX_VALIDATION_CORRECTION_ROUNDS,
                        })
                    structured_errors = list(gate.get("validation_errors") or [])
                    ctx.extras.setdefault("validation_correction_events", []).append({
                        "attempt": validation_correction_attempts,
                        "max_attempts": MAX_VALIDATION_CORRECTION_ROUNDS,
                        "errors": structured_errors,
                    })
                    fake_results = [
                        StreamingToolResult(
                            tool_name=tc.name,
                            call_id=tc.id,
                            output={
                                "ok": False,
                                "executed": False,
                                "retryable": True,
                                "error_code": "TOOL_ARGUMENT_VALIDATION_FAILED",
                                "error": gate["message"],
                                "validation_errors": structured_errors,
                                "correction_attempt": validation_correction_attempts,
                                "max_correction_attempts": MAX_VALIDATION_CORRECTION_ROUNDS,
                                "instruction": (
                                    "Correct the reported tool arguments and issue a new call. "
                                    "Do not repeat unchanged invalid arguments."
                                ),
                            },
                            ok=False,
                            error=gate["message"],
                        )
                        for tc in tool_calls
                    ]
                    all_results.extend(fake_results)
                    messages = self._append_tool_round(messages, tool_calls, fake_results)
                    # Don't count these as successful tool calls
                    continue
                tool_calls = gate["tool_calls"]

                # Execute tools (parallel read-only, serial writes)
                execution_started = time.monotonic()
                results = await self._executor.execute(tool_calls, ctx=ctx, budget=budget)
                all_results.extend(results)
                for r, tc in zip(results, tool_calls):
                    if r.ok:
                        successful_call_keys.add(self._tool_call_key(tc))

                # ── Tracking: auto-poll long tasks (e.g. inspection) ──
                polled_results = await self._settle_tracking(ctx, results, budget=budget)
                execution_duration_ms += (time.monotonic() - execution_started) * 1000
                if polled_results:
                    all_results.extend(polled_results)
                    results = results + polled_results

                # Append assistant message (with tool_calls) + tool results
                messages = self._append_tool_round(messages, tool_calls, results)
                if self._has_complete_analysis_artifact(results):
                    messages = self._append_turn_nudge(
                        messages,
                        FINAL_RESPONSE_ONLY_MARKER
                        + " The complete artifact content is included above. "
                        "Analyze it and answer the original request now; do not read files or call tools.",
                    )

                # ── Doom-loop detection ──
                for r in results:
                    if not r.ok and r.error:
                        err_lower = str(r.error).lower()
                        # Tool not found (wrong name)
                        if "not found" in err_lower:
                            key = f"not_found:{r.tool_name}"
                            failure_counts[key] = failure_counts.get(key, 0) + 1
                            if failure_counts[key] >= 3:
                                return finish(
                                    final_response=f"工具 {r.tool_name} 不存在，已尝试 {failure_counts[key]} 次。请检查工具名称是否正确。",
                                    tool_results=all_results,
                                    iterations=iterations,
                                    total_tool_calls=len(all_results),
                                    llm_calls=llm_calls,
                                    error="doom_loop",
                                )
                        # SSH auth failure (credential issue — do NOT retry)
                        if "ssh 认证失败" in err_lower or "authentication" in err_lower or "password" in err_lower or "permission denied" in err_lower or "auth" in err_lower:
                            key = f"ssh_auth:{r.tool_name}"
                            failure_counts[key] = failure_counts.get(key, 0) + 1
                            if failure_counts[key] >= 2:
                                return finish(
                                    final_response=(
                                        f"SSH 认证已连续失败 {failure_counts[key]} 次。"
                                        "可能原因：1) 资产未配置密码或密码错误；"
                                        "2) 未使用 asset_id 导致凭据未解析。"
                                        "请检查 CMDB 中该设备的密码配置。"
                                    ),
                                    tool_results=all_results,
                                    iterations=iterations,
                                    total_tool_calls=len(all_results),
                                    llm_calls=llm_calls,
                                    error="doom_loop_ssh_auth",
                                )
                        # Budget exhaustion — stop immediately
                        if "budget" in err_lower or "exceeded" in err_lower:
                            return finish(
                                final_response="已达到 LLM 调用或工具执行预算上限。请简化请求或稍后再试。",
                                tool_results=all_results,
                                iterations=iterations,
                                total_tool_calls=len(all_results),
                                llm_calls=llm_calls,
                                error="doom_loop_budget",
                            )
                        # Timeout / connection — generic doom-loop detection
                        if "timeout" in err_lower or "timed out" in err_lower or "connection" in err_lower or "network" in err_lower:
                            key = f"timeout:{r.tool_name}:{_json_compact(r.output, max_chars=600)}"
                            failure_counts[key] = failure_counts.get(key, 0) + 1
                            if failure_counts[key] >= 3:
                                return finish(
                                    final_response=f"工具 {r.tool_name} 连续超时 {failure_counts[key]} 次。请检查网络连接或设备可达性。",
                                    tool_results=all_results,
                                    iterations=iterations,
                                    total_tool_calls=len(all_results),
                                    llm_calls=llm_calls,
                                    error="doom_loop_timeout",
                                )

                if not getattr(self._config, "enable_finalizer", True):
                    return finish(
                        final_response=self._build_tool_result_fallback(ctx, all_results),
                        tool_results=all_results,
                        iterations=iterations,
                        total_tool_calls=len(all_results),
                        llm_calls=llm_calls,
                        metrics={
                            "elapsed_ms": (time.monotonic() - t_start) * 1000,
                            "iterations": iterations,
                            "tool_calls": len(all_results),
                            "llm_calls": llm_calls,
                        },
                    )

                continue

            # No tool calls → final response
            final_text = response.content or ""
            if not final_text.strip():
                if all_results and iterations < max_iterations:
                    reminder = (
                        FINAL_RESPONSE_ONLY_MARKER
                        + " You just received tool results. "
                        "Now answer the user's original question in natural language. "
                        "Do NOT call any more tools — produce the final response directly."
                    )
                    messages.append(LLMMessage(role="user", content=reminder))
                    continue
                elif all_results:
                    # iterations >= max_iterations or nudge already tried enough
                    final_text = self._build_tool_result_fallback(ctx, all_results)
                else:
                    final_text = "抱歉，我无法生成回复。请重新描述您的问题后再试。"
            else:
                final_text = final_text.strip()
            elapsed = (time.monotonic() - t_start) * 1000

            return finish(
                final_response=final_text,
                tool_results=all_results,
                iterations=iterations,
                total_tool_calls=len(all_results),
                llm_calls=llm_calls,
                metrics={
                    "elapsed_ms": elapsed,
                    "iterations": iterations,
                    "tool_calls": len(all_results),
                    "llm_calls": llm_calls,
                    "context_estimated_chars": _estimate_chars(messages),
                    "context_compacted": metrics.snapshot().context_compacted if metrics else False,
                    "execution_duration_ms": execution_duration_ms,
                    "max_parallel_width": self._executor.max_parallel_width,
                },
            )

        # Max iterations exhausted
        return finish(
            final_response=(
                self._build_tool_result_fallback(ctx, all_results)
                if all_results else "已达到最大迭代次数，请缩小任务范围后重试。"
            ),
            tool_results=all_results,
            iterations=iterations,
            total_tool_calls=len(all_results),
            llm_calls=llm_calls,
            error="max_iterations",
        )

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _should_poll_tracking(user_input: str, tracking: dict) -> bool:
        """Track every producer-declared long task within runtime budgets."""
        if tracking.get("done"):
            return False
        action = str(tracking.get("suggested_next_action") or "").lower()
        if action and action != "poll_get":
            return False
        return str(tracking.get("kind") or "") == "long_task"

    def _build_initial(self, ctx: StatelessContext) -> List[LLMMessage]:
        """Build initial messages with cacheable prefix."""
        conversation_block = ctx.extras.get("conversation_history_block") or ""
        retrieved_block = ctx.extras.get("retrieved_context_block") or ""

        return [
            LLMMessage(
                role="system",
                content=build_runtime_system_prompt(ctx.extras),
            ),
            LLMMessage(role="user", content=build_turn_message(
                workspace_id=ctx.workspace_id,
                session_id=ctx.session_id,
                user_input=ctx.user_input,
                conversation_history=str(conversation_block),
                governed_context=str(retrieved_block),
            )),
        ]

    @staticmethod
    def _unique_call_ids(
        tool_calls: List[LLMToolCall],
        iteration: int,
        used: set[str],
    ) -> List[LLMToolCall]:
        """Keep provider call ids unique across iterative LLM rounds."""
        result: list[LLMToolCall] = []
        for index, tc in enumerate(tool_calls):
            base = str(tc.id or f"call_{index}")
            candidate = base
            suffix = 0
            while candidate in used:
                suffix += 1
                candidate = f"{base}_i{iteration}_{suffix}"
            used.add(candidate)
            result.append(LLMToolCall(
                id=candidate,
                name=tc.name,
                arguments=dict(tc.arguments or {}),
            ))
        return result

    async def _call_llm(
        self,
        messages: List[LLMMessage],
        ctx: StatelessContext,
    ) -> Optional[LLMResponse]:
        """Call LLM with tools and streaming support.

        Wraps the synchronous LLM call with asyncio.wait_for + asyncio.to_thread
        to guarantee a hard timeout and prevent event-loop blocking.
        """
        try:
            system_prompt, stream_scope, stream_to_user = self._llm_call_mode(messages, ctx)
            tools_for_call = (
                [] if self._is_final_response_only(messages) else self._cached_tools
            )
            if self._llm_invoke is not None:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._llm_invoke,
                        system=system_prompt,
                        user=self._messages_to_user_text(messages),
                        temperature=0.2,
                        timeout=120,
                        tools=tools_for_call,
                        workspace_id=ctx.workspace_id,
                        session_id=ctx.session_id,
                        extra={
                            "runtime_engine": "ssot_runtime",
                            "stream_scope": stream_scope,
                            "stream_to_user": stream_to_user,
                            "workspace_id": ctx.workspace_id,
                            "session_id": ctx.session_id,
                        },
                    ),
                    timeout=120,
                )
                return self._coerce_llm_response(raw)

            from agent.llm.runtime import invoke_llm
            call_messages = [
                LLMMessage(role="system", content=system_prompt),
                *messages[1:],
            ] if messages else [LLMMessage(role="system", content=system_prompt)]

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    invoke_llm,
                    task="query_loop",
                    messages=call_messages,
                    tools=tools_for_call,
                    config_override={
                        "temperature": 0.2,
                        "max_tokens": 4096,
                        "timeout": 120,
                    },
                ),
                timeout=120,
            )
            return response
        except asyncio.TimeoutError:
            self._llm_call_count += 1
            return LLMResponse(error="llm_call_timeout")
        except Exception as e:
            self._llm_call_count += 1  # P1-7: count against budget even on error
            return LLMResponse(error=str(e))

    @staticmethod
    def _llm_call_mode(
        messages: List[LLMMessage],
        ctx: StatelessContext,
    ) -> tuple[str, str, bool]:
        has_tool_context = any(
            m.role == "tool"
            or (m.role == "user" and "AUTO TRACKING RESULTS" in str(m.content or ""))
            for m in messages
        )
        if has_tool_context:
            return QUERY_LOOP_FINALIZER_PROMPT, "finalizer", True
        return build_runtime_system_prompt(ctx.extras), "planner", False

    @staticmethod
    def _is_final_response_only(messages: List[LLMMessage]) -> bool:
        return any(
            message.role == "user"
            and FINAL_RESPONSE_ONLY_MARKER in str(message.content or "")
            for message in messages[-2:]
        )

    @staticmethod
    def _has_complete_analysis_artifact(
        results: List[StreamingToolResult],
    ) -> bool:
        return any(
            result.ok
            and result.tool_name.replace("__", ".") == "workspace.artifact"
            and result.output.get("content_complete") is True
            and result.output.get("artifact_type") in {
                "inspection_raw", "translated_config", "output_config",
            }
            for result in results
        )

    def _messages_to_user_text(self, messages: List[LLMMessage]) -> str:
        """Serialize loop messages for injected LLM adapters.

        The production adapter accepts ``system`` + ``user`` strings, while
        QueryLoop internally keeps OpenAI-style tool messages. This projection
        preserves the relevant context without bypassing the injected adapter.
        """
        parts: list[str] = []
        final_response_only = self._is_final_response_only(messages)
        for m in messages:
            if m.role == "system":
                continue
            label = m.role.upper()
            content = m.content
            if m.tool_calls and not final_response_only:
                parts.append(
                    f"{label} TOOL_CALLS: "
                    f"{json.dumps(m.tool_calls, ensure_ascii=False, default=str)}"
                )
            if content:
                parts.append(f"{label}: {content}")
            if m.tool_call_id:
                if parts:
                    parts[-1] = f"{parts[-1]} (tool_call_id={m.tool_call_id})"  # P2-3: simpler than slice assignment
        return "\n\n".join(parts)

    def _coerce_llm_response(self, raw: Any) -> LLMResponse:
        """Coerce injected adapter output into QueryLoop's LLMResponse shape.
        
        Also strips ``<think>...</think>`` tags that some models (MiniMax-M3)
        leak into visible output — they confuse final_response_summary truncation
        and make users think the model is talking to itself.
        """
        if isinstance(raw, LLMResponse):
            raw.content = self._strip_think_tags(str(raw.content or ""))
            return raw
        if raw is None:
            return LLMResponse(error="empty_llm_response")
        tool_calls = getattr(raw, "tool_calls", None)
        if tool_calls is not None:
            return LLMResponse(
                content=self._strip_think_tags(str(getattr(raw, "content", "") or "")),
                error=getattr(raw, "error", None),
                tool_calls=list(tool_calls or []),
            )
        text = self._strip_think_tags(str(raw))
        data = self._try_parse_json_object(text)
        if data is not None:
            nodes = data.get("nodes")
            if isinstance(nodes, list):
                calls: list[LLMToolCall] = []
                for idx, node in enumerate(nodes):
                    if not isinstance(node, dict):
                        continue
                    tool = str(node.get("tool") or "").strip()
                    if not tool:
                        continue
                    calls.append(LLMToolCall(
                        id=str(node.get("id") or f"call_{idx}"),
                        name=tool,
                        arguments=dict(node.get("args") or {}),
                    ))
                return LLMResponse(
                    content=self._strip_think_tags(str(data.get("final_response") or "")),
                    tool_calls=calls,
                )
        return LLMResponse(content=text)
    
    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove ``<think>...</think>`` blocks from LLM output.
        
        Some models (MiniMax-M3) emit chain-of-thought reasoning inside XML
        tags. We strip the tags and their content before passing the text on.
        """
        import re
        return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()

    @staticmethod
    def _try_parse_json_object(text: str) -> dict[str, Any] | None:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            data = json.loads(cleaned)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _parse_tool_calls(self, raw: List[LLMToolCall]) -> List[LLMToolCall]:
        """Normalise raw tool calls from LLM response (may be dict or LLMToolCall)."""
        result = []
        for tc in raw:
            if isinstance(tc, dict):
                # Raw dict from provider
                args = tc.get("arguments", {})
                tid = tc.get("id", "")
                tname = tc.get("name", "")
            else:
                # LLMToolCall dataclass
                args = getattr(tc, "arguments", {})
                tid = getattr(tc, "id", "")
                tname = getattr(tc, "name", "")
            
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            
            # Normalise double-underscore to dots
            tname = tname.replace("__", ".")
            if not tid:
                tid = f"call_{len(result)}"
            
            result.append(LLMToolCall(
                id=str(tid),
                name=tname,
                arguments=args,
            ))
        return result

    @staticmethod
    def _tool_call_key(tc: LLMToolCall) -> str:
        return (
            f"{tc.name}:"
            f"{json.dumps(tc.arguments or {}, sort_keys=True, ensure_ascii=False, default=str)}"
        )

    def _prepare_tool_calls(
        self,
        ctx: StatelessContext,
        tool_calls: List[LLMToolCall],
    ) -> dict[str, Any]:
        """Run QueryLoop's pre-execution hard boundaries.

        QueryLoop is the execution path. It still keeps semantic repair, risk,
        and approval boundaries, but does not expose or persist old graph state.
        """
        nodes = self._tool_calls_to_nodes(tool_calls)
        graph = self._validation_graph(nodes)

        from .semantic_validator import SemanticValidator
        from .pre_execution_repair import (
            PreExecutionRepairEngine,
            REPAIRABLE_ERROR_CODES,
        )
        from .risk_policy import RiskPolicyEngine
        from .plan_enrichment import enrich_dag_from_user_request

        enrichment_events = enrich_dag_from_user_request(graph, ctx.user_input)
        if enrichment_events:
            ctx.extras.setdefault("plan_enrichment_events", [])
            ctx.extras["plan_enrichment_events"].extend(
                asdict(event) for event in enrichment_events
            )

        validator = SemanticValidator(self._tool_registry)
        validation = validator.validate(graph)
        if not validation.valid:
            repair = PreExecutionRepairEngine().try_repair(graph, validation.errors)
            self._record_pre_exec_repair(ctx, repair)
            repaired_graph = getattr(repair, "repaired_graph", None)
            if repair.repaired and repaired_graph is not None:
                graph = repaired_graph
                nodes = list(getattr(graph, "nodes", []) or [])
                validation = validator.validate(graph)

        if not validation.valid:
            for node in nodes:
                if any(e.node_id == node.id for e in validation.errors):
                    node.status = ExecutionStatus.SKIPPED
                    node.error = "Blocked by semantic validation"
            errors = [
                f"{e.node_id}:{e.code}:{e.message}"
                for e in validation.errors
            ]
            validation_errors = [
                {
                    "node_id": e.node_id,
                    "code": e.code,
                    "message": e.message,
                    "details": dict(getattr(e, "details", {}) or {}),
                }
                for e in validation.errors
            ]
            self._record_blocked_audit_nodes(ctx, nodes)
            # Repairable semantic errors remain recoverable by the LLM when
            # deterministic repair could not resolve them. The repair engine
            # owns this code set so validation and retry cannot drift apart.
            is_hard = any(
                e.code not in REPAIRABLE_ERROR_CODES
                for e in validation.errors
            )
            return {
                "ok": False,
                "error": "semantic_validation_failed",
                "errors": errors,
                "validation_errors": validation_errors,
                "hard_block": is_hard,
                "risk_level": "high" if is_hard else "low",
                "message": "工具调用校验失败：\n" + "\n".join(f"- {e}" for e in errors),
            }

        risk = RiskPolicyEngine(self._config).assess(graph)
        ctx.extras.update({
            "approval_required": bool(risk.requires_approval),
            "hard_block": bool(risk.hard_block),
            "approval_reason": risk.approval_reason,
            "approval_nodes": list(risk.approval_nodes),
            "approval_details": list(risk.approval_details),
        })

        if risk.hard_block:
            for node in nodes:
                if node.id in risk.blocked_nodes:
                    node.status = ExecutionStatus.SKIPPED
                    node.error = risk.blocked_reason or "Blocked by risk policy"
            reason = risk.blocked_reason or "blocked_by_risk_policy"
            self._record_blocked_audit_nodes(ctx, nodes)
            return {
                "ok": False,
                "error": "risk_hard_block",
                "errors": [reason],
                "hard_block": True,
                "risk_level": risk.risk_level,
                "message": f"工具调用被安全策略阻断：{reason}",
            }

        if risk.requires_approval and not ctx.extras.get("approved_risk"):
            return {
                "ok": False,
                "error": "approval_required",
                "errors": [],
                "approval_required": True,
                "approval_nodes": list(risk.approval_nodes),
                "approval_details": list(risk.approval_details),
                "risk_level": risk.risk_level,
                "message": (
                    "该操作需要用户审批后才能继续执行。"
                    f"原因：{risk.approval_reason or 'high_risk_tool_or_command'}"
                ),
            }

        repaired_calls = [
            LLMToolCall(id=n.id, name=n.tool, arguments=dict(n.args or {}))
            for n in nodes
        ]
        return {
            "ok": True,
            "tool_calls": repaired_calls,
            "risk_level": risk.risk_level,
            "approval_required": False,
        }

    @staticmethod
    def _tool_calls_to_nodes(tool_calls: List[LLMToolCall]) -> list[ExecutionNode]:
        from .action_alias import resolve_action_alias

        nodes: list[ExecutionNode] = []
        for idx, tc in enumerate(tool_calls):
            args = dict(tc.arguments or {})
            action_original = ""
            action_normalized_from_alias = False
            raw_action = args.get("action")
            if isinstance(raw_action, str) and raw_action:
                resolution = resolve_action_alias(tc.name.replace("__", "."), raw_action)
                if resolution.matched:
                    args["action"] = resolution.canonical_action
                    if resolution.operation:
                        args["operation"] = resolution.operation
                    action_original = resolution.original_action
                    action_normalized_from_alias = True
            nodes.append(ExecutionNode(
                id=tc.id or f"call_{idx}",
                tool=tc.name.replace("__", "."),
                args=args,
                depth=0,
                action_original=action_original,
                action_normalized_from_alias=action_normalized_from_alias,
            ))
        return nodes

    @staticmethod
    def _validation_graph(nodes: list[ExecutionNode]):
        """Adapter for validators that still accept a graph-like object."""
        class _ValidationGraph:
            def __init__(self, graph_nodes):
                self.nodes = graph_nodes
                self.layers = {0: graph_nodes}
                self.total_nodes = len(graph_nodes)
                self.max_depth = 0

            def get_layer(self, depth: int):
                return self.layers.get(depth, [])

        return _ValidationGraph(nodes)

    @staticmethod
    def _record_blocked_audit_nodes(ctx: StatelessContext, nodes: list[ExecutionNode]) -> None:
        blocked = []
        for node in nodes:
            if node.status != ExecutionStatus.SKIPPED:
                continue
            blocked.append({
                "node_id": node.id,
                "tool": node.tool,
                "args": dict(node.args or {}),
                "depth": node.depth,
                "status": node.status.value,
                "latency_ms": node.latency_ms,
                "error": node.error or "blocked",
            })
        if blocked:
            ctx.extras["audit_blocked_nodes"] = blocked

    @staticmethod
    def _record_pre_exec_repair(ctx: StatelessContext, repair) -> None:
        events = []
        for event in getattr(repair, "repair_events", []) or []:
            try:
                events.append(asdict(event))
            except Exception:
                events.append(dict(getattr(event, "__dict__", {}) or {}))
        if events:
            ctx.extras["pre_exec_repair_events"] = events
        ctx.extras["pre_exec_repair_applied"] = bool(getattr(repair, "repaired", False))

    def _append_turn_nudge(
        self,
        messages: List[LLMMessage],
        nudge_text: str,
    ) -> List[LLMMessage]:
        """Append a user nudge to guide the LLM toward a final answer.

        Used when the LLM returns empty text after tools have produced
        results — instead of calling a separate "finalizer", we nudge it
        to produce the answer directly.
        """
        new_msgs = list(messages)
        new_msgs.append(LLMMessage(role="user", content=nudge_text))
        return new_msgs

    def _append_tool_round(
        self,
        messages: List[LLMMessage],
        tool_calls: List[LLMToolCall],
        results: List[StreamingToolResult],
    ) -> List[LLMMessage]:
        """Append assistant tool_calls + tool results to messages.
        
        IMPORTANT: assistant message uses __ names (LLM format), tool results
        use cross-referenced call_id to match tool definitions.
        """
        new_msgs = list(messages)

        # Assistant message with tool calls (MUST use __ names to match tool defs)
        assistant_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": (tc.name or "").replace(".", "__"),  # dots → __ for API
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ]
        new_msgs.append(LLMMessage(
            role="assistant",
            content="",
            tool_calls=assistant_tool_calls,
        ))

        original_call_ids = {tc.id for tc in tool_calls}
        extra_results: list[StreamingToolResult] = []

        # Tool result messages for model-requested calls only. Auto-tracking
        # polls are internal and do not have matching assistant tool_calls.
        for r in results:
            if r.call_id not in original_call_ids:
                extra_results.append(r)
                continue
            # v3.11: ensure errors are visible to the LLM even when r.output is empty
            tool_payload = dict(r.output) if r.output else {}
            if not tool_payload.get("ok", True) and r.error and not tool_payload.get("errors"):
                tool_payload["errors"] = [r.error]
            if tool_payload.get("ok", True) and r.error:
                tool_payload["ok"] = False
                tool_payload["errors"] = [r.error]
            is_complete_text_artifact = (
                r.tool_name.replace("__", ".") == "workspace.artifact"
                and tool_payload.get("content_complete") is True
                and tool_payload.get("artifact_type") in {
                    "inspection_raw", "translated_config", "output_config",
                }
            )
            output_str = (
                _artifact_analysis_content(tool_payload)
                if is_complete_text_artifact
                else _json_compact(tool_payload, max_chars=TOOL_MESSAGE_MAX_CHARS)
            )
            new_msgs.append(LLMMessage(
                role="tool",
                content=output_str,
                tool_call_id=r.call_id,
            ))

        if extra_results:
            payload = [
                {
                    "tool": r.tool_name,
                    "tool_id": r.tool_name,
                    "call_id": r.call_id,
                    "ok": r.ok,
                    "error": r.error,
                    "output": r.output,
                }
                for r in extra_results
            ]
            output_str = _json_compact(payload, max_chars=TOOL_MESSAGE_MAX_CHARS)
            new_msgs.append(LLMMessage(
                role="user",
                content="AUTO TRACKING RESULTS:\n" + output_str,
            ))

        return new_msgs

    # ── Tracking / Polling ──────────────────────────────────────────────

    async def _settle_tracking(
        self,
        ctx: StatelessContext,
        results: List[StreamingToolResult],
        budget=None,
    ) -> List[StreamingToolResult]:
        """After tool execution, auto-poll long tasks (e.g. inspection).

        Polling is generic and bounded. It runs only when the tool producer
        declares a non-terminal ``long_task`` tracking payload.
        Uses the tool's canonical name for get calls.
        """
        polled: List[StreamingToolResult] = []
        if not getattr(self._config, "tracking_enabled", True):
            return polled

        max_polls = max(0, int(getattr(self._config, "tracking_max_polls", 8) or 0))
        cap_seconds = float(getattr(self._config, "tracking_poll_interval_cap_seconds", 2.0))
        max_seconds = max(0, float(getattr(self._config, "tracking_max_seconds", 60)))
        if max_polls <= 0:
            return polled

        deadline = time.monotonic() + max_seconds
        user_input = ctx.user_input or ""

        for r in results:
            tracking = extract_tracking_payload(r.output)
            if not tracking:
                continue
            tracking = normalize_tracking_payload(tracking)

            if tracking.get("done"):
                continue

            # Producer-declared tracking avoids keyword or intent guessing.
            if not self._should_poll_tracking(user_input, tracking):
                continue

            task_id = str(tracking.get("task_id") or "").strip()
            # Use the canonical tool name from result, not domain from tracking
            tool_name = (r.tool_name or "").strip()
            if not task_id or not tool_name:
                continue
            if not self._tool_runtime.has_tool(tool_name):
                continue

            ctx.extras.setdefault("tracking_events", [])
            ctx.extras["tracking_events"].append({
                "tool": tool_name,
                "call_id": r.call_id,
                "tracking": tracking,
                "source": "initial",
            })
            ctx.extras["tracking_summary"] = tracking

            poll_index = 0
            last_error_count = 0
            while poll_index < max_polls and time.monotonic() < deadline:
                if tracking.get("done"):
                    break

                wait_s = self._tracking_wait(tracking, cap_seconds, deadline)
                if wait_s > 0:
                    await asyncio.sleep(wait_s)

                poll_index += 1
                poll_call_id = f"{r.call_id}_track_{poll_index}"
                poll_arguments = dict(tracking.get("poll_arguments") or {})
                poll_arguments.setdefault("task_id", task_id)
                poll_arguments.setdefault("action", str(tracking.get("poll_action") or "get"))
                poll_call = LLMToolCall(
                    id=poll_call_id,
                    name=tool_name,
                    arguments=poll_arguments,
                )
                try:
                    poll_result = await self._executor._execute_one(
                        poll_call, ctx=ctx, budget=budget
                    )
                    polled.append(poll_result)

                    new_tracking = extract_tracking_payload(poll_result.output)
                    if new_tracking:
                        tracking = normalize_tracking_payload(new_tracking)
                        ctx.extras["tracking_summary"] = tracking
                        ctx.extras["tracking_events"].append({
                            "tool": tool_name,
                            "call_id": poll_call_id,
                            "tracking": tracking,
                            "source": "poll",
                            "poll_index": poll_index,
                        })
                    if not poll_result.ok:
                        # Track consecutive poll failures
                        last_error_count += 1
                        if last_error_count >= 3:
                            # Too many consecutive poll failures — stop
                            break
                    else:
                        last_error_count = 0
                except Exception as e:
                    # Poll call crashed — record as error and stop polling
                    polled.append(StreamingToolResult(
                        tool_name=tool_name,
                        call_id=poll_call_id,
                        output={},
                        ok=False,
                        error=f"poll_crash: {str(e)[:200]}",
                    ))
                    break

        return polled

    def _tracking_wait(self, tracking: dict, cap: float, deadline: float) -> float:
        """Calculate poll wait time, capped and bounded by deadline."""
        try:
            requested = float(tracking.get("next_poll_seconds") or 0)
        except (TypeError, ValueError):
            requested = 0.0
        remaining = max(0.0, deadline - time.monotonic())
        cap = max(0.0, cap)
        if requested <= 0 or cap <= 0 or remaining <= 0:
            return 0.0
        return max(0.0, min(requested, cap, remaining))

    def _build_tool_result_fallback(
        self,
        ctx: StatelessContext,
        results: List[StreamingToolResult],
    ) -> str:
        """Build a useful final answer when the LLM returns empty text.
        Produces a human-readable report, not raw JSON dumps.
        """
        lines: list[str] = []
        ok_count = 0
        warn_count = 0
        fail_count = 0

        for r in results:
            output = r.output if isinstance(r.output, dict) else {}
            exit_code = output.get("exit_code")

            # Classify by exit_code for exec.run tools
            if not r.ok:
                fail_count += 1
            elif exit_code is not None and exit_code != 0:
                warn_count += 1
            else:
                ok_count += 1

        lines.append(f"工具调用：成功 {ok_count} 个" +
                     (f"，警告 {warn_count} 个" if warn_count else "") +
                     f"，失败 {fail_count} 个")

        for r in results:
            output = r.output if isinstance(r.output, dict) else {}
            exit_code = output.get("exit_code")
            ec_mark = "⚠️ " if (r.ok and exit_code is not None and exit_code != 0) else ""
            status_mark = "❌" if not r.ok else (ec_mark or "✅")

            lines.append(f"\n### {status_mark} {r.tool_name}")

            # ── exec.run: show command, exit_code, stdout, stderr ──
            if r.tool_name in ("exec.run", "exec__run", "exec__background"):
                desc = output.get("description") or output.get("command", "")
                if desc:
                    lines.append(f"> `{str(desc)[:120]}`")
                if exit_code is not None:
                    ec_str = f"exit_code={exit_code}"
                    if exit_code != 0:
                        lines.append(f"Exit code: **{ec_str}**")
                    else:
                        lines.append(f"Exit: {ec_str}")
                stdout = output.get("stdout", "")
                stderr = output.get("stderr", "")
                if stdout.strip():
                    lines.append(f"```\n{str(stdout)[:800]}\n```")
                if stderr.strip():
                    lines.append(f"```\n{str(stderr)[:800]}\n```")

            # ── device.manage / cmdb: show count and key fields ──
            elif r.tool_name in ("device.manage", "device__manage"):
                assets = output.get("assets", [])
                if assets:
                    lines.append(f"找到 {len(assets)} 台设备：")
                    for a in assets[:10]:
                        host = a.get("host", "?")
                        name = a.get("name", "?")
                        vendor = a.get("vendor", "")
                        region = a.get("region", "")
                        lines.append(f"- {name} ({host}) {vendor} {region}".strip())
                    if len(assets) > 10:
                        lines.append(f"... 共 {len(assets)} 台，仅展示前 10 台")
                else:
                    lines.append("未找到匹配设备。")

            # ── inspection: show task status ──
            elif r.tool_name in ("inspection.manage", "inspection__manage"):
                task_id = output.get("task_id", "")
                status = output.get("status", "")
                summary = output.get("summary", {})
                if isinstance(summary, dict):
                    lines.append(f"任务 `{task_id}` — {status}")
                    lines.append(f"总计: {summary.get('total_devices','?')} 台, "
                                 f"成功: {summary.get('succeeded_devices','?')}, "
                                 f"失败: {summary.get('failed_devices','?')}")
                else:
                    lines.append(f"任务 `{task_id}` — {status}")

            # ── other tools: compact summary ──
            else:
                summary = output.get("summary") or output.get("message") or ""
                if summary and len(str(summary)) <= 300:
                    lines.append(str(summary))
                else:
                    ok_mark = "ok" if r.ok else f"error: {r.error}"
                    lines.append(f"{ok_mark}")

            # Error message if any
            if r.error:
                hint = self._canonical_tool_hint(r.tool_name)
                if hint:
                    lines.append(f"错误: `{r.tool_name}` 不存在: {r.error}；应使用 `{hint}`")
                else:
                    lines.append(f"错误: `{r.tool_name}` 不存在: {r.error}")

        # Tracking info
        tracking_items: list[dict[str, Any]] = []
        for r in results:
            tracking = extract_tracking_payload(r.output)
            if tracking:
                tracking_items.append(normalize_tracking_payload(tracking))

        if tracking_items:
            lines.append("")
            latest = tracking_items[-1]
            task_id = latest.get("task_id") or ""
            status = latest.get("status") or "unknown"
            done = bool(latest.get("done"))
            progress = latest.get("progress") or {}
            completed = progress.get("completed")
            total = progress.get("total")
            lines.append(f"跟踪任务 `{task_id}`：{status}，{'已完成' if done else '进行中'}")
            if completed is not None and total is not None:
                lines.append(f"进度：{completed}/{total}")
            report_url = (
                latest.get("report_url")
                or latest.get("html_url")
                or latest.get("artifact_url")
            )
            if report_url:
                lines.append(f"报告链接：{report_url}")

        return "\n".join(lines)

    def _canonical_tool_hint(self, tool_name: str) -> str:
        """Suggest the canonical tool id for a category-like hallucination.

        This is a hint only; it does not execute aliases or widen the public
        tool namespace.
        """
        name = (tool_name or "").strip()
        if not name or self._tool_runtime.has_tool(name):
            return ""
        prefix = name + "."
        matches = sorted(t for t in self._tool_registry if t.startswith(prefix))
        return matches[0] if len(matches) == 1 else ""

    # ── Private helpers ──────────────────────────────────────────────────
