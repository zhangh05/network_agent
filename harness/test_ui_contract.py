"""
UI contract tests — frontend calls module API, planned modules shown correctly.
"""

import os
import json
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestUIContract:
    def test_frontend_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "frontend", "index.html"))

    def test_frontend_calls_module_api(self):
        """Frontend calls /api/modules/config-translation/translate, NOT /api/translate."""
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "/api/modules/config-translation/translate" in content
        # /api/translate without /modules/ prefix should NOT exist
        assert 'fetch("/api/translate"' not in content and "fetch('/api/translate'" not in content

    def test_frontend_has_config_translation_enabled(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "配置翻译" in content or "config translation" in content.lower()

    def test_frontend_shows_planned_modules(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "规划中" in content or "planned" in content.lower()

    def test_modules_registry_has_planned_status(self):
        fp = os.path.join(ROOT, "modules", "registry.json")
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        enabled = [m["module_name"] for m in data["modules"] if m["status"] == "enabled"]
        planned = [m["module_name"] for m in data["modules"] if m["status"] == "planned"]
        assert "config_translation" in enabled
        # Topology, inspection, knowledge_base must be planned, not enabled
        for m in ["topology", "inspection", "knowledge_base"]:
            assert m in planned, f"{m} should be planned, not enabled"

    def test_readme_documents_architecture(self):
        fp = os.path.join(ROOT, "README.md")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "8010" in content
        assert "module" in content.lower()
        assert "LLM" in content or "llm" in content.lower()
