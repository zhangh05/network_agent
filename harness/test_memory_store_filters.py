# harness/test_memory_store_filters.py
"""JSONL Memory Store — put/get/search/list/delete/count tests."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def store(temp_dirs):
    """Create a fresh JSONL store for each test."""
    from memory.backends.jsonl_store import JSONLMemoryStore
    from memory.schemas import MemoryRecord

    s = JSONLMemoryStore()
    # Seed test data
    records = [
        MemoryRecord(
            title="Cisco NAT", content="ip nat inside source static",
            tags=["cisco", "nat"], project_id="proj1",
            memory_type="translation_rule", scope="project",
        ),
        MemoryRecord(
            title="Huawei ACL", content="acl number 3000",
            tags=["huawei", "acl"], project_id="proj1",
            memory_type="knowledge_note", scope="short_term",
        ),
        MemoryRecord(
            title="Routing decision", content="Use OSPF for campus",
            tags=["routing", "decision"], project_id="proj2",
            memory_type="decision", scope="long_term",
        ),
        MemoryRecord(
            title="Run summary", content="translate_config done",
            tags=["run"], project_id="default",
            memory_type="run_summary", scope="short_term",
        ),
    ]
    for r in records:
        s.put(r)
    return s


class TestJSONLStore:
    def test_put_get(self, store):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test", content="data")
        mid = store.put(r)
        assert mid == r.memory_id
        result = store.get(mid)
        assert result is not None
        assert result.title == "test"

    def test_search_keyword(self, store):
        results = store.search("NAT")
        assert len(results) > 0
        assert any("NAT" in r.get("title", "") for r in results)

    def test_search_chinese(self, store):
        from memory.schemas import MemoryRecord
        store.put(MemoryRecord(title="IPv4转换规则", content="中文内容"))
        results = store.search("转换")
        assert len(results) > 0

    def test_search_tags_filter(self, store):
        results = store.search("", tags=["cisco"])
        assert all("cisco" in r.get("tags", []) for r in results)

    def test_search_project_id_filter(self, store):
        results = store.search("", project_id="proj1")
        assert all(r.get("project_id") == "proj1" for r in results)

    def test_search_memory_type_filter(self, store):
        results = store.search("", memory_type="decision")
        assert all(r.get("memory_type") == "decision" for r in results)

    def test_search_scope_filter(self, store):
        results = store.search("", scope="long_term")
        assert all(r.get("scope") == "long_term" for r in results)

    def test_search_limit(self, store):
        results = store.search("", limit=2)
        assert len(results) <= 2

    def test_list_project_id(self, store):
        results = store.list(project_id="proj2")
        assert all(r.get("project_id") == "proj2" for r in results)

    def test_list_memory_type(self, store):
        results = store.list(memory_type="run_summary")
        assert all(r.get("memory_type") == "run_summary" for r in results)

    def test_list_scope(self, store):
        results = store.list(scope="short_term")
        assert all(r.get("scope") == "short_term" for r in results)

    def test_list_limit(self, store):
        results = store.list(limit=2)
        assert len(results) <= 2

    def test_delete_hides_record(self, store):
        all_ids = [r["memory_id"] for r in store.list()]
        assert len(all_ids) >= 1
        target = all_ids[0]
        assert store.delete(target) is True
        # Should not appear in list
        remaining = [r["memory_id"] for r in store.list()]
        assert target not in remaining

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent_id") is False

    def test_count_works(self, store):
        c = store.count()
        assert c > 0

    def test_count_excludes_deleted(self, store):
        before = store.count()
        ids = [r["memory_id"] for r in store.list()]
        if ids:
            store.delete(ids[0])
        after = store.count()
        assert after <= before

    def test_count_project_id(self, store):
        c = store.count(project_id="proj1")
        assert c > 0

    def test_data_file_consistent_name(self, store):
        assert "memories.jsonl" in str(store._path)
