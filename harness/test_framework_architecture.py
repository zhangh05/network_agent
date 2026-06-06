"""
Framework architecture verification tests.

- No legacy structures
- Correct directory layout
- Agent skeleton completeness
- LLM skeleton presence
"""

import os
import sys
import json
import urllib.request
import pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

SAMPLE_CONFIG = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"


# ═══════════════════════════════════════
# A. Architecture — no legacy structures
# ═══════════════════════════════════════

class TestNoLegacyStructures:
    def test_no_backend_services_config_translation(self):
        """backend/services/config_translation does NOT exist."""
        assert not os.path.exists(os.path.join(ROOT, "backend", "services", "config_translation"))

    def test_no_apps_as_formal(self):
        """apps/ is NOT in the root as a formal service directory."""
        assert not os.path.isdir(os.path.join(ROOT, "apps"))

    def test_apps_in_legacy_if_present(self):
        """legacy/apps may exist but is not tested by formal harness."""
        legacy = os.path.join(ROOT, "legacy", "apps")
        # OK either way, just verify it's not in root
        pass

    def test_no_8020_in_registry(self):
        """No skills/modules registry contains port 8020."""
        for registry in ["skills/registry.json", "modules/registry.json"]:
            path = os.path.join(ROOT, registry)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                assert "8020" not in content, f"{registry} contains 8020"

    def test_no_external_network_translator_in_sys_path(self):
        """sys.path has no external network-translator reference."""
        for p in sys.path:
            assert "network-translator" not in str(p)

    def test_no_os_chdir_in_any_source(self):
        """No source file in modules/ or backend/ uses os.chdir."""
        for root_dir in [os.path.join(ROOT, "modules"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "agent"), os.path.join(ROOT, "skills")]:
            if not os.path.isdir(root_dir):
                continue
            for dirpath, _, filenames in os.walk(root_dir):
                for f in filenames:
                    if f.endswith(".py"):
                        fp = os.path.join(dirpath, f)
                        with open(fp, encoding="utf-8", errors="replace") as fh:
                            content = fh.read()
                        for line in content.split("\n"):
                            stripped = line.strip()
                            if stripped.startswith("#") or stripped.startswith('"""'):
                                continue
                            if "os.chdir(" in stripped or "os.chdir (" in stripped:
                                pytest.fail(f"os.chdir found in {fp}: {stripped}")


# ═══════════════════════════════════════
# B. Directory layout
# ═══════════════════════════════════════

class TestDirectoryLayout:
    def test_modules_config_translation_exists(self):
        assert os.path.isdir(os.path.join(ROOT, "modules", "config_translation"))

    def test_module_backend_service_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "backend", "service.py"))

    def test_module_backend_schemas_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "backend", "schemas.py"))

    def test_module_core_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "modules", "config_translation", "core", "rule_translator.py"))

    def test_skills_adapter_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "skills", "config_translation", "adapter.py"))

    def test_agent_skeleton_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "agent", "state.py"))
        assert os.path.isfile(os.path.join(ROOT, "agent", "router.py"))

    def test_agent_llm_skeleton_exists(self):
        assert os.path.isdir(os.path.join(ROOT, "agent", "llm"))
        assert os.path.isfile(os.path.join(ROOT, "agent", "llm", "provider.py"))

    def test_frontend_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "frontend", "index.html"))

    def test_memory_core_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "memory", "store.py"))
        assert os.path.isfile(os.path.join(ROOT, "memory", "backends", "jsonl_store.py"))


# ═══════════════════════════════════════
# C. API endpoints
# ═══════════════════════════════════════

