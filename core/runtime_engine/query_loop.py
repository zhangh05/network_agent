"""
QueryLoop — iterative LLM + tool execution engine.

Replaces the Planner → Compile → Execute → Finalizer pipeline with a
single agentic loop that merges planning and finalization into one
LLM stream, feeds tool results back for iterative refinement, and
auto-compacts long conversations.

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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import SSOTRuntimeConfig, StatelessContext
from .tracking import extract_tracking_payload, normalize_tracking_payload
from agent.llm.schemas import LLMMessage, LLMResponse, LLMToolCall
from agent.llm.tool_adapter import tool_spec_to_openai_function


# ── Prompt Cache ────────────────────────────────────────────────────────────

# Static prefix that never changes between turns — cached by the LLM API.
QUERY_LOOP_SYSTEM_PROMPT = """You are a network operations AI agent. You have access to tools for:
- Device health inspection (inspection.manage)
- Remote command execution via SSH/Telnet (exec.run)
- CMDB device management (device.manage)
- Web search and information retrieval (web.manage)
- File reading and workspace operations (workspace.file, workspace.artifact)
- Network configuration analysis (config.manage)
- Packet capture analysis (pcap.manage)
- Knowledge base search (knowledge.manage)
- Memory and preferences (memory.manage)
- Report generation (report.manage)
- Data analysis (data.manage)
- Text analysis (text.analyze)
- Code search (code.search)
- Git operations (git.manage)
- System diagnostics (system.manage)
- Browser automation (browser.manage)
- Skill management (skill.manage)
- Agent orchestration (agent.manage)
- Workspace metadata (workspace.metadata.get)
- PDF extraction (workspace.document.pdf.extract_text)
- FileStore operations (workspace.filestore)

Work step by step. Call tools to gather information, then reason about the
results. When you have enough information, provide a final answer directly
without calling more tools.

RULES:
1. Use tools to get real data; never fabricate device states or command outputs.
2. For inspection tasks: use inspection.manage(action="run") to start, then
   inspection.manage(action="task_get") to check status.
