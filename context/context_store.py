# context/context_store.py
"""Unified ContextStore — single JSONL-backed store for all retrievable items.

All items share a common schema (ContextItem) and are differentiated
by ``item_type`` (memory_hit, knowledge_chunk, knowledge_source, profile).  The store supports:
  - CRUD by item_id
  - Listing / filtering by item_type, scope, tags
  - Garbage collection (tombstone compaction + expired-item removal)

Thread-safe via per-workspace RLock.

v3.1.0: Created as part of P1-P5 refactoring.
"""

from __future__ import annotations

import json
import os
import time
import threading
import uuid
from pathlib import Path
from typing import Optional, Iterator

# ---------------------------------------------------------------------------
# Workspace root helper (shared with knowledge/index.py)
# ---------------------------------------------------------------------------
_BASE = None

def _ws_root(workspace_id: str = "default") -> Path:
    global _BASE
    if _BASE is None:
        _BASE = Path(os.environ.get(
            "NA_WORKSPACE_ROOT",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspaces"),
        ))
    return _BASE / workspace_id / "context"


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------
_locks: dict[str, threading.RLock] = {}
_lock_guard = threading.Lock()

def _get_lock(workspace_id: str) -> threading.RLock:
    with _lock_guard:
        if workspace_id not in _locks:
            _locks[workspace_id] = threading.RLock()
        return _locks[workspace_id]


# ---------------------------------------------------------------------------
# ContextStore
# ---------------------------------------------------------------------------

class ContextStore:
    """Unified JSONL-backed item store."""

    def __init__(self, workspace_id: str = "default"):
        self.workspace_id = workspace_id
        self._root = _ws_root(workspace_id)
        self._root.mkdir(parents=True, exist_ok=True)
        self._items_path = self._root / "items.jsonl"
        self._lock = _get_lock(workspace_id)

    # ---- Write ----

    def put(self, item: dict) -> str:
        """Append an item.  Returns its item_id."""
        item_id = item.get("item_id") or f"ci_{uuid.uuid4().hex[:12]}"
        item["item_id"] = item_id
        item.setdefault("item_type", "unknown")
        item.setdefault("workspace_id", self.workspace_id)
        item.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        item.setdefault("deleted", False)

        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        return item_id

    def put_many(self, items: list[dict]) -> list[str]:
        """Batch append."""
        ids = []
        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                for item in items:
                    item_id = item.get("item_id") or f"ci_{uuid.uuid4().hex[:12]}"
                    item["item_id"] = item_id
                    item.setdefault("item_type", "unknown")
                    item.setdefault("workspace_id", self.workspace_id)
                    item.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
                    item.setdefault("deleted", False)
                    f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                    ids.append(item_id)
        return ids

    def delete(self, item_id: str) -> bool:
        """Tombstone-delete an item."""
        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "item_id": item_id,
                    "deleted": True,
                    "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, ensure_ascii=False) + "\n")
        return True

    # ---- Read ----

    def get(self, item_id: str) -> Optional[dict]:
        """Return the latest version of an item, or None."""
        result = None
        for item in self._iter_raw():
            if item.get("item_id") == item_id:
                if item.get("deleted"):
                    result = None
                else:
                    result = item
        return result

    def list_items(
        self,
        item_type: Optional[str] = None,
        scope: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source_id: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        """List items with optional filters."""
        seen: dict[str, dict] = {}  # last-write-wins
        for item in self._iter_raw():
            iid = item.get("item_id", "")
            if item.get("deleted"):
                seen.pop(iid, None)
                continue
            if item_type and item.get("item_type") != item_type:
                continue
            if scope and item.get("scope") != scope:
                continue
            if source_id and item.get("source_id") != source_id:
                continue
            if tags:
                item_tags = set(item.get("tags") or [])
                if not item_tags.intersection(tags):
                    continue
            seen[iid] = item

        if include_deleted:
            # re-scan to include deleted
            pass  # TODO if needed

        results = list(seen.values())
        # newest first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    def count(self, item_type: Optional[str] = None) -> int:
        """Count live (non-deleted) items."""
        seen: set[str] = set()
        deleted: set[str] = set()
        for item in self._iter_raw():
            iid = item.get("item_id", "")
            if item.get("deleted"):
                deleted.add(iid)
                seen.discard(iid)
            else:
                if item_type and item.get("item_type") != item_type:
                    continue
                if iid not in deleted:
                    seen.add(iid)
        return len(seen)

    def all_items(self, item_type: Optional[str] = None) -> list[dict]:
        """Return all live items (for indexing)."""
        return self.list_items(item_type=item_type, limit=999_999)

    # ---- Garbage Collection ----

    def compact(self) -> dict:
        """Rewrite items.jsonl, removing tombstones and superseded versions."""
        with self._lock:
            live: dict[str, dict] = {}
            deleted: set[str] = set()
            for item in self._iter_raw():
                iid = item.get("item_id", "")
                if item.get("deleted"):
                    deleted.add(iid)
                    live.pop(iid, None)
                else:
                    if iid not in deleted:
                        live[iid] = item

            # Backup
            bak = self._items_path.with_suffix(
                f".bak.{time.strftime('%Y%m%d%H%M%S')}"
            )
            if self._items_path.exists():
                self._items_path.rename(bak)

            # Rewrite
            with open(self._items_path, "w", encoding="utf-8") as f:
                for item in live.values():
                    f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        return {
            "before": len(live) + len(deleted),
            "after": len(live),
            "removed": len(deleted),
            "backup": str(bak),
        }

    def cleanup_expired(self, dry_run: bool = False) -> dict:
        """Remove items past their expires_at."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        expired: list[str] = []
        for item in self.all_items():
            ea = item.get("expires_at", "")
            if ea and ea < now:
                expired.append(item["item_id"])

        if not dry_run:
            for iid in expired:
                self.delete(iid)

        return {"expired_count": len(expired), "dry_run": dry_run}

    # ---- Internal ----

    def _iter_raw(self) -> Iterator[dict]:
        """Yield every line from items.jsonl."""
        if not self._items_path.exists():
            # Ensure directory exists for future writes
            self._root.mkdir(parents=True, exist_ok=True)
            return
        with self._lock:
            with open(self._items_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------
_stores: dict[str, ContextStore] = {}

def get_context_store(workspace_id: str = "default") -> ContextStore:
    """Return the singleton ContextStore for a workspace."""
    if workspace_id not in _stores:
        _stores[workspace_id] = ContextStore(workspace_id)
    return _stores[workspace_id]
