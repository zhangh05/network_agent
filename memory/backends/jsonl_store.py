# memory/backends/jsonl_store.py
"""JSONL-based memory store backend — unified data file, rich search/list filters."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory.schemas import MemoryRecord

# Unified data file name
DATA_FILE = "memories.jsonl"


class JSONLMemoryStore:
    """Append-only JSONL memory store with search/list/delete/count."""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / DATA_FILE
        self._deleted_path = self._dir / ".deleted_memories.json"

        # Migrate old file name
        self._migrate_old_file()

    def _migrate_old_file(self):
        """Migrate from old memory_records.jsonl to memories.jsonl."""
        old = self._dir / "memory_records.jsonl"
        if old.is_file() and not self._path.is_file():
            old.rename(self._path)
        elif old.is_file() and self._path.is_file():
            # Both exist — append old to new
            old_content = old.read_text()
            if old_content.strip():
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(old_content)
            old.unlink()

    def _get_deleted_ids(self) -> set:
        """Load tombstoned memory IDs."""
        if not self._deleted_path.is_file():
            return set()
        try:
            data = json.loads(self._deleted_path.read_text())
            return set(data.get("deleted", []))
        except Exception:
            return set()

    def _save_deleted_ids(self, ids: set):
        """Persist tombstoned IDs."""
        self._deleted_path.write_text(
            json.dumps({"deleted": list(ids)}, ensure_ascii=False)
        )

    def put(self, record: MemoryRecord) -> str:
        """Write a record. Returns memory_id."""
        record.updated_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        return record.memory_id

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        """Get a single record by ID (excludes deleted)."""
        deleted = self._get_deleted_ids()
        if memory_id in deleted:
            return None
        for record in self._iter_all():
            if record.memory_id == memory_id:
                return record
        return None

    def search(
        self,
        query: str,
        tags: Optional[list] = None,
        project_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        """Search memories with full filter support.
        
        Args:
            query: Keyword search in title+summary+content.
            tags: Filter by tags (any match).
            project_id: Filter by project.
            memory_type: Filter by type.
            scope: Filter by scope.
            limit: Max results.
        """
        deleted = self._get_deleted_ids()
        terms = re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]+", query.lower()) if query else []
        results = []

        for record in self._iter_all():
            # Exclude deleted
            if record.memory_id in deleted:
                continue

            # Keyword match
            if terms:
                content = (
                    record.title + " " + record.summary + " " + record.content
                ).lower()
                score = sum(1 for t in terms if t in content)
                if score == 0:
                    continue
            else:
                score = 1  # no keyword filter

            # Tag filter
            if tags:
                if not any(t in (record.tags or []) for t in tags):
                    continue

            # project_id filter
            if project_id and record.project_id != project_id:
                continue

            # memory_type filter
            if memory_type and record.memory_type != memory_type:
                continue

            # scope filter
            if scope and record.scope != scope:
                continue

            results.append({"record": record, "score": score})

        results.sort(key=lambda x: -x["score"])
        return [r["record"].as_dict() for r in results[:limit]]

    def list(
        self,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """List memories with optional filters.
        
        Args:
            scope: Filter by scope.
            memory_type: Filter by type.
            project_id: Filter by project.
            limit: Max results (default 100, 0 = unlimited).
        """
        deleted = self._get_deleted_ids()
        results = []

        for record in self._iter_all():
            if record.memory_id in deleted:
                continue
            if scope and record.scope != scope:
                continue
            if memory_type and record.memory_type != memory_type:
                continue
            if project_id and record.project_id != project_id:
                continue
            results.append(record.as_dict())

            if limit and len(results) >= limit:
                break

        return results

    def delete(self, memory_id: str) -> bool:
        """Tombstone-delete a memory record. API will no longer return it."""
        deleted = self._get_deleted_ids()

        # Verify record exists
        found = any(
            r.memory_id == memory_id for r in self._iter_all()
        )
        if not found:
            return False

        deleted.add(memory_id)
        self._save_deleted_ids(deleted)
        return True

    def count(self, project_id: Optional[str] = None) -> int:
        """Count active (non-deleted) records, optionally by project."""
        deleted = self._get_deleted_ids()
        total = 0
        for record in self._iter_all():
            if record.memory_id in deleted:
                continue
            if project_id and record.project_id != project_id:
                continue
            total += 1
        return total

    def _iter_all(self):
        """Iterate all records from JSONL file."""
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield MemoryRecord.from_dict(json.loads(line))
                except Exception:
                    continue
