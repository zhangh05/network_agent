# agent/runtime/memory_write/llm_memory.py
"""LLM-driven memory generation — ask the LLM to write its own memories.

Replaces the system extraction pipeline with a single LLM call at the end
of each turn. The LLM reviews the conversation and produces structured memory
items (JSON), which are then written through MemoryWriteGate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger("memory_write.llm_memory")

SYSTEM_PROMPT = """You are a memory curator for a network operations AI agent.

Review the conversation below and identify key facts, decisions, findings,
or patterns worth remembering for future conversations.

Return a JSON array of memory items. Each item:
- "content": max 200 chars. Write a complete sentence. Include device names,
  IPs, commands, results, or decisions. Do NOT write "tool X completed."
- "type": one of "operational_fact", "device_state", "error_lesson",
  "user_preference", "task_pattern"
- "confidence": 0.0-1.0. Higher = more certain it's worth remembering.

Only return memories that would be genuinely useful in a future conversation.
Skip trivial or redundant facts. Max 3 items. If nothing worth remembering,
return an empty array [].

Respond ONLY with valid JSON. No markdown, no explanation."""

USER_PROMPT = """Conversation:

{conversation}

Identify key memories (max 3) worth keeping for future conversations:"""


def generate_memories(
    user_input: str,
    assistant_response: str,
    tool_summaries: list[str],
    session_history: str = "",
) -> list[dict[str, Any]]:
    """Ask the LLM to produce memory items from a completed turn.

    Args:
        user_input: what the user asked
        assistant_response: the LLM's final response
        tool_summaries: list of tool call summaries (tool_id + summary)
        session_history: (unused) previous turns context

    Returns:
        list of memory candidates: [{content, type, confidence}, ...]
    """
    # Build conversation summary
    parts = [f"User: {user_input[:500]}"]
    for ts in tool_summaries[:10]:
        parts.append(f"Tool: {ts[:300]}")
    parts.append(f"Assistant: {assistant_response[:1000]}")
    conversation = "\n".join(parts)

    prompt = USER_PROMPT.format(conversation=conversation)

    # Call LLM with minimal config
    try:
        from agent.llm.runtime import invoke_llm
        from agent.llm.schemas import LLMMessage

        resp = invoke_llm(
            task="memory_generation",
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ],
        )

        if resp.error:
            _log.warning("LLM memory generation failed: %s", resp.error)
            return []

        raw = resp.content or ""
        items = _parse_json(raw)
        _log.info("LLM generated %d memory items", len(items))
        return items
    except Exception as e:
        _log.exception("LLM memory generation error")
        return []


def _parse_json(raw: str) -> list[dict[str, Any]]:
    """Parse LLM JSON response, handling common formatting issues."""
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start:end + 1]
            data = json.loads(text)
        else:
            _log.warning("LLM memory: no valid JSON in response")
            return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("content")]
    if isinstance(data, dict) and data.get("content"):
        return [data]
    return []
