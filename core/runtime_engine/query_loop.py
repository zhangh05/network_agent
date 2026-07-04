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
import json
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


# ── Prompt Cache ────────────────────────────────────────────────────────────

# Static prefix that never changes between turns — cached by the LLM API.
QUERY_LOOP_SYSTEM_PROMPT = """You are a network operations AI agent. Use EXACT tool names — never abbreviate.
For example:
- inspection__manage (device inspection)
- exec__run (SSH/Telnet/command)   web__manage (search/fetch/weather)
- device__manage (CMDB)   config__manage (config analysis)   pcap__manage (packet analysis)
- knowledge__manage (RAG search)   memory__manage   browser__manage (automation)
- data__manage (CSV/JSON/stats)   report__manage (save/diff/doc)
- text__analyze (redact/extract)   system__manage (diagnostics)
- workspace__file / workspace__artifact / workspace__filestore (storage)
- skill__manage   agent__manage (subagent spawn)   git__manage   code__search

Work step by step. Gather data with tools first, then reason and answer.
Do not fabricate any data — only use what tools return.

RULES:
1. Use EXACT tool names — never shorten or invent names.
2. For SSH: exec__run(action="shell", target="ssh", asset_id=...). Use asset_id
   from CMDB — never pass host/username/password separately.
3. If a tool returns "Tool not found", the name is wrong — check the available
   function list.
4. Never repeat the same failing tool+arguments more than 2 times.
5. Weather: web__manage(action="weather", location=..., days=...).
   明天=2, 后天=3, 一周=7, 未来十天=10.
6. Inspection: inspection__manage(action="run") starts a CMDB task; follow the
   same task with inspection__manage(action="get", task_id=...). Fetch
   inspection__manage(action="report", task_id=..., format="html") only after
   status is succeeded/partial.
7. After all tool results are in, respond directly without calling more tools."""


QUERY_LOOP_FINALIZER_PROMPT = """You are the final response writer for Network Agent.

Use the provided tool results as facts. Explain the outcome in clear user-facing
language:
1. Answer the user's original request directly.
2. Summarize successful tool results, failures, retries, tracking status, and
   next actions when relevant.
3. If a long task is still running, keep the task id and tell the user it is
   still running; do not start a duplicate task.
4. If a report or artifact URL is present, include it.
5. Do not invent device states, command output, weather data, files, or memory.
6. You may call another tool only when a required follow-up fact is missing.
7. Never repeat a tool call whose successful result is already shown below."""


def _build_cached_tool_definitions(tool_registry: dict) -> List[dict]:
    """Build tool definitions with stable ordering for prompt caching."""
    tools = []
    for tool_id, meta in sorted(tool_registry.items()):
        tools.append(tool_spec_to_openai_function({
            "tool_id": tool_id,
            "input_schema": meta.get("args_schema", {}),
            "description": meta.get("description", ""),
            "risk_level": meta.get("risk_level", "low"),
        }))
    return tools


# ── Auto-Compact ────────────────────────────────────────────────────────────

COMPACT_THRESHOLD_CHARS = 40_000  # ~10K tokens
COMPACT_KEEP_LAST_N = 6           # Keep last N messages intact


def _estimate_chars(messages: List[LLMMessage]) -> int:
    """Rough character count of all messages, including tool_call JSON."""
    total = 0
    for m in messages:
        content = m.content
        if isinstance(content, list):
            total += sum(len(str(p.get("text", ""))) for p in content if isinstance(p, dict))
        else:
            total += len(str(content or ""))
        # Count tool_calls JSON for assistant messages
        if m.tool_calls:
            total += len(json.dumps(m.tool_calls, ensure_ascii=False, default=str))
    return total


