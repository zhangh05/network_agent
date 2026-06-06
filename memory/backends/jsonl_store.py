# memory/backends/jsonl_store.py
"""JSONL-based memory store backend."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory.schemas import MemoryRecord


class JSONLMemoryStore:
    """Append-only JSONL memory store."""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "memory_records.jsonl"

    def put(self, record: MemoryRecord) -> str:
        record.updated_at = datetime.now().isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        return record.memory_id

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        for record in self._iter_all():
            if record.memory_id == memory_id:
                return record
        return None

    def search(self, query: str, tags: Optional[list] = None, limit: int = 10) -> list:
        terms = re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]+", query.lower())
        results = []
        for record in self._iter_all():
            content = (record.title + " " + record.summary + " " + record.content).lower()
            score = sum(1 for t in terms if t in content)
            if score == 0:
                continue
            if tags:
                tag_match = any(t in record.tags for t in tags)
                if not tag_match:
                    continue
            results.append({"record": record, "score": score})

        results.sort(key=lambda x: -x["score"])
        return [r["record"].as_dict() for r in results[:limit]]

    def list(self, scope: Optional[str] = None, memory_type: Optional[str] = None) -> list:
        results = []
        for record in self._iter_all():
            if scope and record.scope != scope:
                continue
            if memory_type and record.memory_type != memory_type:
                continue
            results.append(record.as_dict())
        return results

    def delete(self, memory_id: str) -> bool:
        all_records = list(self._iter_all())
        filtered = [r for r in all_records if r.memory_id != memory_id]
        if len(filtered) == len(all_records):
            return False
        with open(self._path, "w", encoding="utf-8") as f:
            for r in filtered:
                f.write(json.dumps(r.as_dict(), ensure_ascii=False) + "\n")
        return True

    def count(self) -> int:
        return sum(1 for _ in self._iter_all())

    def _iter_all(self):
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
