"""
Config Translation module placement tests.

Verifies:
- Correct directory structure (modules/config_translation/backend/)
- Old location is a compatibility shim
- Both /api/translate and /api/modules/config-translation/translate work
- Both APIs produce identical results
- No legacy LLM/GraphAgent in module
- No old network-translator UI in module
- No external repo/cwd/sys.path dependencies
"""

import inspect
import json
import os
import sys
import urllib.request
import urllib.error
import pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE_CONFIG = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ═════════════════════════════════════════════════════════════
# Directory structure tests
# ═════════════════════════════════════════════════════════════

class TestDirectoryStructure:
    def test_module_backend_exists(self):
        """modules/config_translation/backend/ exists."""
        assert os.path.isdir(os.path.join(ROOT, "modules", "config_translation", "backend"))

    def test_module_backend_service_exists(self):
        """modules/config_translation/backend/service.py exists."""
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "backend", "service.py"))

    def test_module_backend_schemas_exists(self):
        """modules/config_translation/backend/schemas.py exists."""
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "backend", "schemas.py"))

    def test_module_backend_client_exists(self):
        """modules/config_translation/backend/client.py exists."""
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "backend", "client.py"))

    def test_module_core_exists(self):
        """modules/config_translation/core/ exists and has core files."""
        core_dir = os.path.join(ROOT, "modules", "config_translation", "core")
        assert os.path.isdir(core_dir)
        assert os.path.isfile(os.path.join(core_dir, "rule_translator.py"))


# ═════════════════════════════════════════════════════════════
# Backend shim tests
# ═════════════════════════════════════════════════════════════

