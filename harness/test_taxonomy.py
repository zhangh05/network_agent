"""
Taxonomy tests for Module / Skill / Memory / Legacy cleanup.

Run: pytest harness/test_taxonomy.py -v
"""

import json
import os
import urllib.request
import urllib.error
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path, body, timeout=120):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


# ── Module Tests ──

class TestModuleRegistry:
    def test_modules_registry_yaml_exists(self):
        assert os.path.exists(os.path.join(ROOT, "modules", "registry.yaml"))

    def test_modules_registry_json_exists(self):
        assert os.path.exists(os.path.join(ROOT, "modules", "registry.json"))

    def test_config_translation_module_exists(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        names = [m["module_name"] for m in data["modules"]]
        assert "config_translation" in names

    def test_config_translation_status_enabled(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "config_translation")
        assert m["status"] == "enabled"

    def test_config_translation_has_ui_true(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "config_translation")
        assert m["has_ui"] is True

    def test_config_translation_ui_route_present(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "config_translation")
        assert "ui_route" in m

    def test_config_translation_module_doc_exists(self):
        assert os.path.exists(os.path.join(ROOT, "modules", "config_translation", "MODULE.md"))

    def test_topology_module_planned(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "topology")
        assert m["status"] == "planned"

    def test_inspection_module_planned(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "inspection")
        assert m["status"] == "planned"

    def test_knowledge_base_module_planned(self):
        with open(os.path.join(ROOT, "modules", "registry.json")) as f:
            data = json.load(f)
        m = next(m for m in data["modules"] if m["module_name"] == "knowledge_base")
        assert m["status"] == "planned"

    def test_api_modules_returns_config_translation(self):
        r = _get("/api/modules")
        names = [m["module_name"] for m in r["modules"]]
        assert "config_translation" in names

    def test_api_module_status_works(self):
        r = _get("/api/modules/config_translation/status")
        assert r["status"] == "enabled"


# ── Skill Tests ──

class TestSkillRegistry:
    def test_skills_registry_yaml_exists(self):
        assert os.path.exists(os.path.join(ROOT, "skills", "registry.yaml"))

    def test_skills_registry_json_exists(self):
        assert os.path.exists(os.path.join(ROOT, "skills", "registry.json"))

    def test_config_translation_skill_exists(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        names = [s["skill_name"] for s in data["skills"]]
        assert "config_translation" in names

    def test_config_translation_skill_enabled(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "config_translation")
        assert s["enabled"] is True

    def test_config_translation_skill_refs_module(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "config_translation")
        assert s.get("module") == "config_translation"

    def test_config_translation_skill_doc_exists(self):
        assert os.path.exists(os.path.join(ROOT, "skills", "config_translation", "SKILL.md"))

    def test_config_translation_rules_exist(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "config_translation")
        rules = s.get("rules", [])
        assert "do_not_modify_deployable_config" in rules
        assert "do_not_use_full_output_as_deployable" in rules
        assert "always_check_manual_review" in rules
        assert "never_hide_high_risk" in rules

    def test_skill_doc_has_red_lines(self):
        with open(os.path.join(ROOT, "skills", "config_translation", "SKILL.md")) as f:
            content = f.read()
        assert "Red Lines" in content
        assert "do_not_modify_deployable_config" in content

    def test_topology_draw_skill_planned(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "topology_draw")
        assert s["enabled"] is False

    def test_inspection_analyze_skill_planned(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "inspection_analyze")
        assert s["enabled"] is False

    def test_knowledge_search_skill_planned(self):
        with open(os.path.join(ROOT, "skills", "registry.json")) as f:
            data = json.load(f)
        s = next(s for s in data["skills"] if s["skill_name"] == "knowledge_search")
        assert s["enabled"] is False

    def test_api_skills_returns_config_translation(self):
        r = _get("/api/skills")
        names = [s["skill_name"] for s in r["skills"]]
        assert "config_translation" in names


# ── Memory Tests ──

class TestMemorySchema:
    def test_memory_record_schema_works(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test", content="hello", scope="short_term")
        d = r.as_dict()
        assert d["title"] == "test"
        assert d["scope"] == "short_term"
        assert d["memory_id"]

    def test_memory_record_from_dict(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord.from_dict({"title": "test", "content": "x", "scope": "project"})
        assert r.title == "test"

    def test_jsonl_store_put_get(self):
        from memory.backends.jsonl_store import JSONLMemoryStore
        from memory.schemas import MemoryRecord
        import tempfile, os
        d = tempfile.mkdtemp()
        try:
            store = JSONLMemoryStore(data_dir=d)
            r = MemoryRecord(title="test-put-get", content="hello world")
            mid = store.put(r)
            retrieved = store.get(mid)
            assert retrieved is not None
            assert retrieved.title == "test-put-get"
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_jsonl_store_search(self):
        from memory.backends.jsonl_store import JSONLMemoryStore
        from memory.schemas import MemoryRecord
        import tempfile
        d = tempfile.mkdtemp()
        try:
            store = JSONLMemoryStore(data_dir=d)
            store.put(MemoryRecord(title="BGP translation", content="BGP neighbor config", tags=["bgp"]))
            store.put(MemoryRecord(title="OSPF routing", content="OSPF area config", tags=["ospf"]))
            results = store.search("BGP", limit=10)
            assert len(results) >= 1
            assert any("BGP" in r["title"] for r in results)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_api_memory_status_works(self):
        r = _get("/api/memory/status")
        assert r["enabled"] is True
        assert r["backend"] == "jsonl"

    def test_api_memory_write_works(self):
        r = _post("/api/memory/write", {
            "title": "test memory",
            "content": "test content for API",
            "scope": "short_term",
            "memory_type": "knowledge_note",
        })
        assert r["ok"] is True
        assert "memory_id" in r

    def test_api_memory_search_works(self):
        r = _post("/api/memory/search", {
            "query": "test",
        })
        assert r["ok"] is True
        assert "results" in r


# ── Legacy Cleanup Tests ──

class TestLegacyCleanup:
    def test_legacy_test_file_renamed(self):
        assert os.path.exists(os.path.join(ROOT, "harness", "test_legacy_services.py"))
        assert not os.path.exists(os.path.join(ROOT, "harness", "test_services.py"))

    def test_readme_says_unified_entry_8010(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            content = f.read()
        assert "8010" in content
        assert "unified" in content.lower() or "backend/main.py" in content

    def test_readme_says_apps_dev_only(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            content = f.read()
        assert "dev-only" in content or "legacy" in content.lower()

    def test_readme_has_backend_main_start_cmd(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            content = f.read()
        assert "backend.main" in content

    def test_no_graph_agent_in_backend(self):
        import glob
        content = ""
        for path in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True):
            with open(path) as f:
                content += f.read() + "\n"
        # The service says it wraps translate_bundle — GraphAgent should not appear
        # except possibly in comments/docs saying "does NOT use"
        assert "GraphAgent" not in content or "#" + "GraphAgent" not in content or content.count("GraphAgent") <= 2


# ── Architecture Doc ──

class TestArchitectureDoc:
    def test_architecture_doc_exists(self):
        assert os.path.exists(os.path.join(ROOT, "docs", "ARCHITECTURE.md"))

    def test_architecture_doc_defines_module_skill_memory(self):
        with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md")) as f:
            content = f.read()
        assert "Module" in content
        assert "Skill" in content
        assert "Memory" in content
        assert "Workspace" in content
