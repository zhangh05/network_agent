# harness/test_knowledge_ingestion_security_v1011.py
"""Tests for v1.0.1.1 Knowledge Ingestion Security & Gate Fix.

Coverage (12 tests):
  1.  workspace/{ws}/uploads/<file> is allowed
  2.  workspace/{ws}/inbox/<file> is allowed
  3.  Absolute external path is rejected (path_not_allowed)
  4.  Path with '..' escape is rejected (path_not_allowed)
  5.  Symlink pointing outside the allowlist is rejected
      (path_not_allowed)
  6.  Oversize file is rejected (file_too_large)
  7.  Archive-bomb DOCX is rejected (archive_too_large)
  8.  knowledge.read_source is NOT model-visible
      (callable_by_llm=False)
  9.  knowledge.list_sources / search_chunks / read_chunk /
      read_parent are still model-visible
  10. tags schema is array[string] for import_file + search_chunks
  11. Tool count remains 73 (no capability-layer tools added or removed)
  12. planned tools (topology / inspection / cmdb) still not visible
"""

import io
import os
import zipfile

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
    """Fresh workspace_id; conftest redirects WS_ROOT to temp_dir."""
    return f"test_ws_v1011_{id(object())}"


# ── Helpers ──

def _setup_uploads(workspace_id: str, temp_dirs) -> Path:
    """Create uploads/ and inbox/ in the workspace; return uploads path."""
    base = Path(temp_dirs["workspace_dir"]) / workspace_id
    (base / "uploads").mkdir(parents=True, exist_ok=True)
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    return base / "uploads"


def _make_md(name: str, body: str = "# Test\n\nBody text.") -> bytes:
    return body.encode("utf-8")


def _make_docx_archive_bomb(out_path: Path) -> None:
    """Create a DOCX whose total uncompressed size exceeds the
    200 MB archive cap, but whose compressed (on-disk) size stays
    well under the 50 MB file-size cap.

    The bomb is a stream of zeros — DEFLATE compresses it down to
    ~1% of its uncompressed size. 300 entries x 1 MB uncompressed
    = 300 MB uncompressed, but the on-disk file is only a few MB.
    """
    if out_path.exists():
        out_path.unlink()
    big = b"\x00" * (1 * 1024 * 1024)  # 1 MB of zeros per entry
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(300):
            zf.writestr(f"entry_{i:04d}.bin", big)


# ── 1-2. uploads / inbox allowed ──

