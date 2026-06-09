# agent/nodes/llm_orchestrator.py
"""LLM Orchestrator — agentic loop where LLM is the brain.

LLM receives all 53+ tool definitions, decides which to call,
Tool Runtime executes safely, results feed back to LLM for
further decisions or final response.
"""

import json
import re
import time
from typing import List, Optional

from agent.state import NetworkAgentState
from agent.llm.schemas import LLMRequest, LLMMessage, LLMResponse, LLMToolCall

MAX_ORCHESTRATION_STEPS = 10


def orchestrate(state: NetworkAgentState) -> NetworkAgentState:
    """LLM-driven agentic loop: LLM decides tools -> execute -> loop -> final answer.

    Replaces the old keyword-based tool_planner entirely.
    """
    ws_id = state.workspace_id or "default"
    user_input = state.user_input or ""

    # 1. Get LLM config
    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()
    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        state.tool_results = {"ok": True, "answer": "LLM is disabled. Cannot orchestrate tools.",
                              "mode": "llm_disabled"}
        state.skill_results = state.tool_results
        return state

    # 2. Build tool definitions
    from agent.llm.tool_adapter import list_tools_for_orchestrator, build_system_prompt_with_tools
    tools = list_tools_for_orchestrator()

    # 3. Build messages with session history
    system_prompt = build_system_prompt_with_tools(ws_id)
    messages = [LLMMessage(role="system", content=system_prompt)]

    # Load recent conversation history if session exists
    session_id = getattr(state, 'session_id', None)
    if session_id:
        try:
            from workspace.session_store import get_session_messages
            history = get_session_messages(session_id, ws_id)
            recent = history[-8:]  # Last 4 turns (8 messages) max
            for m in recent:
                role = m.get("role", "user")
                content = (m.get("content") or "")[:1000]
                if role in ("user", "assistant"):
                    messages.append(LLMMessage(role=role, content=content))
        except Exception:
            pass

    messages.append(LLMMessage(role="user", content=user_input))

    # 4. Build initial request
    req = LLMRequest(
        task="assistant_chat",
        messages=messages,
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        tools=tools,
    )

    # 5. Agentic loop
    from agent.llm.provider import generate

    all_tool_results = []
    final_answer = ""
    step = 0

    while step < MAX_ORCHESTRATION_STEPS:
        step += 1
        try:
            resp = generate(req)
        except Exception as e:
            final_answer = _build_partial_answer(all_tool_results, str(e)[:200])
            break

        if resp.error:
            if step == 1:
                final_answer = f"LLM error: {resp.error}"
            else:
                final_answer = _build_partial_answer(all_tool_results, resp.error)
            break

        if resp.has_tool_calls():
            for tc in resp.tool_calls:
                tool_result = _execute_tool(tc.name, tc.arguments, ws_id)
                all_tool_results.append({
                    "tool_id": tc.name,
                    "arguments": tc.arguments,
                    "ok": tool_result.get("ok", False),
                    "summary": _truncate(tool_result.get("summary", ""), 500),
                    "errors": tool_result.get("errors", [])[:5],
                })
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

            req = LLMRequest(
                task="assistant_chat",
                messages=messages,
                model=cfg["model"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
                tools=tools,
            )
            continue

        final_answer = _clean_response(resp.content)
        break

    # 6. Set result
    if not final_answer:
        final_answer = _build_partial_answer(all_tool_results, "no response")
        state.warnings.append(f"orchestration max steps ({MAX_ORCHESTRATION_STEPS}) reached")

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


def _truncate(text, max_len: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s[:max_len] + ("..." if len(s) > max_len else "")


def _clean_response(text: str) -> str:
    """Remove provider reasoning markup from LLM output."""
    if not text:
        return ""
    t = text
    t = re.sub(r"<think\b[^>]*>.*?</think>", "", t, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", t, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"(?ism)^\s*(思考|思考过程|reasoning)\s*[:：].*?(?=\n\s*(回答|答案|answer|conclusion)\s*[:：]|\Z)", "", t)
    t = re.sub(r"(?i)</?(think|reasoning)\b[^>]*>", "", t)
    cleaned = t.strip()
    if cleaned:
        return cleaned
    # If all content was inside think tags, return a fallback message instead of raw think content
    if text.strip() and (text.strip() != cleaned):
        return "思考过程已过滤。请重新描述您的问题。"
    return text.strip()


def _build_partial_answer(tool_results: list, error: str) -> str:
    """Build a partial answer when LLM fails after some tool calls."""
    if not tool_results:
        return f"LLM error: {error}"
    successes = [r for r in tool_results if r.get("ok")]
    msg = f"部分工具执行完成（{len(successes)}/{len(tool_results)} 成功），但 LLM 处理出错：{error}"
    for r in tool_results[:3]:
        msg += f"\n- {r.get('tool_id', '')}: {'OK' if r.get('ok') else 'FAILED'}"
    return msg


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