3. For SSH access: use exec.run(action="shell", target="ssh", asset_id=...).
4. If a tool returns an error, try an alternative approach before giving up.
5. After all tool results are in, respond directly without calling more tools."""


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

    def __init__(self, tool_runtime, emitter=None):
        self._runtime = tool_runtime
        self._emitter = emitter

    def _is_read_only(self, tool_id: str) -> bool:
        # LLM emits double-underscore names (device__manage); normalize to dots
        normalized = tool_id.replace("__", ".")
        return normalized in self._READ_ONLY_TOOLS

    async def execute(self, tool_calls: List[LLMToolCall]) -> List[StreamingToolResult]:
        """Execute tool calls. Read-only parallel, writes serialised."""
        results: List[StreamingToolResult] = []

        # Group: first all read-only (parallel), then writes (serial)
        read_only = [tc for tc in tool_calls if self._is_read_only(tc.name)]
        writes = [tc for tc in tool_calls if not self._is_read_only(tc.name)]

        # Parallel read-only
        if read_only:
            tasks = [self._execute_one(tc) for tc in read_only]
            results.extend(await asyncio.gather(*tasks))

        # Serial writes
        for tc in writes:
            results.append(await self._execute_one(tc))

        return results

    async def _execute_one(self, tc: LLMToolCall) -> StreamingToolResult:
        """Execute a single tool call via the tool runtime client."""
        try:
            # Map LLM name (dots → underscores) back to canonical tool_id
            tool_id = tc.name.replace("__", ".")
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


# ── QueryLoop ────────────────────────────────────────────────────────────────

@dataclass
class QueryLoopResult:
    final_response: str
    tool_results: List[StreamingToolResult] = field(default_factory=list)
    iterations: int = 0
    total_tool_calls: int = 0
    llm_calls: int = 0
    error: Optional[str] = None
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
        emitter=None,
    ):
        self._config = config
        self._tool_registry = tool_registry
        self._tool_runtime = tool_runtime
        self._emitter = emitter
        self._executor = StreamingToolExecutor(tool_runtime, emitter)
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

        # Build initial messages (cacheable prefix)
        messages = self._build_initial(ctx)

        max_iterations = getattr(self._config, "max_query_loop_iterations", 20)

        while iterations < max_iterations:
            iterations += 1

            # Budget check
            if llm_calls >= getattr(budget, "max_llm_calls", 30):
                return QueryLoopResult(
                    final_response="已达到 LLM 调用上限，请简化请求。",
                    tool_results=all_results,
                    iterations=iterations,
                    total_tool_calls=len(all_results),
                    llm_calls=llm_calls,
                    error="budget_exceeded",
                )

            # Auto-compact if needed
            if _estimate_chars(messages) > COMPACT_THRESHOLD_CHARS:
                messages = _compact_messages(messages)

            # Call LLM (with streaming for tool exec)
            response = await self._call_llm(messages)

            if response is None or response.error:
                return QueryLoopResult(
                    final_response=response.content if response else "LLM 调用失败",
                    tool_results=all_results,
                    iterations=iterations,
                    total_tool_calls=len(all_results),
                    llm_calls=llm_calls,
                    error=response.error if response else "no_response",
                )

            llm_calls += 1

            # Check for tool calls
            if response.tool_calls:
                # Convert to LLMToolCall objects
                tool_calls = self._parse_tool_calls(response.tool_calls)

                # Execute tools (parallel read-only, serial writes)
                results = await self._executor.execute(tool_calls)
                all_results.extend(results)

                # ── Tracking: auto-poll long tasks (e.g. inspection) ──
                polled_results = await self._settle_tracking(ctx, results)
                if polled_results:
                    all_results.extend(polled_results)
                    results = results + polled_results

                # Append assistant message (with tool_calls) + tool results
                messages = self._append_tool_round(messages, tool_calls, results)
                continue

            # No tool calls → final response
            final_text = response.content or ""
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
        """Check if user explicitly requested tracking (keywords like 跟踪/持续)."""
        if tracking.get("done"):
            return False
        action = str(tracking.get("suggested_next_action") or "").lower()
        if action and action != "poll_task_get":
            return False
        text = str(user_input or "").lower()
        explicit = any(w in text for w in (
            "跟踪", "追踪", "等待", "持续", "结果", "完成", "巡检",
            "track", "follow", "wait", "until complete",
        ))
        return explicit or str(tracking.get("kind") or "") == "long_task"

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
        self, messages: List[LLMMessage]
    ) -> Optional[LLMResponse]:
        """Call LLM with tools and streaming support.
        
        Uses agent.llm.runtime.invoke_llm directly — bypasses the
        Planner-focused wrapper (_invoke_llm_for_ssot_runtime) which
        converts LLMResponse tool_calls into PlanNode JSON strings.
        """
        try:
            from agent.llm.runtime import invoke_llm
            
            response = await asyncio.to_thread(
                invoke_llm,
                task="query_loop",
                messages=messages,
                tools=self._cached_tools,
                config_override={
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "timeout": 120,  # seconds for HTTP request
                },
            )
            return response
        except Exception as e:
            return LLMResponse(error=str(e))

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
            
            result.append(LLMToolCall(
                id=str(tid),
                name=tname,
                arguments=args,
            ))
        return result

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

        # Tool result messages
        for r in results:
            output_str = json.dumps(r.output, ensure_ascii=False, default=str)
            # Truncate large outputs
            if len(output_str) > 8000:
                output_str = output_str[:8000] + "... [truncated]"
            new_msgs.append(LLMMessage(
                role="tool",
                content=output_str,
                tool_call_id=r.call_id,
            ))

        return new_msgs

    # ── Tracking / Polling ──────────────────────────────────────────────

    async def _settle_tracking(
        self,
        ctx: StatelessContext,
        results: List[StreamingToolResult],
    ) -> List[StreamingToolResult]:
        """After tool execution, auto-poll long tasks (e.g. inspection).

        Mirrors _settle_tracking_tasks from the legacy pipeline.
        Only polls if user explicitly requested tracking (关键词: 跟踪/持续/等待).
        Uses the tool's canonical name for task_get calls.
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

            poll_index = 0
            while poll_index < max_polls and time.monotonic() < deadline:
                if tracking.get("done"):
                    break

                wait_s = self._tracking_wait(tracking, cap_seconds, deadline)
                if wait_s > 0:
                    await asyncio.sleep(wait_s)

                poll_index += 1
                poll_call = LLMToolCall(
                    id=f"{r.call_id}_poll_{poll_index}",
                    name=tool_name,
                    arguments={"action": "task_get", "task_id": task_id},
                )
                poll_result = await self._executor._execute_one(poll_call)
                poll_result.call_id = r.call_id  # group under original call
                polled.append(poll_result)

                tracking = extract_tracking_payload(poll_result.output)
                if tracking:
                    tracking = normalize_tracking_payload(tracking)

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

    # ── Private helpers ──────────────────────────────────────────────────
