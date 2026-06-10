# agent/context/compaction.py
"""Context compaction placeholder."""


def compact_history(history: list, max_messages: int = 20) -> list:
    """Keep last N messages; older ones summarized as system note."""
    if len(history) <= max_messages:
        return history
    kept = history[-max_messages:]
    summary = f"[{len(history) - max_messages} earlier messages omitted for context budget]"
    from agent.protocol.message import SystemMessage
    return [SystemMessage(content=summary)] + kept
