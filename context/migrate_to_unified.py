#!/usr/bin/env python3
# context/migrate_to_unified.py
"""Migrate existing memory + knowledge + profile data into unified ContextStore.

Usage:
    python -m context.migrate_to_unified [--workspace default] [--dry-run]

This script is idempotent: items already present (by item_id) are skipped.

v3.1.0: Created as part of P1-P5 refactoring.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from context.context_store import get_context_store


def _ws_root(workspace_id: str = "default") -> Path:
    base = Path(os.environ.get(
        "NA_WORKSPACE_ROOT",
        _project_root / "workspaces",
    ))
    return base / workspace_id


def migrate_memories(workspace_id: str, dry_run: bool = False) -> dict:
    """Migrate memory/data/memories.jsonl → ContextStore (item_type=memory_hit)."""
    mem_path = _project_root / "memory" / "data" / "memories.jsonl"
    if not mem_path.exists():
        return {"source": "memories.jsonl", "status": "not_found"}

    store = get_context_store(workspace_id)
    existing_ids = {it["item_id"] for it in store.all_items(item_type="memory_hit")}

    migrated = 0
    skipped = 0
    errors = 0

    with open(mem_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue

            if rec.get("deleted"):
                continue

            # Map MemoryRecord fields → ContextItem fields
            mem_id = rec.get("memory_id", "")
            item_id = f"mem_{mem_id}" if mem_id else f"mem_{uuid.uuid4().hex[:8]}"

            if item_id in existing_ids:
                skipped += 1
                continue

            item = {
                "item_id": item_id,
                "item_type": "memory_hit",
                "source": "memory_migration",
                "source_id": rec.get("source", ""),
                "title": rec.get("title", ""),
                "summary": rec.get("summary", ""),
                "content": rec.get("content", ""),
                "scope": rec.get("scope", "workspace"),
                "sensitivity": rec.get("sensitivity", "internal"),
                "tags": rec.get("tags", []),
                "memory_id": mem_id,
                "memory_type": rec.get("memory_type", ""),
                "confidence": rec.get("confidence", ""),
                "workspace_id": rec.get("workspace_id", rec.get("project_id", "")),
                "expires_at": rec.get("expires_at", ""),
                "priority": 0,
                "metadata": rec.get("metadata", {}),
                "redaction_applied": rec.get("redaction_applied", False),
                "created_at": rec.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
            }

            if not dry_run:
                store.put(item)
            migrated += 1

    return {
        "source": "memories.jsonl",
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
    }


def migrate_knowledge_chunks(workspace_id: str, dry_run: bool = False) -> dict:
    """Migrate sys/knowledge/chunks.jsonl → ContextStore (item_type=knowledge_chunk)."""
    chunks_path = _ws_root(workspace_id) / "sys" / "knowledge" / "chunks.jsonl"
    if not chunks_path.exists():
        return {"source": "chunks.jsonl", "status": "not_found"}

    store = get_context_store(workspace_id)
    existing_ids = {it["item_id"] for it in store.all_items(item_type="knowledge_chunk")}

    migrated = 0
    skipped = 0
    errors = 0

    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue

            if chunk.get("deleted") or not chunk.get("enabled", True):
                continue

            chunk_id = chunk.get("chunk_id", "")
            item_id = f"kc_{chunk_id}" if chunk_id else f"kc_{uuid.uuid4().hex[:8]}"

            if item_id in existing_ids:
                skipped += 1
                continue

            item = {
                "item_id": item_id,
                "item_type": "knowledge_chunk",
                "source": "knowledge_migration",
                "source_id": chunk.get("source_id", ""),
                "title": chunk.get("title", "") or chunk.get("chapter", ""),
                "summary": "",
                "content": chunk.get("content", ""),
                "scope": chunk.get("scope", "workspace"),
                "sensitivity": "internal",
                "chunk_id": chunk_id,
                "parent_chunk_id": chunk.get("parent_chunk_id", ""),
                "chunk_type": chunk.get("chunk_type", "child"),
                "chapter": chunk.get("chapter", ""),
                "section": chunk.get("section", ""),
                "subsection": chunk.get("subsection", ""),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "chunk_index": chunk.get("chunk_index", 0),
                "index_text": chunk.get("index_text", ""),
                "token_count": chunk.get("token_count", 0),
                "source_type": chunk.get("source_type", ""),
                "tags": chunk.get("tags", []),
                "author": chunk.get("author", ""),
                "language": chunk.get("language", ""),
                "priority": 0,
                "metadata": chunk.get("metadata", {}),
                "redaction_applied": False,
                "created_at": chunk.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
            }

            if not dry_run:
                store.put(item)
            migrated += 1

    return {
        "source": "chunks.jsonl",
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
    }


def migrate_profile(workspace_id: str, dry_run: bool = False) -> dict:
    """Migrate sys/memory/profile.json → ContextStore (item_type=profile)."""
    profile_path = _ws_root(workspace_id) / "sys" / "memory" / "profile.json"
    if not profile_path.exists():
        return {"source": "profile.json", "status": "not_found"}

    store = get_context_store(workspace_id)
    existing = store.list_items(item_type="profile", limit=1)
    if existing:
        return {"source": "profile.json", "status": "already_migrated"}

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"source": "profile.json", "status": "read_error"}

    item = {
        "item_id": f"profile_{workspace_id}",
        "item_type": "profile",
        "source": "profile_migration",
        "title": "User Profile",
        "summary": json.dumps(profile, ensure_ascii=False)[:200],
        "content": profile if isinstance(profile, dict) else {"raw": str(profile)},
        "scope": "workspace",
        "sensitivity": "internal",
        "priority": 10,  # profiles should rank high
        "metadata": {},
    }

    if not dry_run:
        store.put(item)

    return {"source": "profile.json", "migrated": 1}


def run_migration(workspace_id: str = "default", dry_run: bool = False) -> dict:
    """Run full migration."""
    print(f"{'[DRY RUN] ' if dry_run else ''}Migrating workspace: {workspace_id}")

    results = {
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "memory": migrate_memories(workspace_id, dry_run),
        "knowledge": migrate_knowledge_chunks(workspace_id, dry_run),
        "profile": migrate_profile(workspace_id, dry_run),
    }

    # Summary
    total_migrated = sum(
        r.get("migrated", 0)
        for r in [results["memory"], results["knowledge"], results["profile"]]
    )
    results["total_migrated"] = total_migrated

    print(f"Migration complete: {total_migrated} items migrated")
    for key in ("memory", "knowledge", "profile"):
        print(f"  {key}: {results[key]}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate to unified ContextStore")
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_migration(args.workspace, args.dry_run)
