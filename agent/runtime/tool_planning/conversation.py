# agent/runtime/tool_planning/conversation.py
"""Conversation-aware query enrichment for tool search.

When the user says "把它删了" or "查一下刚才那个", we need to resolve
the pronoun/ellipsis using recent conversation history. 

Strategy: simple history concatenation (ConvDR-style).
  - Take the last 2-3 user/assistant message pairs
  - Concatenate with the current query for tool search
  - This helps the embedding/BM25 retriever understand context

No LLM call — just text concatenation. Fast and low-latency.
"""

from __future__ import annotations

from typing import Any


def enrich_query_with_history(
    user_input: str,
    ctx: Any = None,
    max_history_turns: int = 3,
) -> str:
    """Enrich the user query with recent conversation context.
    
    When ctx has history_window (list of message dicts/objects),
    append the last few turns to the current query for better
    semantic matching.
    
    Example:
        history: ["列出CMDB设备", "AR1路由器"]
        current: "把它删了" 
        → enriched: "列出CMDB设备 AR1路由器 把它删了"
    """
    if not ctx:
        return user_input
    
    history = getattr(ctx, "history_window", None) or []
    if not history or len(history) <= 1:
        return user_input
    
    # Extract recent text content from history
    recent_texts: list[str] = []
    for msg in history[-(max_history_turns * 2):]:  # user+assistant pairs
        text = _extract_message_text(msg)
        if text:
            recent_texts.append(text)
    
    if not recent_texts:
        return user_input
    
    # Don't append if the user_input is already long (self-contained)
    if len(user_input) > 100:
        return user_input
    
    # Concatenate: recent context first, then current query
    context = " ".join(recent_texts[-max_history_turns:])
    # Avoid duplicating if current input is already in context
    if user_input in context:
        return user_input
    
    enriched = f"{context} {user_input}"
    return enriched


def _extract_message_text(msg: Any) -> str:
    """Extract text content from a message object or dict."""
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content.strip()[:200]
        if isinstance(content, list):
            # OpenAI-style content array
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            return " ".join(texts)[:200]
    if hasattr(msg, "content"):
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content.strip()[:200]
    return ""