class TestUploadsInboxAllowed:
    def test_uploads_path_allowed(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.ingestion import import_file
        uploads = _setup_uploads(fresh_ws, temp_dirs)
        f = uploads / "book.md"
        f.write_bytes(_make_md("book", "# Book\n\nAllowed in uploads."))
        out = import_file(
            workspace_id=fresh_ws, source=str(f),
            title="Book", source_type="book", scope="workspace",
        )
        assert out["ok"] is True, out
        assert "source_id" in out

    def test_inbox_path_allowed(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.ingestion import import_file
        base = _setup_uploads(fresh_ws, temp_dirs)
        inbox = base.parent / "inbox"
        f = inbox / "inbox_doc.md"
        f.write_bytes(_make_md("inbox", "# Inbox Doc\n\nAllowed in inbox."))
        out = import_file(
            workspace_id=fresh_ws, source=str(f),
            title="Inbox Doc", source_type="project_doc", scope="workspace",
        )
        assert out["ok"] is True, out
        assert "source_id" in out


# ── 3. Absolute external path rejected ──

class TestAbsoluteExternalPathRejected:
    def test_absolute_outside_workspace_rejected(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.ingestion import import_file
        # File at /tmp (outside the workspace's allowlisted roots)
        ext = Path(temp_dirs["workspace_dir"]).parent / "external.md"
        ext.write_bytes(_make_md("ext", "# External\n\nShould be rejected."))
        try:
            out = import_file(
                workspace_id=fresh_ws, source=str(ext),
                title="External", source_type="project_doc",
            )
        finally:
            if ext.exists():
                ext.unlink()
        assert out["ok"] is False
        assert "path_not_allowed" in out["errors"]


# ── 4. Path traversal rejected ──

class TestPathTraversalRejected:
    def test_dotdot_traversal_rejected(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.ingestion import import_file
        _setup_uploads(fresh_ws, temp_dirs)
        # uploads/../external.md -> must be rejected even though
        # the prefix looks like an allowlisted dir.
        traversal = f"{temp_dirs['workspace_dir']}/{fresh_ws}/uploads/../external.md"
        out = import_file(
            workspace_id=fresh_ws, source=traversal,
            title="Traversal", source_type="project_doc",
        )
        assert out["ok"] is False
        assert "path_not_allowed" in out["errors"]


# ── 5. Symlink escape rejected ──

class TestSymlinkEscapeRejected:
    def test_symlink_to_outside_workspace_rejected(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.ingestion import import_file
        uploads = _setup_uploads(fresh_ws, temp_dirs)
        # Real file outside the workspace
        ext = Path(temp_dirs["workspace_dir"]).parent / "outside_target.md"
        ext.write_bytes(_make_md("outside", "# Outside\n\nA file outside."))
        try:
            # Symlink inside uploads/ pointing to /outside
            link = uploads / "evil_link.md"
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(ext)
            out = import_file(
                workspace_id=fresh_ws, source=str(link),
                title="Evil", source_type="project_doc",
            )
        finally:
            link_path = uploads / "evil_link.md"
            if link_path.is_symlink() or link_path.exists():
                link_path.unlink()
            if ext.exists():
                ext.unlink()
        assert out["ok"] is False
        assert "path_not_allowed" in out["errors"]


# ── 6. Oversize file rejected ──

class TestOversizeFileRejected:
    def test_oversize_md_rejected(self, fresh_ws, temp_dirs, monkeypatch):
        # Lower the cap to make the test fast.
        monkeypatch.setenv("KNOWLEDGE_MAX_FILE_BYTES", "1024")  # 1 KB
        # Reload module to pick up the env change.
        import importlib
        from agent.modules.knowledge import ingestion
        importlib.reload(ingestion)
        from agent.modules.knowledge.ingestion import import_file
        uploads = _setup_uploads(fresh_ws, temp_dirs)
        f = uploads / "huge.md"
        # 2 KB of content > 1 KB cap
        f.write_bytes(_make_md("huge", "# Huge\n\n" + "A" * 2000))
        out = import_file(
            workspace_id=fresh_ws, source=str(f),
            title="Huge", source_type="project_doc",
        )
        assert out["ok"] is False
        assert "file_too_large" in out["errors"]


# ── 7. Archive-bomb DOCX rejected ──

class TestArchiveBombRejected:
    def test_docx_archive_bomb_rejected(self, fresh_ws, temp_dirs, monkeypatch):
        # Raise the per-file cap so the archive-bomb check is the one
        # that fires. The compressed bomb file is small on disk
        # (DEFLATE zeros), but the uncompressed total is 300 MB.
        monkeypatch.setenv("KNOWLEDGE_MAX_FILE_BYTES", str(1024 * 1024 * 1024))  # 1 GB
        # Reload module to pick up the env change.
        import importlib
        from agent.modules.knowledge import ingestion
        importlib.reload(ingestion)
        from agent.modules.knowledge.ingestion import import_file
        uploads = _setup_uploads(fresh_ws, temp_dirs)
        f = uploads / "bomb.docx"
        _make_docx_archive_bomb(f)
        try:
            out = import_file(
                workspace_id=fresh_ws, source=str(f),
                title="Bomb", source_type="book",
            )
        finally:
            if f.exists():
                f.unlink()
        assert out["ok"] is False
        assert "archive_too_large" in out["errors"]


# ── 8. read_source not model-visible ──

class TestReadSourceNotModelVisible:
    def test_read_source_callable_by_llm_false(self, reg):
        m = reg.get("knowledge")
        rs = next(t for t in m.tools if t.tool_id == "knowledge.read_source")
        assert rs.callable_by_llm is False

    def test_read_source_not_in_visible_tool_ids(self, reg):
        visible = set(reg.visible_tool_ids())
        # The tool is enabled (backend callable) but NOT LLM-visible.
        # visible_tool_ids() should not include it.
        # (Some registry impls return LLM-visible only; this test
        # makes the contract explicit.)
        assert "knowledge.read_source" not in visible


# ── 9. read_chunk / read_parent / list_sources / search_chunks still model-visible ──

class TestChunkReadToolsStillModelVisible:
    def test_chunk_read_tools_model_visible(self, reg):
        visible = set(reg.visible_tool_ids())
        for tid in (
            "knowledge.list_sources",
            "knowledge.search_chunks",
            "knowledge.read_chunk",
            "knowledge.read_parent",
        ):
            assert tid in visible, f"{tid} should be LLM-visible"


# ── 10. tags schema is array[string] ──

class TestTagsSchema:
    def test_import_file_tags_schema(self, reg):
        m = reg.get("knowledge")
        tool = next(t for t in m.tools if t.tool_id == "knowledge.import_file")
        schema = tool.input_schema
        tags_schema = schema["properties"]["tags"]
        assert tags_schema["type"] == "array"
        assert tags_schema["items"] == {"type": "string"}

    def test_search_chunks_tags_schema(self, reg):
        m = reg.get("knowledge")
        tool = next(t for t in m.tools if t.tool_id == "knowledge.search_chunks")
        schema = tool.input_schema
        tags_schema = schema["properties"]["tags"]
        assert tags_schema["type"] == "array"
        assert tags_schema["items"] == {"type": "string"}


# ── 11. Tool count remains 73 ──

class TestToolCountV1011:
    def test_total_tool_count_is_73(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        total = len(tr.registry.list_all())
        # v1.0.1 was 73; v1.0.1.1 is a security fix only — no new
        # tools added. Tool count must stay 73.
        assert total == 73

    def test_capability_layer_tool_count_is_19(self, reg):
        m = reg.get("knowledge")
        assert len(m.tools) == 12  # 6 v1.0 + 6 v1.0.1
        # CapabilityRegistry.enabled_tools() returns tools that
        # are enabled AND callable_by_llm=True.
        enabled_llm = [t for t in m.tools
                        if t.callable_by_llm and not t.forbidden]
        # Was 12 in v1.0.1; v1.0.1.1 sets read_source
        # callable_by_llm=False, so 12 - 1 = 11.
        assert len(enabled_llm) == 11


# ── 12. planned tools still not visible ──

class TestPlannedStillNotVisibleV1011:
    def test_topology_inspection_cmdb_not_visible(self, reg):
        for t in ("topology.extract", "topology.render",
                   "topology.health_check",
                   "inspection.analyze_outputs", "inspection.generate_report",
                   "cmdb.extract_assets", "cmdb.query_assets",
                   "cmdb.upsert_assets"):
            assert t not in reg.visible_tool_ids()


# ── Extras ──

class TestReadSourceBackendStillWorks:
    """v1.0.1.1 only flips callable_by_llm. The backend service must
    still work for internal callers (e.g. reindex_source)."""

    def test_service_read_source_returns_full_content(self, fresh_ws, temp_dirs):
        from agent.modules.knowledge.service import read_source
        from agent.modules.knowledge.ingestion import import_file
        uploads = _setup_uploads(fresh_ws, temp_dirs)
        f = uploads / "book.md"
        f.write_bytes(_make_md("book", "# Backend Read\n\nFull content here."))
        out = import_file(
            workspace_id=fresh_ws, source=str(f),
            title="Backend Read", source_type="book",
        )
        sid = out["source_id"]
        # service.read_source is callable by backend code
        rec = read_source(workspace_id=fresh_ws, source_id=sid)
        assert rec["ok"] is True
        assert "Full content here" in rec["source"]["content"]