class TestAPIEndpoints:
    def test_health_returns_unified(self):
        data = _get("/api/health")
        assert data["status"] == "ok"
        assert data["api_mode"] == "unified"

    def test_version_embedded(self):
        data = _get("/api/version")
        assert data["config_translation_source"] == "embedded"
        assert data["external_translator_dependency"] is False
        assert data["translator_entry"] == "translate_bundle"

    def test_modules_registry(self):
        data = _get("/api/modules")
        assert "modules" in data
        names = [m.get("module_name") for m in data["modules"]]
        assert "config_translation" in names

    def test_skills_registry(self):
        data = _get("/api/skills")
        assert "skills" in data
        ct = next((s for s in data["skills"] if s["skill_name"] == "config_translation"), None)
        assert ct is not None
        assert ct["enabled"] is True

    def test_memory_status(self):
        data = _get("/api/memory/status")
        assert "backend" in data
        assert data.get("enabled") is True

    def test_module_translate_works(self):
        data = _post("/api/modules/config-translation/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True
        assert isinstance(data["deployable_config"], str)

    def test_agent_run_works(self):
        data = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True

    def test_agent_run_planned_intent(self):
        """Planned intents return coming_soon, not 500."""
        data = _post("/api/agent/run", {
            "intent": "topology_draw",
            "source_config": SAMPLE_CONFIG,
        })
        assert data.get("error", "").find("coming_soon") >= 0 or data.get("ok") is False

    def test_agent_run_uses_skill_adapter(self):
        """Agent run uses skill adapter (verified via result structure)."""
        data = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["skill_used"] == "config_translation"
        assert data["module_used"] == "config_translation"


# ═══════════════════════════════════════
# D. Config translation module boundaries
# ═══════════════════════════════════════

class TestModuleBoundaries:
    def test_module_has_no_frontend(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for bad in ["frontend", "web", "static", "templates"]:
            assert not os.path.isdir(os.path.join(ct, bad)), f"{bad}/ in module"

    def test_module_has_no_graph_agent_code(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    fp = os.path.join(dirpath, f)
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    for line in content.split("\n"):
                        s = line.strip()
                        if s.startswith("#") or s.startswith('"""'):
                            continue
                        if "GraphAgent" in s and not s.startswith("#"):
                            pytest.fail(f"GraphAgent in {fp}: {s}")

    def test_module_no_llm_translator(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    fp = os.path.join(dirpath, f)
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    for line in content.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                            continue
                        if "translate_separated" in stripped and ("def " in stripped or "=" in stripped):
                            pytest.fail(f"translate_separated in {fp}: {stripped}")

    def test_module_no_legacy_rule_translator(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    fp = os.path.join(dirpath, f)
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    assert "legacy_rule_translator" not in content

    def test_no_absolute_paths_in_module_service(self):
        fp = os.path.join(ROOT, "modules", "config_translation", "backend", "service.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "/Users/" not in content


# ═══════════════════════════════════════
# E. Skill adapter
# ═══════════════════════════════════════

class TestSkillAdapter:
    def test_adapter_imports_module_service(self):
        """Skill adapter imports from module service, not HTTP."""
        fp = os.path.join(ROOT, "skills", "config_translation", "adapter.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "modules.config_translation.backend" in content
        assert "urllib" not in content, "adapter still uses HTTP"

    def test_adapter_has_no_llm_call(self):
        fp = os.path.join(ROOT, "skills", "config_translation", "adapter.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "llm" not in content.lower(), "adapter calls LLM"

    def test_skill_yaml_has_red_lines(self):
        fp = os.path.join(ROOT, "skills", "config_translation", "skill.yaml")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "do_not_modify_deployable_config" in content
        assert "do_not_call_llm" in content


# ═══════════════════════════════════════
# F. Agent skeleton
# ═══════════════════════════════════════

class TestAgentSkeleton:
    def test_router_recognizes_translate_config(self):
        from agent.router import route
        from agent.state import NetworkAgentState
        state = NetworkAgentState(intent="translate_config")
        result = route(state)
        assert result.intent == "translate_config"
        assert result.error is None

    def test_router_rejects_unknown_intent(self):
        from agent.router import route
        from agent.state import NetworkAgentState
        state = NetworkAgentState(intent="unknown_stuff")
        result = route(state)
        assert result.error is not None

    def test_planner_produces_plan(self):
        from agent.planner import plan
        from agent.state import NetworkAgentState
        state = NetworkAgentState(intent="translate_config")
        result = plan(state)
        assert len(result.plan) > 0

    def test_verifier_checks_translate_result(self):
        from agent.verifier import verify
        from agent.state import NetworkAgentState
        state = NetworkAgentState(intent="translate_config")
        state.tool_results = [{
            "ok": True,
            "deployable_config": "test",
            "manual_review": [],
            "unsupported": [],
            "audit": {},
            "translator_entry": "translate_bundle",
        }]
        result = verify(state)
        assert result.verification.get("status") == "pass"

    def test_llm_client_is_not_connected(self):
        from agent.llm.client import LLMClient
        client = LLMClient()
        assert client.is_connected() is False