def _compact_messages(messages: List[LLMMessage]) -> List[LLMMessage]:
    """Keep first 2 (system+tools context) + last N, summarise middle."""
    if len(messages) <= COMPACT_KEEP_LAST_N + 2:
        return messages

    head = messages[:2]          # system + user request
    tail = messages[-COMPACT_KEEP_LAST_N:]  # most recent messages

    # Summarise the middle as a single user message
    middle_count = len(messages) - len(head) - len(tail)
    if middle_count <= 1:
        return messages  # 1 msg → 1 summary is a no-op; prevent infinite loop

    summary = (
        f"[{middle_count} earlier messages summarised: "
        "tools were executed and results collected. "
        "See the most recent messages below for current context.]"
    )
    return head + [LLMMessage(role="user", content=summary)] + tail


# ── Streaming Tool Executor ─────────────────────────────────────────────────

@dataclass
class StreamingToolResult:
    tool_name: str
    call_id: str
    output: dict
    ok: bool
    error: Optional[str] = None


class StreamingToolExecutor:
    """Execute tools as they arrive from the LLM stream.

    Read-only tools run in parallel; write tools serialised.
    """

    _READ_ONLY_TOOLS = {
        "device.manage", "web.manage", "knowledge.manage",
        "workspace.file", "workspace.artifact", "workspace.metadata.get",
        "workspace.document.pdf.extract_text", "code.search",
        "report.manage", "text.analyze", "config.manage", "pcap.manage",
        "data.manage", "browser.manage", "skill.manage",
        "memory.manage", "system.manage", "git.manage",
    }

    def __init__(self, tool_runtime, config: SSOTRuntimeConfig | None = None, emitter=None):
        self._runtime = tool_runtime
        self._config = config or SSOTRuntimeConfig()
        self._emitter = emitter

    def _is_read_only(self, tool_id: str) -> bool:
        # LLM emits double-underscore names (device__manage); normalize to dots
        normalized = tool_id.replace("__", ".")
        return normalized in self._READ_ONLY_TOOLS

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
        # Build result map keyed by call_id so we can return in original order
        result_by_id: dict[str, StreamingToolResult] = {}

        # --- Parallel read-only ---
        read_only = [tc for tc in tool_calls if self._is_read_only(tc.name)]
        if read_only:
            tasks = [self._execute_one(tc, ctx=ctx, budget=budget) for tc in read_only]
            # return_exceptions=True: collect every result, even if some fail
            ro_results = await asyncio.gather(*tasks, return_exceptions=True)
            for tc, r in zip(read_only, ro_results):
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

        # --- Serial writes ---
        for tc in (tc for tc in tool_calls if not self._is_read_only(tc.name)):
            result_by_id[tc.id] = await self._execute_one(tc, ctx=ctx, budget=budget)

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
            result = await asyncio.to_thread(
                self._runtime.invoke_raw, tool_id, tc.arguments
            )
            return StreamingToolResult(
                tool_name=tool_id,
                call_id=tc.id,
                output=result,
                ok=result.get("ok", False),
                error=result.get("error"),
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

        error_code = (original_result.error_code or "").strip().upper()
        if not error_code:
            err = (original_result.error or "").lower()
            if "timeout" in err or "timed out" in err:
                error_code = "TOOL_TIMEOUT"
            elif "rate" in err and "limit" in err:
                error_code = "RATE_LIMITED"
            elif "connection" in err and "reset" in err:
                error_code = "CONNECTION_RESET"
            else:
                error_code = "TOOL_EXCEPTION"

        contract = get_contract(node.tool)
        budget_ok = bool(budget.check_execution().ok) if budget is not None else True
        decision = should_retry_tool_failure(
            node=node,
            tool_contract=contract,
            error_code=error_code,
            error_message=original_result.error or "",
            config_max_retries=(
                int(getattr(contract, "max_retries", 0) or 0)
                if contract is not None else 0
            ),
            global_max_retries_per_node=self._config.max_retries_per_node,
            budget_ok=budget_ok,
        )
        self._record_retry_decision(ctx, node, decision)

        if not decision.retry_allowed:
            return original_result

        await asyncio.sleep(decision.backoff_ms / 1000.0)
        node.retry_count += 1
        retry_result = await self._runtime.execute_node(node, ctx, {})
        retry_result.retry_count = node.retry_count
        retry_result.metadata = dict(retry_result.metadata or {})
        retry_result.metadata.update({
            "retried": True,
            "retry_count": node.retry_count,
            "retry_reason": decision.reason,
            "retry_backoff_ms": decision.backoff_ms,
            "retry_error_code": decision.error_code,
            "retry_original_error": decision.notes.get("original_error", ""),
        })
        self._record_retry_result(ctx, node, retry_result)
        return retry_result

    @staticmethod
    def _record_retry_decision(ctx: StatelessContext, node: ExecutionNode, decision) -> None:
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

    @staticmethod
    def _record_retry_result(ctx: StatelessContext, node: ExecutionNode, result: ToolResult) -> None:
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
        successful_call_keys: set[str] = set()

        # Build initial messages (cacheable prefix)
        messages = self._build_initial(ctx)

        max_iterations = getattr(self._config, "max_query_loop_iterations", 20)

        while iterations < max_iterations:
            iterations += 1

            # Budget check. BudgetController is the SSOT for LLM call count;
            # local llm_calls mirrors it for QueryLoopResult only.
            budget_status = budget.check_llm_call()
            if not budget_status.ok:
                return QueryLoopResult(
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

            # Auto-compact if needed
            if _estimate_chars(messages) > COMPACT_THRESHOLD_CHARS:
                messages = _compact_messages(messages)

            # Call LLM (with streaming for tool exec)
            response = await self._call_llm(messages, ctx)

            if response is None or response.error:
                return QueryLoopResult(
                    final_response=response.content if response else "LLM 调用失败",
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

                duplicate_successes = [
                    tc for tc in tool_calls
                    if self._tool_call_key(tc) in successful_call_keys
                ]
                if duplicate_successes and len(duplicate_successes) == len(tool_calls):
                    return QueryLoopResult(
                        final_response=self._build_tool_result_fallback(ctx, all_results),
                        tool_results=all_results,
                        iterations=iterations,
                        total_tool_calls=len(all_results),
                        llm_calls=llm_calls,
                        error="duplicate_successful_tool_call",
                    )
                tool_calls = [
                    tc for tc in tool_calls
                    if self._tool_call_key(tc) not in successful_call_keys
                ]
                if not tool_calls:
                    return QueryLoopResult(
                        final_response=self._build_tool_result_fallback(ctx, all_results),
                        tool_results=all_results,
                        iterations=iterations,
                        total_tool_calls=len(all_results),
                        llm_calls=llm_calls,
                        error="duplicate_tool_call",
                    )

                gate = self._prepare_tool_calls(ctx, tool_calls)
                if not gate["ok"]:
                    return QueryLoopResult(
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
                tool_calls = gate["tool_calls"]

                # Execute tools (parallel read-only, serial writes)
                results = await self._executor.execute(tool_calls, ctx=ctx, budget=budget)
                all_results.extend(results)
                for r, tc in zip(results, tool_calls):
                    if r.ok:
                        successful_call_keys.add(self._tool_call_key(tc))

                # ── Tracking: auto-poll long tasks (e.g. inspection) ──
                polled_results = await self._settle_tracking(ctx, results, budget=budget)
                if polled_results:
                    all_results.extend(polled_results)
                    results = results + polled_results

                # Append assistant message (with tool_calls) + tool results
                messages = self._append_tool_round(messages, tool_calls, results)

                # ── Doom-loop detection ──
                for r in results:
                    if not r.ok and r.error:
                        err_lower = str(r.error).lower()
                        # Tool not found (wrong name)
                        if "not found" in err_lower:
                            key = f"not_found:{r.tool_name}"
                            failure_counts[key] = failure_counts.get(key, 0) + 1
                            if failure_counts[key] >= 3:
                                return QueryLoopResult(
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
                                return QueryLoopResult(
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
                            return QueryLoopResult(
                                final_response="已达到 LLM 调用或工具执行预算上限。请简化请求或稍后再试。",
                                tool_results=all_results,
                                iterations=iterations,
                                total_tool_calls=len(all_results),
                                llm_calls=llm_calls,
                                error="doom_loop_budget",
                            )
                        # Timeout / connection — generic doom-loop detection
                        if "timeout" in err_lower or "timed out" in err_lower or "connection" in err_lower or "network" in err_lower:
                            key = f"timeout:{r.tool_name}:{json.dumps(r.output, sort_keys=True)}"
                            failure_counts[key] = failure_counts.get(key, 0) + 1
                            if failure_counts[key] >= 3:
                                return QueryLoopResult(
                                    final_response=f"工具 {r.tool_name} 连续超时 {failure_counts[key]} 次。请检查网络连接或设备可达性。",
                                    tool_results=all_results,
                                    iterations=iterations,
                                    total_tool_calls=len(all_results),
                                    llm_calls=llm_calls,
                                    error="doom_loop_timeout",
                                )

                if not getattr(self._config, "enable_finalizer", True):
                    return QueryLoopResult(
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
            if not final_text.strip() and all_results:
                # Try LLM finalizer first, fall back to static summary
                final_text = await self._finalize_with_results(
                    ctx, messages, all_results, budget
                )
                # _finalize_with_results consumed one LLM call — update count
                llm_calls = budget.llm_calls
            elapsed = (time.monotonic() - t_start) * 1000

            return QueryLoopResult(
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
                },
            )

        # Max iterations exhausted
        return QueryLoopResult(
            final_response="已达到最大迭代次数，请检查结果。",
            tool_results=all_results,
            iterations=iterations,
            total_tool_calls=len(all_results),
            llm_calls=llm_calls,
            error="max_iterations",
        )

    # ── Private helpers ──────────────────────────────────────────────────

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _should_poll_tracking(user_input: str, tracking: dict) -> bool:
        """Check if user explicitly requested tracking (keywords like 跟踪/持续).

        IMPORTANT: Only poll when BOTH conditions are true:
        1. The task is marked as a long_task in the tracking payload
        2. The user input contains explicit tracking keywords

        v3.16: "巡检" is explicitly included because inspection tasks are
        inherently long-running and users expect completion reports.
        """
        if tracking.get("done"):
            return False
        action = str(tracking.get("suggested_next_action") or "").lower()
        if action and action != "poll_get":
            return False
        # Must be a long task to be eligible for polling
        if str(tracking.get("kind") or "") != "long_task":
            return False
        text = str(user_input or "").lower()
        explicit = any(w in text for w in (
            "巡检", "跟踪", "追踪", "等待", "持续",
            "完成后", "完成后请", "汇总", "报告",
            "track", "follow", "wait", "until complete",
        ))
        return explicit

    def _build_initial(self, ctx: StatelessContext) -> List[LLMMessage]:
        """Build initial messages with cacheable prefix."""
        conversation_block = ctx.extras.get("conversation_history_block") or ""

        user_content = (
            f"Workspace: {ctx.workspace_id}\n"
            f"Session: {ctx.session_id}\n\n"
            f"User request: {ctx.user_input}"
        )

        if conversation_block.strip():
            user_content = (
                f"Recent conversation:\n{conversation_block}\n\n"
                f"{user_content}"
            )

        return [
            LLMMessage(role="system", content=QUERY_LOOP_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_content),
        ]

    async def _call_llm(
        self,
        messages: List[LLMMessage],
        ctx: StatelessContext,
    ) -> Optional[LLMResponse]:
        """Call LLM with tools and streaming support.

        v3.17: Removed asyncio.to_thread because it runs the LLM call on a
        different thread, which loses the StreamEmitter TLS (threading.local)
        callback.  Without the callback, ``_push_stream_token`` is a no-op
        and the frontend never sees streaming tokens.
        
        We now call directly on the event-loop thread so the TLS callback
        is preserved.  The minor event-loop blocking (LLM latency) is
        acceptable for the single-user development loop.
        """
        try:
            system_prompt, stream_scope, stream_to_user = self._llm_call_mode(messages)
            if self._llm_invoke is not None:
                raw = self._llm_invoke(
                    system=system_prompt,
                    user=self._messages_to_user_text(messages),
                    temperature=0.2,
                    timeout=120,
                    tools=self._cached_tools,
                    workspace_id=ctx.workspace_id,
                    session_id=ctx.session_id,
                    extra={
                        "runtime_engine": "ssot_runtime",
                        "stream_scope": stream_scope,
                        "stream_to_user": stream_to_user,
                        "workspace_id": ctx.workspace_id,
                        "session_id": ctx.session_id,
                    },
                )
                return self._coerce_llm_response(raw)

            from agent.llm.runtime import invoke_llm
            call_messages = [
                LLMMessage(role="system", content=system_prompt),
                *messages[1:],
            ] if messages else [LLMMessage(role="system", content=system_prompt)]
            
            response = invoke_llm(
                task="query_loop",
                messages=call_messages,
                tools=self._cached_tools,
                config_override={
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "timeout": 120,
                },
            )
            return response
        except Exception as e:
            return LLMResponse(error=str(e))

    @staticmethod
    def _llm_call_mode(messages: List[LLMMessage]) -> tuple[str, str, bool]:
        has_tool_context = any(
            m.role == "tool"
            or (m.role == "user" and "AUTO TRACKING RESULTS" in str(m.content or ""))
            for m in messages
        )
        if has_tool_context:
            return QUERY_LOOP_FINALIZER_PROMPT, "finalizer", True
        return QUERY_LOOP_SYSTEM_PROMPT, "planner", False

    def _messages_to_user_text(self, messages: List[LLMMessage]) -> str:
        """Serialize loop messages for injected LLM adapters.

        The production adapter accepts ``system`` + ``user`` strings, while
        QueryLoop internally keeps OpenAI-style tool messages. This projection
        preserves the relevant context without bypassing the injected adapter.
        """
        parts: list[str] = []
        for m in messages:
            if m.role == "system":
                continue
            label = m.role.upper()
            content = m.content
            if m.tool_calls:
                parts.append(
                    f"{label} TOOL_CALLS: "
                    f"{json.dumps(m.tool_calls, ensure_ascii=False, default=str)}"
                )
            if content:
                parts.append(f"{label}: {content}")
            if m.tool_call_id:
                parts[-1:] = [f"{parts[-1]} (tool_call_id={m.tool_call_id})"] if parts else []
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
        from .pre_execution_repair import PreExecutionRepairEngine
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
            self._record_blocked_audit_nodes(ctx, nodes)
            return {
                "ok": False,
                "error": "semantic_validation_failed",
                "errors": errors,
                "hard_block": True,
                "risk_level": "high",
                "message": "工具调用被执行前校验拦截：\n" + "\n".join(f"- {e}" for e in errors),
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
            output_str = json.dumps(r.output, ensure_ascii=False, default=str)
            # Truncate large outputs
            if len(output_str) > 8000:
                output_str = output_str[:8000] + "... [truncated]"
            new_msgs.append(LLMMessage(
                role="tool",
                content=output_str,
                tool_call_id=r.call_id,
            ))

        if extra_results:
            payload = [
                {
                    "tool": r.tool_name,
                    "call_id": r.call_id,
                    "ok": r.ok,
                    "error": r.error,
                    "output": r.output,
                }
                for r in extra_results
            ]
            output_str = json.dumps(payload, ensure_ascii=False, default=str)
            if len(output_str) > 8000:
                output_str = output_str[:8000] + "... [truncated]"
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

        Polling is generic and bounded. It only runs when the user explicitly
        requested tracking (关键词: 跟踪/持续/等待) or the tool marks the payload
        as a long task.
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

            # Only poll if user explicitly asked for tracking
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
                poll_call = LLMToolCall(
                    id=poll_call_id,
                    name=tool_name,
                    arguments={"action": "get", "task_id": task_id},
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

    async def _finalize_with_results(
        self,
        ctx: StatelessContext,
        messages: List[LLMMessage],
        results: List[StreamingToolResult],
        budget,
    ) -> str:
        """Call the LLM one final time without tools to produce a natural-language
        summary from tool execution results.

        Falls back to ``_build_tool_result_fallback`` if the LLM call fails or
        the budget is exhausted.
        """
        # Budget check
        budget_status = budget.check_llm_call()
        if not budget_status.ok:
            return self._build_tool_result_fallback(ctx, results)

        # Build user prompt: original request + tool result summaries
        tool_summary_parts: list[str] = []
        for r in results:
            status = "✅" if r.ok else "❌"
            tool_summary_parts.append(
                f"- {status} `{r.tool_name}`: "
                f"{json.dumps(r.output, ensure_ascii=False, default=str)[:3000]}"
            )
        tool_results_block = "\n".join(tool_summary_parts)

        finalizer_user = (
            f"ORIGINAL REQUEST:\n{ctx.user_input}\n\n"
            f"TOOL EXECUTION RESULTS:\n{tool_results_block}\n\n"
            "Please write a clear natural-language summary of what was done, "
            "what was found, and any next steps. "
            "DO NOT call any more tools. Respond directly."
        )

        try:
            if self._llm_invoke is not None:
                raw = self._llm_invoke(
                    system=QUERY_LOOP_FINALIZER_PROMPT,
                    user=finalizer_user,
                    temperature=0.2,
                    timeout=120,
                    tools=None,  # No tools — force text-only response
                    workspace_id=ctx.workspace_id,
                    session_id=ctx.session_id,
                    extra={
                        "runtime_engine": "ssot_runtime",
                        "stream_scope": "finalizer",
                        "stream_to_user": True,
                        "workspace_id": ctx.workspace_id,
                        "session_id": ctx.session_id,
                    },
                )
                resp = self._coerce_llm_response(raw)
                if resp.content and resp.content.strip():
                    return resp.content.strip()
            else:
                from agent.llm.runtime import invoke_llm
                resp = invoke_llm(
                    task="assistant_chat",
                    messages=[
                        LLMMessage(role="system", content=QUERY_LOOP_FINALIZER_PROMPT),
                        LLMMessage(role="user", content=finalizer_user),
                    ],
                    tools=None,
                    user_input=finalizer_user,
                    extra={
                        "runtime_engine": "ssot_runtime",
                        "stream_scope": "finalizer",
                        "stream_to_user": True,
                    },
                )
                if (resp_content := (resp.content or "").strip()):
                    return resp_content
        except Exception:
            pass

        return self._build_tool_result_fallback(ctx, results)

    def _build_tool_result_fallback(
        self,
        ctx: StatelessContext,
        results: List[StreamingToolResult],
    ) -> str:
        """Build a useful final answer when the LLM returns empty text.

        This is the *last resort* — ``_finalize_with_results`` is tried first.
        When we reach here, both the iterative LLM and the dedicated finalizer
        call failed to produce a summary.  We build a structured report from
        raw tool outputs so the user still sees useful data.
        """
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        lines = [
            f"工具调用：成功 {len(ok)} 个，失败 {len(failed)} 个",
            "",
            "以下是原始结果摘要：",
        ]

        # Include successful tool outputs (truncated)
        if ok:
            lines.append("")
            lines.append("━━━ 成功工具输出 ━━━")
            for r in ok:
                output_str = json.dumps(r.output, ensure_ascii=False, default=str)
                if len(output_str) > 2000:
                    output_str = output_str[:2000] + "... [truncated]"
                lines.append(f"\n### {r.tool_name}")
                lines.append(output_str)

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

        # Failed items
        if failed:
            lines.append("")
            lines.append("━━━ 失败项 ━━━")
            for r in failed[:5]:
                err = r.error or r.output.get("summary") or r.output.get("error") or "unknown error"
                hint = self._canonical_tool_hint(r.tool_name)
                suffix = f"；应使用 `{hint}`" if hint else ""
                lines.append(f"- `{r.tool_name}`：{err}{suffix}")

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
