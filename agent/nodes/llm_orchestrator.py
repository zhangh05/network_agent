# agent/nodes/llm_orchestrator.py
"""LLM Orchestrator — agentic loop where LLM is the brain.

LLM receives all 53+ tool definitions, decides which to call,
Tool Runtime executes safely, results feed back to LLM for
further decisions or final response.
"""

import json
import time
from typing import List, Optional

from agent.state import NetworkAgentState
from agent.llm.schemas import LLMRequest, LLMMessage, LLMResponse, LLMToolCall

MAX_ORCHESTRATION_STEPS = 10


def orchestrate(state: NetworkAgentState) -> NetworkAgentState:
    """LLM-driven agentic loop: LLM decides tools → execute → loop → final answer.

    Replaces the old keyword-based tool_planner entirely.
    """
    ws_id = state.workspace_id or "default"
    user_input = state.user_input or ""

    # ── 1. Get LLM config ──
    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()
    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        state.tool_results = {"ok": True, "answer": "LLM is disabled. Cannot orchestrate tools.",
                              "mode": "llm_disabled"}
        state.skill_results = state.tool_results
        return state

    # ── 2. Build tool definitions ──
    from agent.llm.tool_adapter import list_tools_for_orchestrator, build_system_prompt_with_tools
    tools = list_tools_for_orchestrator()

    # ── 3. Build messages ──
    system_prompt = build_system_prompt_with_tools(ws_id)
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_input),
    ]

    # ── 4. Build initial request ──
    req = LLMRequest(
        task="assistant_chat",
        messages=messages,
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        tools=tools,
    )

    # ── 5. Agentic loop ──
    from agent.llm.provider import generate

    all_tool_results = []
    final_answer = ""
    step = 0

    while step < MAX_ORCHESTRATION_STEPS:
        step += 1
        resp = generate(req)

        if resp.error:
            final_answer = f"LLM error: {resp.error}"
            break

        if resp.has_tool_calls():
            # Execute each tool call
            for tc in resp.tool_calls:
                tool_result = _execute_tool(tc.name, tc.arguments, ws_id)
                all_tool_results.append({
                    "tool_id": tc.name,
                    "arguments": tc.arguments,
                    "ok": tool_result.get("ok", False),
                    "summary": _truncate(tool_result.get("summary", ""), 500),
                    "errors": tool_result.get("errors", [])[:5],
                })
                # Append tool result to conversation
                assistant_msg = LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                    }],
                )
                messages.append(assistant_msg)

                tool_msg = LLMMessage(
                    role="tool",
                    content=json.dumps(tool_result, ensure_ascii=False)[:1000],
                    tool_call_id=tc.id,
                )
                messages.append(tool_msg)

            # Update request with accumulated messages
            req = LLMRequest(
                task="assistant_chat",
                messages=messages,
                model=cfg["model"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
                tools=tools,
            )
            continue

        # No more tool calls — LLM produced final content
        final_answer = resp.content or ""
        break

    # ── 6. Set result ──
    if not final_answer:
        final_answer = "No response from LLM."

    state.tool_results = {
        "ok": True,
        "answer": final_answer,
        "tool_calls": all_tool_results,
        "steps": step,
        "mode": "llm_orchestrated",
    }
    state.skill_results = state.tool_results
    state.final_response = final_answer

    return state


def _execute_tool(tool_id: str, arguments: dict, workspace_id: str) -> dict:
    """Execute a tool through the Tool Runtime safety pipeline."""
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.schemas import ToolInvocation

        client = get_default_tool_runtime_client()
        invocation = ToolInvocation(
            tool_id=tool_id,
            arguments=arguments,
            workspace_id=workspace_id,
            requested_by="llm:orchestrator",
        )
        result = client._executor.execute(invocation)
        return {
            "ok": result.status in ("succeeded", "dry_run"),
            "status": result.status,
            "summary": result.summary,
            "output": _safe_dict(result.output),
            "errors": result.errors[:10],
            "warnings": result.warnings[:10],
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _safe_dict(d: dict) -> dict:
    """Return a sanitized shallow copy."""
    if not d:
        return {}
    result = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 1000:
            result[k] = v[:1000] + "..."
        else:
            result[k] = v
    return result
