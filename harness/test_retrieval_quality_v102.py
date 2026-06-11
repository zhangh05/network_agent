# harness/test_retrieval_quality_v102.py
"""Tests for v1.0.2 Retrieval Quality & Evaluation.

Coverage (16 tests):
  1-2.  CJK n-gram tokenization (2-gram, 3-gram) + English word tokens
  3.    Mixed CJK + English query tokenization
  4-5.  Field-weighted BM25 (title/chapter > body); defaults preserved
  6-7.  BM25 k1 / b are configurable via env vars
  8-9.  Query expansion (deterministic, no LLM) — OSPF / BGP / 邻居
  10.   tokenizer_version / scoring_version are exposed in metadata
  11.   query_expansions is surfaced in metadata (no hidden expansion)
  12.   Sibling dedup drops near-duplicates within a single source
  13.   dedup preserves cross-source / cross-chapter independence
  14.   no-hit precision: random CJK queries return [] (no fabrication)
  15.   Tool count remains 73 (no capability-layer tools added or removed)
  16.   planned tools (topology / inspection / cmdb) still NOT visible

  + Gating test: runs scripts/evaluate_retrieval_v102.py and asserts
    Recall@3 / MRR / no_hit_precision / duplicate_rate all pass.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.capabilities import get_default_capability_registry
from agent.capabilities.builtin import reset_default_capability_registry_cache


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = (PROJECT_ROOT / "harness" / "fixtures"
                / "retrieval_eval_v102.json")
EVAL_SCRIPT = PROJECT_ROOT / "scripts" / "evaluate_retrieval_v102.py"


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
    return f"test_ws_v102_{id(object())}"


# ── Helpers ──

def _md_with_h3(title: str = "OSPF 完全手册") -> str:
    return (
        f"# 第一章 OSPF 简介\n"
        f"\n"
        f"OSPF（开放式最短路径优先）是一种基于链路状态的内部网关协议。\n"
        f"\n"
        f"## 1.1 OSPF 邻居\n"
        f"\n"
        f"OSPF 邻居通过 Hello 包建立。\n"
        f"\n"
        f"### 1.1.1 邻居状态机\n"
        f"\n"
        f"OSPF 邻居状态机包含 Down / Init / 2-Way / Exstart / Exchange / "
        f"Loading / Full 等状态。\n"
    )


def _ingest_md(workspace_id: str, body: str, title: str = "OSPF 完全手册",
                source_type: str = "book", scope: str = "workspace"):
    from agent.modules.knowledge.ingestion import import_file
    return import_file(
        workspace_id=workspace_id, source=body.encode("utf-8"),
        title=title, source_type=source_type, scope=scope,
        language="zh", tags=["routing", "ospf"],
    )


# ── 1-3. Tokenization ──

class TestTokenization:
    def test_cjk_2gram_present(self):
        from agent.modules.knowledge.index import _cjk_ngrams
        toks = _cjk_ngrams("开放式最短路径优先", (2, 3))
        # 2-grams
        for t in ("开放", "放式", "式最", "最短", "路径", "径优", "优先"):
            assert t in toks, f"missing 2-gram {t!r}"
        # 3-grams
        for t in ("开放式", "放式最", "式最短", "最短路", "短路径", "路径优", "径优先"):
            assert t in toks, f"missing 3-gram {t!r}"

    def test_english_word_tokens(self):
        from agent.modules.knowledge.index import _tokenize_words
        toks = _tokenize_words("OSPF and BGP routing protocol")
        assert "ospf" in toks
        assert "and" in toks
        assert "bgp" in toks
        assert "routing" in toks
        assert "protocol" in toks
        # 1-char CJK skipped
        assert "的" not in _tokenize_words("OSPF 协议")
        assert "协" not in _tokenize_words("OSPF 协议")

    def test_mixed_query_emits_both(self):
        from agent.modules.knowledge.index import _tokenize_mixed
        toks = _tokenize_mixed("OSPF 邻居 邻接")
        # English word
        assert "ospf" in toks
        # CJK 2-grams
        assert "邻居" in toks
        assert "邻接" in toks


# ── 4-5. Field weights ──

class TestFieldWeights:
    def test_default_field_weights_in_code(self):
        from agent.modules.knowledge.index import DEFAULT_FIELD_WEIGHTS
        # title > chapter > section >= tags > body
        assert DEFAULT_FIELD_WEIGHTS["title"] > DEFAULT_FIELD_WEIGHTS["body"]
        assert DEFAULT_FIELD_WEIGHTS["chapter"] > DEFAULT_FIELD_WEIGHTS["body"]
        assert DEFAULT_FIELD_WEIGHTS["section"] >= DEFAULT_FIELD_WEIGHTS["body"]

    def test_title_match_ranks_higher_than_body_only(self, fresh_ws):
        """A chunk with 'OSPF' in the title should outrank a chunk with
        'OSPF' only in the body, for the query 'OSPF'."""
        from agent.modules.knowledge.ingestion import import_file
        from agent.modules.knowledge.index import search_chunks

        # Both bodies need to be long enough to produce a real BM25
        # score above the min_score threshold (0.5) so the test
        # actually exercises the title-weight vs body-weight ordering.
        body_a = (
            "# OSPF 完全手册\n\n"
            "OSPF（开放式最短路径优先）是一种基于链路状态的内部网关协议，"
            "使用 Dijkstra 算法计算最短路径。OSPF 通过区域（area）划分减少"
            "链路状态通告（LSA）的泛洪范围。OSPF 支持层次化路由。"
        )
        body_b = (
            "# 通用网络手册\n\n"
            "OSPF 是一种链路状态协议，与 IS-IS 协议属于同一类协议家族。"
            "BGP 是路径向量协议，用于自治系统之间的路由选择。"
        )
        out1 = import_file(
            workspace_id=fresh_ws, source=body_a.encode("utf-8"),
            title="OSPF 完全手册", source_type="book", scope="workspace",
        )
        out2 = import_file(
            workspace_id=fresh_ws, source=body_b.encode("utf-8"),
            title="通用网络手册", source_type="book", scope="workspace",
        )
        sid1 = out1["source_id"]
        r = search_chunks(workspace_id=fresh_ws, query="OSPF", top_k=5)
        assert r["ok"] is True
        assert r["source_count"] >= 1, (
            f"expected at least 1 hit, got {r['source_count']}; "
            f"metadata={r['metadata']}")
        # The top hit must be the OSPF book (title match outranks body-only)
        top_src = r["hits"][0]["source_id"]
        assert top_src == sid1, (
            f"expected title-match source {sid1} as top hit, got {top_src}")


# ── 6-7. BM25 k1 / b configurability ──

class TestBM25Configurability:
    def test_bm25_k1_env_override(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_BM25_K1", "2.0")
        from agent.modules.knowledge.index import _get_bm25_k1, BM25Index
        from agent.modules.knowledge.schemas import KnowledgeChunk
        assert _get_bm25_k1() == 2.0
        idx = BM25Index()
        assert idx.k1 == 2.0

    def test_bm25_b_env_override(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_BM25_B", "0.5")
        from agent.modules.knowledge.index import _get_bm25_b, BM25Index
        assert _get_bm25_b() == 0.5
        idx = BM25Index()
        assert idx.b == 0.5


# ── 8-9. Query expansion ──

class TestQueryExpansion:
    def test_ospf_expansion_to_chinese_full_name(self):
        from agent.modules.knowledge.index import _expand_query
        q, exps = _expand_query("OSPF 协议")
        assert "ospf" in q.lower()
        # Should add Chinese full name
        assert any("开放式最短路径优先" in (e.get("added") or [])
                    for e in exps)

    def test_bgp_expansion_to_chinese_full_name(self):
        from agent.modules.knowledge.index import _expand_query
        q, exps = _expand_query("BGP")
        assert any("边界网关协议" in (e.get("added") or [])
                    for e in exps)

    def test_neighbor_expansion(self):
        from agent.modules.knowledge.index import _expand_query
        q, exps = _expand_query("邻居")
        # 邻居 expands to neighbor + 邻接
        assert any("neighbor" in (e.get("added") or [])
                    or "邻接" in (e.get("added") or [])
                    for e in exps)

    def test_no_expansion_for_unrelated_query(self):
        from agent.modules.knowledge.index import _expand_query
        q, exps = _expand_query("完全不相关xyz")
        assert exps == []


# ── 10-11. Metadata surfacing ──

class TestMetadataSurfacing:
    def test_tokenizer_and_scoring_version_in_metadata(self, fresh_ws):
        from agent.modules.knowledge.ingestion import import_file
        from agent.modules.knowledge.index import search_chunks
        import_file(
            workspace_id=fresh_ws,
            source=_md_with_h3().encode("utf-8"),
            title="OSPF 完全手册", source_type="book", scope="workspace",
        )
        r = search_chunks(workspace_id=fresh_ws, query="OSPF", top_k=3)
        meta = r["metadata"]
        assert meta["tokenizer_version"] == "v1_cjk_ngram"
        assert meta["scoring_version"] == "v1_bm25_field_weighted"
        assert meta["retrieval_backend"] == "local_bm25"

    def test_query_expansions_surfaced_in_metadata(self, fresh_ws):
        from agent.modules.knowledge.ingestion import import_file
        from agent.modules.knowledge.index import search_chunks
        import_file(
            workspace_id=fresh_ws,
            source=_md_with_h3().encode("utf-8"),
            title="OSPF 完全手册", source_type="book", scope="workspace",
        )
        r = search_chunks(workspace_id=fresh_ws, query="OSPF", top_k=3)
        meta = r["metadata"]
        # query_expansions is a list of {term, added}
        assert isinstance(meta.get("query_expansions"), list)
        # The OSPF term should be expanded
        terms = [e.get("term") for e in meta["query_expansions"]]
        assert any(t and t.lower() == "ospf" for t in terms)


# ── 12-13. Sibling dedup ──

class TestSiblingDedup:
    def test_dedup_drops_near_duplicates_same_source(self):
        from agent.modules.knowledge.index import _dedupe_sibling_chunks
        # 3 hits: hit 0 and hit 1 are exact duplicates; the 3rd is independent.
        hits = [
            {"source_id": "ksrc_a", "parent_chunk_id": "p1",
             "content": "OSPF 邻居通过 Hello 包建立邻接关系",
             "score": 5.0},
            {"source_id": "ksrc_a", "parent_chunk_id": "p1",
             "content": "OSPF 邻居通过 Hello 包建立邻接关系",  # exact dup
             "score": 4.9},
            {"source_id": "ksrc_a", "parent_chunk_id": "p1",
             "content": "OSPF 区域边界路由器 ABR 通告 LSA",
             "score": 4.5},
        ]
        deduped, dropped = _dedupe_sibling_chunks(hits)
        # 1 drop (the exact duplicate); 2 hits kept (the independent one)
        assert dropped == 1
        assert len(deduped) == 2
        # The first kept is the highest-scored (kept on first pass)
        assert "OSPF 邻居" in deduped[0]["content"]
        assert "ABR" in deduped[1]["content"]

    def test_dedup_preserves_cross_source_independence(self):
        from agent.modules.knowledge.index import _dedupe_sibling_chunks
        # Same text, different sources — must NOT be deduped.
        hits = [
            {"source_id": "ksrc_a", "parent_chunk_id": "p1",
             "content": "OSPF 邻居通过 Hello 包建立邻接关系",
             "score": 5.0},
            {"source_id": "ksrc_b", "parent_chunk_id": "p1",
             "content": "OSPF 邻居通过 Hello 包建立邻接关系",
             "score": 4.9},
        ]
        deduped, dropped = _dedupe_sibling_chunks(hits)
        assert dropped == 0
        assert len(deduped) == 2


# ── 14. No-hit precision ──

class TestNoHitPrecision:
    def test_random_cjk_query_returns_no_fabrication(self, fresh_ws):
        from agent.modules.knowledge.ingestion import import_file
        from agent.modules.knowledge.index import search_chunks
        import_file(
            workspace_id=fresh_ws,
            source=_md_with_h3().encode("utf-8"),
            title="OSPF 完全手册", source_type="book", scope="workspace",
        )
        r = search_chunks(workspace_id=fresh_ws,
                            query="xyzqqq 绝对不相关", top_k=3)
        assert r["ok"] is True
        assert r["source_count"] == 0
        assert r["hits"] == []
        assert r["source_summary"] == []


# ── 15. Tool count ──

class TestToolCountV102:
    def test_total_tool_count_is_73(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        total = len(tr.registry.list_all())
        # v1.0.2 is a retrieval-quality improvement; no new tool_ids.
        assert total == 73


# ── 16. Planned still not visible ──

class TestPlannedStillNotVisibleV102:
    def test_topology_inspection_cmdb_not_visible(self, reg):
        for t in ("topology.extract", "topology.render",
                   "topology.health_check",
                   "inspection.analyze_outputs", "inspection.generate_report",
                   "cmdb.extract_assets", "cmdb.query_assets",
                   "cmdb.upsert_assets"):
            assert t not in reg.visible_tool_ids()


# ── Gating test: run the eval script and assert thresholds pass ──

class TestEvalGate:
    def test_eval_script_passes_thresholds(self, fresh_ws, tmp_path, monkeypatch):
        """Run scripts/evaluate_retrieval_v102.py and assert:
        - exit code 0
        - recall_at_3 >= 0.85
        - mrr >= 0.75
        - no_hit_precision == 1.0
        - duplicate_rate <= 0.20
        """
        if not EVAL_SCRIPT.exists():
            pytest.skip(f"eval script missing: {EVAL_SCRIPT}")
        if not FIXTURE_PATH.exists():
            pytest.skip(f"fixture missing: {FIXTURE_PATH}")
        # Run the eval in a subprocess so its own temp dir setup
        # does not pollute the test workspace.
        env = dict(os.environ)
        env["WS_ROOT"] = str(tmp_path / "ws")
        env["NETWORK_AGENT_WORKSPACE_DIR"] = str(tmp_path / "ws")
        env["NETWORK_AGENT_MEMORY_DIR"] = str(tmp_path / "mem")
        env["NETWORK_AGENT_REPORTS_DIR"] = str(tmp_path / "reports")
        # Make sure the subprocess can find the project package.
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(PROJECT_ROOT) + (os.pathsep + existing_pp if existing_pp else "")
        )
        (tmp_path / "ws").mkdir(parents=True, exist_ok=True)
        (tmp_path / "mem").mkdir(parents=True, exist_ok=True)
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(EVAL_SCRIPT), "--quiet",
             "--fixture", str(FIXTURE_PATH)],
            capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT),
        )
        # Eval should exit 0 on full pass.
        assert proc.returncode == 0, (
            f"eval exited {proc.returncode}\n"
            f"stdout: {proc.stdout[:2000]}\n"
            f"stderr: {proc.stderr[:2000]}"
        )
        # Parse the summary (no per_query)
        summary = json.loads(proc.stdout)
        metrics = summary.get("metrics", {})
        passes = summary.get("passes", {})
        # Hard assert thresholds
        assert metrics.get("recall_at_3", 0) >= 0.85, \
            f"recall_at_3 = {metrics.get('recall_at_3')}"
        assert metrics.get("mrr", 0) >= 0.75, \
            f"mrr = {metrics.get('mrr')}"
        assert metrics.get("no_hit_precision", 0) >= 1.0, \
            f"no_hit_precision = {metrics.get('no_hit_precision')}"
        assert metrics.get("duplicate_rate", 1) <= 0.20, \
            f"duplicate_rate = {metrics.get('duplicate_rate')}"
        assert summary.get("all_pass") is True
        for k, v in passes.items():
            assert v is True, f"passes[{k}] = {v}"