class TestBackendShim:
    def test_old_service_is_compatibility_shim(self):
        """backend/services/config_translation/service.py is a thin shim."""
        path = os.path.join(ROOT, "backend", "services", "config_translation", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "modules.config_translation.backend" in content
        assert "Compatibility shim" in content or "compatibility" in content

    def test_old_service_has_no_business_logic(self):
        """backend/services/config_translation/service.py has no business logic."""
        path = os.path.join(ROOT, "backend", "services", "config_translation", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # Shim should only have imports and __all__, no function bodies with logic
        assert "translate_bundle" not in content, "Old service contains translate_bundle logic"
        assert "RuleBasedTranslator" not in content, "Old service references RuleBasedTranslator directly"

    def test_module_service_has_business_logic(self):
        """modules/config_translation/backend/service.py has the implementation."""
        path = os.path.join(ROOT, "modules", "config_translation", "backend", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "translate_bundle" in content
        assert "RuleBasedTranslator" in content


# ═════════════════════════════════════════════════════════════
# API tests
# ═════════════════════════════════════════════════════════════

class TestModuleAPI:
    def test_module_translate_api_works(self):
        """POST /api/modules/config-translation/translate returns deployable_config."""
        data = _post("/api/modules/config-translation/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True
        assert "deployable_config" in data
        assert isinstance(data["deployable_config"], str)

    def test_legacy_translate_api_works(self):
        """POST /api/translate returns deployable_config."""
        data = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True
        assert "deployable_config" in data

    def test_both_apis_identical(self):
        """POST /api/translate and /api/modules/config-translation/translate are identical."""
        body = {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        }
        legacy = _post("/api/translate", body)
        module = _post("/api/modules/config-translation/translate", body)
        assert legacy["deployable_config"] == module["deployable_config"]

    def test_agent_run_works(self):
        """POST /api/agent/run works."""
        data = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True


# ═════════════════════════════════════════════════════════════
# Version
# ═════════════════════════════════════════════════════════════

class TestVersion:
    def test_config_translation_source_embedded(self):
        data = _get("/api/version")
        assert data["config_translation_source"] == "embedded"

    def test_external_translator_dependency_false(self):
        data = _get("/api/version")
        assert data["external_translator_dependency"] is False

    def test_translator_entry_translate_bundle(self):
        data = _get("/api/version")
        assert data["translator_entry"] == "translate_bundle"


# ═════════════════════════════════════════════════════════════
# UI cleanup tests — no old network-translator UI in module
# ═════════════════════════════════════════════════════════════

class TestUIBoundary:
    def test_module_has_no_frontend(self):
        """modules/config_translation does NOT contain frontend/ directory."""
        assert not os.path.isdir(os.path.join(ROOT, "modules", "config_translation", "frontend"))

    def test_module_has_no_web_ui(self):
        """modules/config_translation does NOT contain web/ or templates/ or static/."""
        ct = os.path.join(ROOT, "modules", "config_translation")
        assert not os.path.isdir(os.path.join(ct, "web"))
        assert not os.path.isdir(os.path.join(ct, "templates"))
        assert not os.path.isdir(os.path.join(ct, "static"))

    def test_network_agent_ui_retained(self):
        """network_agent/frontend/index.html still exists."""
        assert os.path.isfile(os.path.join(ROOT, "frontend", "index.html"))


# ═════════════════════════════════════════════════════════════
# LLM / GraphAgent cleanup — no legacy LLM in module
# ═════════════════════════════════════════════════════════════

class TestLLMBoundary:
    def _walk_module(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        files = []
        for dirpath, dirnames, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    files.append(os.path.join(dirpath, f))
        return files

    def test_module_has_no_graph_agent(self):
        """No code in module imports or uses GraphAgent (comments allowed)."""
        for fp in self._walk_module():
            with open(fp, encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Only check code lines, not docstrings/comments
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if "GraphAgent" in stripped and ("import" in stripped or "GraphAgent(" in stripped):
                    pytest.fail(f"GraphAgent usage in {fp}: {stripped}")

    def test_module_has_no_legacy_rule_translator(self):
        """No file in module imports legacy_rule_translator."""
        for fp in self._walk_module():
            with open(fp, encoding="utf-8", errors="replace") as f:
                content = f.read()
            assert "legacy_rule_translator" not in content, f"legacy_rule_translator in {fp}"

    def test_module_has_no_translate_separated(self):
        """No code in module calls translate_separated (docstrings/comments allowed)."""
        for fp in self._walk_module():
            with open(fp, encoding="utf-8", errors="replace") as f:
                content = f.read()
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if "translate_separated" in stripped and ("def " in stripped or "=" in stripped or "call" in stripped.lower()):
                    pytest.fail(f"translate_separated usage in {fp}: {stripped}")

    def test_module_has_no_prompt_based_translator(self):
        """No file in module contains prompt-based LLM translator references."""
        for fp in self._walk_module():
            with open(fp, encoding="utf-8", errors="replace") as f:
                content = f.read()
            assert "prompt" not in content.lower(), f"prompt reference in {fp}"

    def test_module_does_not_import_backend_agent_llm(self):
        """No file in module imports backend/agent/llm."""
        for fp in self._walk_module():
            with open(fp, encoding="utf-8", errors="replace") as f:
                content = f.read()
            assert "backend.agent.llm" not in content, f"backend.agent.llm in {fp}"
            assert "agent.llm" not in content, f"agent.llm in {fp}"


# ═════════════════════════════════════════════════════════════
# External dependency cleanup
# ═════════════════════════════════════════════════════════════

class TestExternalDependency:
    def test_no_network_translator_in_sys_path(self):
        """sys.path contains no network-translator reference."""
        for p in sys.path:
            assert "network-translator" not in str(p), f"External path: {p}"

    def test_no_os_chdir_in_module_service(self):
        """module service.py has no os.chdir."""
        path = os.path.join(ROOT, "modules", "config_translation", "backend", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "os.chdir" not in content

    def test_no_sys_path_insert_in_module_service(self):
        """module service.py has no sys.path.insert."""
        path = os.path.join(ROOT, "modules", "config_translation", "backend", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "sys.path" not in content

    def test_no_absolute_path_in_module_service(self):
        """module service.py has no /Users/ absolute path."""
        path = os.path.join(ROOT, "modules", "config_translation", "backend", "service.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "/Users/" not in content
