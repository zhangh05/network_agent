# harness/test_knowledge_store_v10.py
"""Tests for v1.0 Knowledge Store Management.

Coverage:
  1.  import_document creates source_id
  2.  list_sources returns imported source
  3.  read_source returns content
  4.  read_source not found returns None
  5.  disable_source excludes it from query
  6.  delete_source removes or marks deleted
  7.  query returns real hit
  8.  query no hits returns empty source_summary
  9.  query empty store does not fabricate
  10. source_summary snippet <= 200
  11. knowledge.import_document tool works
  12. knowledge.list_sources tool works
  13. knowledge.read_source tool works
  14. knowledge.disable_source tool works
  15. CapabilityRegistry exposes new knowledge tools
  16. planned topology/inspection/cmdb still not visible
  + extra: delete_source via tool, query backend metadata, etc.
"""

import pytest
from pathlib import Path

from agent.capabilities import get_default_capability_registry
from agent.capabilities.builtin import reset_default_capability_registry_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_default_capability_registry_cache()
    yield
    reset_default_capability_registry_cache()


@pytest.fixture
def reg():
    return get_default_capability_registry()


@pytest.fixture
def fresh_ws(temp_dirs):
    """Create a fresh workspace id for each test (uses conftest temp_dirs)."""
    return f"test_ws_v10_{id(object())}"


# ── 1. import_document creates source_id ──
class TestImportDocument:
    def test_creates_stable_source_id(self, fresh_ws):
        from agent.modules.knowledge.store import import_document
        out = import_document(
            workspace_id=fresh_ws,
            title="OSPF 协议介绍",
            content="OSPF 是一种链路状态路由协议。",
            source="rfc2328",
            metadata={"category": "rfc"},
        )
        assert out["ok"] is True
        assert "source_id" in out["source"]
        sid = out["source"]["source_id"]
        assert sid.startswith("ksrc_")
        assert len(sid) == 21  # ksrc_ + 16 hex


