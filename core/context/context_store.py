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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Iterator

from workspace.ids import validate_workspace_id
from storage.paths import workspace_root


def _now_iso() -> str:
    """UTC ISO 8601 timestamp — matches workspace.session_store."""
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Workspace root helper (shared with knowledge/index.py)
# ---------------------------------------------------------------------------
def _ws_root(workspace_id: str = "default") -> Path:
    return workspace_root(validate_workspace_id(workspace_id)) / "context"


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
        self.workspace_id = validate_workspace_id(workspace_id)
        self._root = _ws_root(self.workspace_id)
        self._root.mkdir(parents=True, exist_ok=True)
        self._items_path = self._root / "items.jsonl"
        self._lock = _get_lock(self.workspace_id)

    # ---- Write ----

    def put(self, item: dict) -> str:
        """Append an item.  Returns its item_id."""
        item = dict(item)
        item_workspace = validate_workspace_id(
            str(item.get("workspace_id") or self.workspace_id)
        )
        if item_workspace != self.workspace_id:
            raise ValueError("context item workspace_id does not match store")
        item_id = item.get("item_id") or f"ci_{uuid.uuid4().hex[:12]}"
        item["item_id"] = item_id
        item.setdefault("item_type", "unknown")
        item["workspace_id"] = self.workspace_id
        item.setdefault("created_at", _now_iso())
        item.setdefault("deleted", False)

        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        return item_id

    def put_many(self, items: list[dict]) -> list[str]:
        """Batch append."""
        prepared: list[dict] = []
        for source_item in items:
            item = dict(source_item)
            item_workspace = validate_workspace_id(
                str(item.get("workspace_id") or self.workspace_id)
            )
            if item_workspace != self.workspace_id:
                raise ValueError("context item workspace_id does not match store")
            item_id = item.get("item_id") or f"ci_{uuid.uuid4().hex[:12]}"
            item["item_id"] = item_id
            item.setdefault("item_type", "unknown")
            item["workspace_id"] = self.workspace_id
            item.setdefault("created_at", _now_iso())
            item.setdefault("deleted", False)
            prepared.append(item)

        ids = []
        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                for item in prepared:
                    f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                    ids.append(item["item_id"])
        return ids

    def delete(self, item_id: str) -> bool:
        """Tombstone-delete an item."""
        with self._lock:
            with open(self._items_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "item_id": item_id,
                    "deleted": True,
                    "deleted_at": _now_iso(),
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
        seen: dict[str, dict] = {}  # last-write-wins before filtering
        for item in self._iter_raw():
            iid = item.get("item_id", "")
            if item.get("deleted"):
                if include_deleted:
                    seen[iid] = {
                        "item_id": iid,
                        "item_type": item.get("item_type", "unknown"),
                        "workspace_id": item.get("workspace_id", self.workspace_id),
                        "deleted": True,
                        "deleted_at": item.get("deleted_at", ""),
                        "created_at": item.get("created_at", ""),
                    }
                else:
                    seen.pop(iid, None)
                continue
            seen[iid] = item

        results: list[dict] = []
        for item in seen.values():
            if item_type and item.get("item_type") != item_type:
                continue
            if scope and item.get("scope") != scope:
                continue
            if source_id and item.get("source_id") != source_id:
                continue
            if tags and not set(item.get("tags") or []).intersection(tags):
                continue
            results.append(item)
        # newest first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    def count(self, item_type: Optional[str] = None) -> int:
        """Count live (non-deleted) items."""
        live: dict[str, dict] = {}
        for item in self._iter_raw():
            iid = item.get("item_id", "")
            if item.get("deleted"):
                live.pop(iid, None)
            else:
                live[iid] = item
        if item_type:
            return sum(1 for item in live.values() if item.get("item_type") == item_type)
        return len(live)

    def all_items(self, item_type: Optional[str] = None) -> list[dict]:
        """Return all live items (for indexing)."""
        return self.list_items(item_type=item_type, limit=999_999)

    # ---- Garbage Collection ----

    def purge(self, item_ids: set[str]) -> int:
        """Physically remove items from items.jsonl by rewriting the file
        without the given item_ids. Returns count of removed items."""
        if not item_ids:
            return 0
        removed = 0
        with self._lock:
            kept: list[dict] = []
            for item in self._iter_raw():
                if item.get("item_id") in item_ids or item.get("deleted"):
                    removed += 1
                    continue
                kept.append(item)

            # Atomic rewrite (same pattern as compact)
            tmp = self._items_path.with_name(
                self._items_path.name + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
            )
            fd = os.open(
                str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for item in kept:
                        f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            except Exception:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise

            if self._items_path.exists():
                bak = self._items_path.with_suffix(
                    f".bak.{time.strftime('%Y%m%d%H%M%S')}"
                )
                try:
                    import shutil
                    shutil.copy2(self._items_path, bak)
                except OSError:
                    pass

            try:
                os.replace(tmp, self._items_path)
            except Exception:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
        return removed

    def compact(self) -> dict:
        """Rewrite items.jsonl, removing tombstones and superseded versions."""
        with self._lock:
            live: dict[str, dict] = {}
            raw_count = 0
            for item in self._iter_raw():
                raw_count += 1
                iid = item.get("item_id", "")
                if item.get("deleted"):
                    live.pop(iid, None)
                else:
                    # Append-only storage is strict last-write-wins. A later
                    # put with the same item_id intentionally revives a prior
                    # tombstone (for example, a rebuilt knowledge chunk).
                    live[iid] = item

            # Atomic rewrite: write to a sibling tmp file, fsync, then
            # os.replace() into place. On failure the original file is
            # untouched, so we never lose data.
            bak = self._items_path.with_suffix(
                f".bak.{time.strftime('%Y%m%d%H%M%S')}"
            )
            # P1 fix (round 7): unique tmp name per call (pid + uuid) and
            # O_EXCL prevents concurrent compact() calls from clobbering
            # each other's tmp file. Without O_EXCL, two concurrent
            # compacts could race in os.open() with O_TRUNC and end up
            # with mixed content in the final items.jsonl.
            tmp = self._items_path.with_name(
                self._items_path.name + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
            )
            fd = os.open(
                str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for item in live.values():
                        f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            except Exception:
                # Remove partial tmp file on failure
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise

            # Copy a backup before the atomic swap. Renaming the primary
            # first would leave items.jsonl missing if os.replace failed.
            if self._items_path.exists():
                try:
                    import shutil
                    shutil.copy2(self._items_path, bak)
                except OSError as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "compact: backup copy failed (path=%s bak=%s err=%s) — proceeding without backup",
                        self._items_path, bak, e,
                    )

            try:
                os.replace(tmp, self._items_path)
            except Exception:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise

        return {
            "before": raw_count,
            "after": len(live),
            "removed": max(0, raw_count - len(live)),
            "backup": str(bak),
        }

    def cleanup_expired(self, dry_run: bool = False) -> dict:
        """Remove items past their expires_at."""
        now = _now_iso()
        expired: list[str] = []
        for item in self.all_items():
            ea = item.get("expires_at", "")
            if ea and ea < now:
                expired.append(item["item_id"])

        if not dry_run:
            if expired:
                # P1 fix (round 7): batch delete via single compact() rather
                # than N tombstone appends. N tombstones cause the JSONL
                # to grow by N lines for every cleanup run, doubling IO;
                # the next read still has to scan past every tombstone.
                # Compact once at the end gives O(N) write cost in a single
                # tmp+replace operation.
                self.delete_many(expired)
                self.compact()
            return {"expired_count": len(expired), "dry_run": dry_run, "compacted": bool(expired)}

        return {"expired_count": len(expired), "dry_run": dry_run}

    def delete_many(self, item_ids: list) -> None:
        """Mark multiple items deleted in a single write batch.

        P1 fix (round 7): writes a single tombstone line per iid under
        a single lock acquisition, instead of N independent delete()
        calls each holding/releasing the write lock. Combined with
        compact() this gives O(N) IO total for cleanup_expired().
        """
        if not item_ids:
            return
        with self._lock:
            ts = _now_iso()
            with open(self._items_path, "a", encoding="utf-8") as f:
                for iid in item_ids:
                    tombstone = {
                        "item_id": iid,
                        "deleted": True,
                        "deleted_at": ts,
                    }
                    f.write(json.dumps(tombstone, ensure_ascii=False) + "\n")

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
_stores_lock = threading.Lock()

def get_context_store(workspace_id: str = "default") -> ContextStore:
    """Return the singleton ContextStore for a workspace."""
    validated = validate_workspace_id(workspace_id)
    with _stores_lock:
        if validated not in _stores:
            _stores[validated] = ContextStore(validated)
        return _stores[validated]
