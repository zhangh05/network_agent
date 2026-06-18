#!/usr/bin/env python3
# scripts/seed_default_memories.py
"""Seed default memory entries into unified ContextStore.

v3.1.0: Uses context.context_store directly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.context_store import get_context_store
from memory.writer import write_memory


DEFAULT_MEMORIES = [
    {
        "title": "OSPF answer style",
        "content": "When answering OSPF troubleshooting questions, start with the shortest command sequence.",
        "memory_type": "user_preference",
        "scope": "long_term",
        "tags": ["ospf", "style"],
    },
]


def seed(workspace_id: str = "default"):
    store = get_context_store(workspace_id)
    existing = store.count(item_type="memory_hit")
    if existing > 0:
        print(f"Store already has {existing} memories, skipping seed.")
        return

    for mem in DEFAULT_MEMORIES:
        mid = write_memory(
            title=mem["title"],
            content=mem["content"],
            memory_type=mem.get("memory_type", "knowledge_note"),
            scope=mem.get("scope", "long_term"),
            tags=mem.get("tags", []),
            project_id=workspace_id,
        )
        print(f"  Seeded: {mid} — {mem['title']}")

    print(f"Done. Seeded {len(DEFAULT_MEMORIES)} memories.")


if __name__ == "__main__":
    ws = sys.argv[1] if len(sys.argv) > 1 else "default"
    seed(ws)