# ── 2. list_sources returns imported source ──
class TestListSources:
    def test_returns_imported_source(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, list_sources
        import_document(workspace_id=fresh_ws, title="Doc1",
                        content="hello world", source="rfc1")
        sources = list_sources(workspace_id=fresh_ws)
        assert len(sources) == 1
        s = sources[0]
        assert s["title"] == "Doc1"
        assert s["source"] == "rfc1"
        assert s["enabled"] is True
        assert "created_at" in s
        # No content in list view
        assert "content" not in s
        # No local paths leak
        for k in ("path", "file_path", "local_path"):
            assert k not in s


# ── 3. read_source returns content ──
class TestReadSource:
    def test_returns_full_record(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, read_source
        out = import_document(workspace_id=fresh_ws, title="T",
                              content="Body content", source="rfc")
        sid = out["source"]["source_id"]
        rec = read_source(workspace_id=fresh_ws, source_id=sid)
        assert rec is not None
        assert rec["content"] == "Body content"
        assert rec["title"] == "T"
        assert rec["source"] == "rfc"


# ── 4. read_source not found returns None ──
class TestReadSourceNotFound:
    def test_missing_returns_none(self, fresh_ws):
        from agent.modules.knowledge.store import read_source
        rec = read_source(workspace_id=fresh_ws, source_id="ksrc_does_not_exist")
        assert rec is None


# ── 5. disable_source excludes it from query ──
class TestDisableSource:
    def test_disabled_source_excluded_from_query(self, fresh_ws):
        from agent.modules.knowledge.store import (
            import_document, disable_source, query,
        )
        out = import_document(workspace_id=fresh_ws, title="OSPF",
                              content="OSPF 协议 内容", source="rfc2328")
        sid = out["source"]["source_id"]
        # First verify it matches
        r1 = query(workspace_id=fresh_ws, query="OSPF")
        assert r1["source_count"] >= 1
        # Disable
        disabled = disable_source(workspace_id=fresh_ws, source_id=sid)
        assert disabled is not None
        assert disabled["enabled"] is False
        # Now query should not return it
        r2 = query(workspace_id=fresh_ws, query="OSPF")
        assert r2["source_count"] == 0
        assert r2["hits"] == []
        assert r2["source_summary"] == []

    def test_re_enable(self, fresh_ws):
        from agent.modules.knowledge.store import (
            import_document, disable_source, query,
        )
        out = import_document(workspace_id=fresh_ws, title="OSPF",
                              content="OSPF 协议 内容", source="rfc2328")
        sid = out["source"]["source_id"]
        disable_source(workspace_id=fresh_ws, source_id=sid, disabled=True)
        # Re-enable
        re = disable_source(workspace_id=fresh_ws, source_id=sid, disabled=False)
        assert re["enabled"] is True
        r = query(workspace_id=fresh_ws, query="OSPF")
        assert r["source_count"] >= 1


# ── 6. delete_source removes or marks deleted ──
class TestDeleteSource:
    def test_soft_delete_marks_record(self, fresh_ws):
        from agent.modules.knowledge.store import (
            import_document, delete_source, read_source, list_sources,
        )
        out = import_document(workspace_id=fresh_ws, title="OSPF",
                              content="OSPF", source="rfc")
        sid = out["source"]["source_id"]
        ok = delete_source(workspace_id=fresh_ws, source_id=sid)
        assert ok is True
        # read_source returns None for soft-deleted
        rec = read_source(workspace_id=fresh_ws, source_id=sid)
        assert rec is None
        # list_sources does NOT include deleted
        srcs = list_sources(workspace_id=fresh_ws)
        assert all(s["source_id"] != sid for s in srcs)
        # but list_sources with include_deleted=True DOES
        srcs2 = list_sources(workspace_id=fresh_ws, include_deleted=True)
        assert any(s["source_id"] == sid for s in srcs2)
        assert any(s["deleted"] is True for s in srcs2)

    def test_delete_missing_returns_false(self, fresh_ws):
        from agent.modules.knowledge.store import delete_source
        ok = delete_source(workspace_id=fresh_ws, source_id="ksrc_missing")
        assert ok is False


# ── 7. query returns real hit ──
class TestQueryRealHit:
    def test_returns_real_hit(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, query
        import_document(workspace_id=fresh_ws,
                        title="OSPF 协议介绍",
                        content="OSPF 是一种链路状态路由协议，基于 Dijkstra 算法。",
                        source="rfc2328",
                        metadata={"category": "rfc"})
        import_document(workspace_id=fresh_ws,
                        title="BGP 协议介绍",
                        content="BGP 是一种路径向量协议。",
                        source="rfc4271",
                        metadata={"category": "rfc"})
        r = query(workspace_id=fresh_ws, query="OSPF 路由")
        assert r["ok"] is True
        assert r["source_count"] >= 1
        # Top hit must be the OSPF doc
        top = r["hits"][0]
        assert "OSPF" in top["title"] or "OSPF" in top["content"]
        assert top["score"] > 0
        # backend must be local_store
        assert r["metadata"]["retrieval_backend"] == "local_store"


# ── 8. query no hits returns empty source_summary ──
class TestQueryNoHits:
    def test_no_hits_empty_summary(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, query
        import_document(workspace_id=fresh_ws, title="BGP",
                        content="BGP content", source="rfc4271")
        r = query(workspace_id=fresh_ws, query="totally-unrelated-xyz")
        assert r["ok"] is True
        assert r["source_count"] == 0
        assert r["hits"] == []
        assert r["source_summary"] == []


# ── 9. query empty store does not fabricate ──
class TestQueryEmptyStore:
    def test_empty_store_no_fabrication(self, fresh_ws):
        from agent.modules.knowledge.store import query
        r = query(workspace_id=fresh_ws, query="anything")
        assert r["ok"] is True
        assert r["source_count"] == 0
        assert r["hits"] == []
        assert r["source_summary"] == []
        # No fabricated sources
        for s in r.get("source_summary", []):
            assert s.get("title")
            assert s.get("snippet") == ""  # no fake content


# ── 10. source_summary snippet <= 200 ──
class TestSnippetLength:
    def test_snippet_capped(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, query
        long_content = "OSPF " + ("a" * 5000)
        import_document(workspace_id=fresh_ws, title="OSPF",
                        content=long_content, source="rfc")
        r = query(workspace_id=fresh_ws, query="OSPF")
        assert r["source_count"] >= 1
        for s in r["source_summary"]:
            assert len(s["snippet"]) <= 200


# ── 11-14. Tool handler tests ──
class TestToolHandlers:
    def test_import_document_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import tool_handler_import
        out = tool_handler_import({
            "workspace_id": fresh_ws,
            "title": "Test Doc",
            "content": "OSPF 协议内容",
            "source": "rfc",
        })
        for f in ("call_id", "tool_id", "ok", "summary", "artifacts",
                  "source_count", "manual_review_count", "errors",
                  "warnings", "metadata"):
            assert f in out, f"missing {f}"
        assert out["tool_id"] == "knowledge.import_document"
        assert out["ok"] is True
        assert out["source_id"].startswith("ksrc_")

    def test_list_sources_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import (
            tool_handler_import, tool_handler_list,
        )
        tool_handler_import({"workspace_id": fresh_ws, "title": "T",
                              "content": "C", "source": "rfc"})
        out = tool_handler_list({"workspace_id": fresh_ws})
        for f in ("call_id", "tool_id", "ok", "summary", "artifacts",
                  "source_count", "manual_review_count", "errors",
                  "warnings", "metadata"):
            assert f in out
        assert out["tool_id"] == "knowledge.list_sources"
        assert out["ok"] is True
        # sources field is in data
        assert "sources" in out["data"] or any(
            k in out["data"] for k in ("sources", "items"))

    def test_read_source_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import (
            tool_handler_import, tool_handler_read,
        )
        imp = tool_handler_import({"workspace_id": fresh_ws, "title": "T",
                                    "content": "C", "source": "rfc"})
        sid = imp["source_id"]
        out = tool_handler_read({"workspace_id": fresh_ws, "source_id": sid})
        assert out["tool_id"] == "knowledge.read_source"
        assert out["ok"] is True

    def test_read_source_not_found_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import tool_handler_read
        out = tool_handler_read({"workspace_id": fresh_ws,
                                  "source_id": "ksrc_missing"})
        assert out["tool_id"] == "knowledge.read_source"
        assert out["ok"] is False
        assert "source_not_found" in out["errors"]

    def test_disable_source_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import (
            tool_handler_import, tool_handler_disable,
        )
        imp = tool_handler_import({"workspace_id": fresh_ws, "title": "T",
                                    "content": "OSPF", "source": "rfc"})
        sid = imp["source_id"]
        out = tool_handler_disable({"workspace_id": fresh_ws,
                                    "source_id": sid, "disabled": True})
        assert out["tool_id"] == "knowledge.disable_source"
        assert out["ok"] is True

    def test_delete_source_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import (
            tool_handler_import, tool_handler_delete,
        )
        imp = tool_handler_import({"workspace_id": fresh_ws, "title": "T",
                                    "content": "C", "source": "rfc"})
        sid = imp["source_id"]
        out = tool_handler_delete({"workspace_id": fresh_ws, "source_id": sid})
        assert out["tool_id"] == "knowledge.delete_source"
        assert out["ok"] is True

    def test_query_tool(self, fresh_ws):
        from agent.modules.knowledge.tools import (
            tool_handler_import, tool_handler_query,
        )
        tool_handler_import({"workspace_id": fresh_ws, "title": "OSPF",
                              "content": "OSPF content", "source": "rfc"})
        out = tool_handler_query({"workspace_id": fresh_ws, "query": "OSPF"})
        assert out["tool_id"] == "knowledge.query"
        assert out["ok"] is True
        assert out["source_count"] >= 1


# ── 15. CapabilityRegistry exposes new knowledge tools ──
class TestCapabilityRegistry:
    def test_visibility_includes_5_knowledge_tools(self, reg):
        # v1.0.1.1: knowledge.read_source is NOT LLM-visible
        # (callable_by_llm=False). The 5 LLM-visible v1.0 knowledge
        # tools are still there.
        expected = {
            "knowledge.query",
            "knowledge.import_document",
            "knowledge.list_sources",
            "knowledge.disable_source",
            "knowledge.delete_source",
        }
        visible = set(reg.visible_tool_ids())
        assert expected.issubset(visible), \
            f"missing: {expected - visible}"
        # read_source is intentionally NOT LLM-visible
        assert "knowledge.read_source" not in visible

    def test_knowledge_capability_tool_count_is_12(self, reg):
        # v1.0.1 added 6 more knowledge tools: import_file /
        # list_chunks / search_chunks / read_chunk / read_parent /
        # reindex_source. 6 (v1.0) + 6 (v1.0.1) = 12.
        # v1.0.1.1: read_source flipped to callable_by_llm=False,
        # so the LLM-visible subset is 11 (12 - 1). The capability
        # tool manifest is still 12.
        m = reg.get("knowledge")
        assert m is not None
        assert m.status == "enabled"
        assert len(m.tools) == 12
        # 11 are LLM-visible (read_source is not).
        llm_visible = [t for t in m.tools if t.callable_by_llm]
        assert len(llm_visible) == 11
        assert all(t.forbidden is False for t in m.tools)


# ── 16. planned topology/inspection/cmdb still not visible ──
class TestPlannedStillNotVisible:
    def test_topology_tools_not_visible(self, reg):
        for t in ("topology.extract", "topology.render", "topology.health_check"):
            assert t not in reg.visible_tool_ids()
    def test_inspection_tools_not_visible(self, reg):
        for t in ("inspection.analyze_outputs", "inspection.generate_report"):
            assert t not in reg.visible_tool_ids()
    def test_cmdb_tools_not_visible(self, reg):
        for t in ("cmdb.extract_assets", "cmdb.query_assets", "cmdb.upsert_assets"):
            assert t not in reg.visible_tool_ids()


# ── Extra: knowledge capability safety contract ──
class TestKnowledgeSafety:
    def test_safety_contract(self, reg):
        m = reg.get("knowledge")
        assert m.safety.real_device_access is False
        assert m.safety.allows_config_push is False
        assert m.safety.produces_deployable_config is False
        assert m.safety.may_fabricate_sources is False

    def test_local_path_sanitized(self, fresh_ws):
        """Caller-supplied 'source' that looks like a local path is
        redacted; raw paths do not leak into list_sources / read_source."""
        from agent.modules.knowledge.store import import_document, list_sources
        out = import_document(
            workspace_id=fresh_ws, title="T", content="C",
            source="/Users/secret/secret.txt",
        )
        sid = out["source"]["source_id"]
        assert "secret" not in out["source"]["source"]
        # Confirm in list view too
        srcs = list_sources(workspace_id=fresh_ws)
        assert not any("secret" in s["source"] for s in srcs)


# ── Extra: Tool count check ──
class TestToolCountV10:
    def test_total_tool_count_is_73(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        tools = {t.tool_id for t in tr.registry.list_all()}
        # v1.0.1 adds 6 new knowledge tool_ids (import_file / list_chunks
        # / search_chunks / read_chunk / read_parent / reindex_source).
        # Later capabilities may add more tools, so assert the minimum
        # catalog size and the required knowledge tool set instead of an
        # exact total.
        assert len(tools) >= 73
        assert {
            "knowledge.import_file",
            "knowledge.list_chunks",
            "knowledge.search_chunks",
            "knowledge.read_chunk",
            "knowledge.read_parent",
            "knowledge.reindex_source",
        }.issubset(tools)


# ── Extra: query scoring is deterministic + 0.0 for non-matches ──
class TestQueryScoring:
    def test_score_is_zero_for_no_match(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, query
        import_document(workspace_id=fresh_ws, title="OSPF",
                        content="OSPF content", source="rfc")
        r = query(workspace_id=fresh_ws, query="zxcvbnm-qwerty")
        assert r["source_count"] == 0

    def test_score_higher_for_title_match(self, fresh_ws):
        from agent.modules.knowledge.store import import_document, query
        import_document(workspace_id=fresh_ws, title="OSPF 协议",
                        content="unrelated", source="rfc")
        r = query(workspace_id=fresh_ws, query="OSPF")
        assert r["source_count"] == 1
        assert r["hits"][0]["score"] > 0
