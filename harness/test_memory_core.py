"""
Memory core tests — JSONL store put/get/search.

Memory belongs to network_agent platform.
"""

import json
import os
import tempfile
import pytest

from memory.schemas import MemoryRecord
from memory.backends.jsonl_store import JSONLMemoryStore


@pytest.fixture
def store():
    tmpdir = tempfile.mkdtemp()
    s = JSONLMemoryStore(data_dir=tmpdir)
    yield s
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestJSONLStore:
    def test_put_and_get_by_id(self, store):
        record = MemoryRecord(
            memory_type="decision",
            title="Test decision",
            content="Use OSPF as routing protocol",
        )
        rid = store.put(record)
        result = store.get(rid)
        assert result is not None
        assert result.title == "Test decision"

    def test_search(self, store):
        store.put(MemoryRecord(memory_type="decision", title="OSPF routing", content="OSPF area 0 design"))
        store.put(MemoryRecord(memory_type="knowledge", title="BGP config", content="BGP peering best practices"))
        results = store.search("OSPF")
        assert len(results) > 0

    def test_list(self, store):
        store.put(MemoryRecord(memory_type="decision", title="A", content="a"))
        store.put(MemoryRecord(memory_type="decision", title="B", content="b"))
        all_records = store.list()
        assert len(all_records) >= 2

    def test_list_by_type(self, store):
        store.put(MemoryRecord(memory_type="decision", title="D1", content="d1"))
        store.put(MemoryRecord(memory_type="knowledge", title="K1", content="k1"))
        decisions = store.list(memory_type="decision")
        assert len(decisions) > 0


class TestMemoryAPI:
    PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
    BASE = f"http://127.0.0.1:{PORT}"

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen(f"{self.BASE}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_memory_status_ok(self):
        data = self._get("/api/memory/status")
        assert data.get("backend") is not None
        assert data.get("enabled") is True
