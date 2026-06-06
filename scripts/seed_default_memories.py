"""Seed default memories — idempotent, only writes if not already present."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.schemas import MemoryRecord
from memory.backends.jsonl_store import JSONLMemoryStore

DECISIONS = [
    {
        "memory_type": "decision",
        "scope": "long_term",
        "title": "Null0 simple static route policy",
        "content": "Simple Null0/NULL0 blackhole static routes are valid static routes and should NOT be forced to manual review unless combined with track, VRF, BFD, policy, or other complex attributes.",
        "tags": ["config_translation", "static_route", "null0"],
        "confidence": 1.0,
        "source": "user_confirmed",
        "project_id": "",
    }
]

def seed():
    store = JSONLMemoryStore()
    existing = store.search("Null0 static route")
    existing_titles = {r.get('title','') if isinstance(r,dict) else (r.title if hasattr(r,'title') else '') for r in existing}
    for d in DECISIONS:
        if d["title"] in existing_titles:
            print(f"SKIP (exists): {d['title']}")
            continue
        r = MemoryRecord(**d)
        store.put(r)
        print(f"SEEDED: {d['title']}")

if __name__ == "__main__":
    seed()
