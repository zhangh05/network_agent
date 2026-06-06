"""
Formal entry point verification.

Verifies the unified Network Agent on port 8010:
- Health, version, skills registry
- /api/translate and /api/agent/run consistency
- No legacy 8020 references in registry
- External dependency cleanup
"""

import json
import os
import urllib.request
import urllib.error
import pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"

SAMPLE_CONFIG = """\
hostname Core-Router
interface GigabitEthernet0/1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 spanning-tree portfast
!
router bgp 65001
 neighbor 10.0.0.2 remote-as 65002
"""


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ═════════════════════════════════════════════════════════════
# Health
# ═════════════════════════════════════════════════════════════

class TestFormalHealth:
    def test_health_returns_unified(self):
        """GET /api/health returns api_mode=unified."""
        data = _get("/api/health")
        assert data["status"] == "ok"
        assert data["api_mode"] == "unified"

    def test_health_skills_loaded(self):
        """GET /api/health reports skills_loaded."""
        data = _get("/api/health")
        assert data["skills_loaded"] >= 1


# ═════════════════════════════════════════════════════════════
# Version
# ═════════════════════════════════════════════════════════════

class TestFormalVersion:
    def test_app_is_network_agent(self):
        """GET /api/version app=network_agent."""
        data = _get("/api/version")
        assert data["app"] == "network_agent"

    def test_config_translation_source_embedded(self):
        """GET /api/version config_translation_source=embedded."""
        data = _get("/api/version")
        assert data["config_translation_source"] == "embedded"

    def test_external_translator_dependency_false(self):
        """GET /api/version external_translator_dependency=false."""
        data = _get("/api/version")
        assert data["external_translator_dependency"] is False

    def test_translator_entry_translate_bundle(self):
        """GET /api/version translator_entry=translate_bundle."""
        data = _get("/api/version")
        assert data["translator_entry"] == "translate_bundle"

    def test_api_mode_unified(self):
        """GET /api/version api_mode=unified."""
        data = _get("/api/version")
        assert data["api_mode"] == "unified"


# ═════════════════════════════════════════════════════════════
# Translate
# ═════════════════════════════════════════════════════════════

class TestFormalTranslate:
    def test_translate_returns_deployable(self):
        """POST /api/translate returns deployable_config string."""
        data = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True
        assert isinstance(data["deployable_config"], str)
        assert len(data["deployable_config"]) > 0

    def test_translate_returns_manual_review(self):
        """POST /api/translate returns manual_review list."""
        data = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert "manual_review" in data
        assert isinstance(data["manual_review"], list)

    def test_translate_returns_audit(self):
        """POST /api/translate returns audit with counts."""
        data = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert "audit" in data
        assert "counts" in data["audit"]

    def test_translate_no_full_output(self):
        """POST /api/translate does not leak full_output as deployable."""
        data = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert "full_output" not in data


# ═════════════════════════════════════════════════════════════
# Agent Run
# ═════════════════════════════════════════════════════════════

class TestFormalAgentRun:
    def test_agent_run_returns_deployable(self):
        """POST /api/agent/run with translate_config returns deployable_config."""
        data = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        assert data["ok"] is True
        result = data.get("result", data)
        assert "deployable_config" in result
        assert isinstance(result["deployable_config"], str)

    def test_agent_run_matches_translate(self):
        """POST /api/agent/run deployable matches POST /api/translate."""
        agent = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        translate = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        agent_result = agent.get("result", agent)
        assert agent_result["deployable_config"] == translate["deployable_config"], \
            "agent/run and translate deployable outputs must match"

    def test_agent_run_returns_manual_review(self):
        """POST /api/agent/run returns manual_review list."""
        data = _post("/api/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
        result = data.get("result", data)
        assert "manual_review" in result
        assert isinstance(result["manual_review"], list)


# ═════════════════════════════════════════════════════════════
# Skills Registry
# ═════════════════════════════════════════════════════════════

class TestFormalSkills:
    def test_skills_registry_loaded(self):
        """GET /api/skills returns skills list."""
        data = _get("/api/skills")
        assert "skills" in data
        assert len(data["skills"]) >= 1

    def test_config_translation_skill_enabled(self):
        """config_translation skill is enabled."""
        data = _get("/api/skills")
        ct = next((s for s in data["skills"] if s["skill_name"] == "config_translation"), None)
        assert ct is not None, "config_translation skill not found"
        assert ct["enabled"] is True

    def test_config_translation_endpoint_is_8010(self):
        """config_translation entrypoint path is /api/translate (on 8010)."""
        data = _get("/api/skills")
        ct = next((s for s in data["skills"] if s["skill_name"] == "config_translation"), None)
        assert ct is not None
        ep = ct.get("entrypoint", {})
        assert ep.get("type") == "api"
        assert ep.get("path") == "/api/translate"

    def test_no_skill_points_to_8020(self):
        """No skill entrypoint references port 8020."""
        data = _get("/api/skills")
        for skill in data["skills"]:
            ep = skill.get("entrypoint", {})
            if ep.get("type") == "api":
                path = ep.get("path", "")
                # All paths must be relative (under 8010 host), not point to 8020
                assert "8020" not in path, f"Skill {skill['skill_name']} points to 8020"


# ═════════════════════════════════════════════════════════════
# Modules Registry
# ═════════════════════════════════════════════════════════════

class TestFormalModules:
    def test_modules_registry_loaded(self):
        """GET /api/modules returns modules list."""
        data = _get("/api/modules")
        assert "modules" in data

    def test_config_translation_module_exists(self):
        """config_translation module is in registry."""
        data = _get("/api/modules")
        names = [m.get("module_name") for m in data.get("modules", [])]
        assert "config_translation" in names
