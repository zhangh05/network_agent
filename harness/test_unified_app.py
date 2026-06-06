"""
Harness tests for unified Network Agent backend.

Run:
    TRANSLATOR_SERVICE_PORT=8010 pytest harness/test_unified_app.py -v
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


# ── Health ──

class TestHealth:
    def test_health_returns_api_mode(self):
        r = _get("/api/health")
        assert r["status"] == "ok"
        assert r["api_mode"] == "unified"

    def test_health_has_skills_loaded(self):
        r = _get("/api/health")
        assert "skills_loaded" in r
        assert r["skills_loaded"] >= 1


# ── Version ──

class TestVersion:
    def test_version_returns_app_name(self):
        r = _get("/api/version")
        assert r["app"] == "network_agent"

    def test_version_returns_translator_entry(self):
        r = _get("/api/version")
        assert r["translator_entry"] == "translate_bundle"

    def test_version_returns_product_ready_false(self):
        r = _get("/api/version")
        assert r["product_ready"] is False

    def test_version_returns_firewall_status(self):
        r = _get("/api/version")
        assert r["firewall_status"] == "PARTIAL"

    def test_version_has_build_commit(self):
        r = _get("/api/version")
        assert "build_commit" in r
        assert len(r["build_commit"]) > 0

    def test_version_has_api_mode(self):
        r = _get("/api/version")
        assert r["api_mode"] == "unified"


# ── Skills ──

class TestSkills:
    def test_skills_returns_config_translate(self):
        r = _get("/api/skills")
        skills = r.get("skills", [])
        names = [s["skill_name"] for s in skills]
        assert "config_translation" in names

    def test_skill_endpoint_points_to_8010(self):
        r = _get("/api/skills")
        skill = next(s for s in r["skills"] if s["skill_name"] == "config_translation")
        ep = skill.get("entrypoint", {})
        assert "api/translate" in str(ep.get("path", ""))

    def test_skill_has_module_ref(self):
        r = _get("/api/skills")
        skill = next(s for s in r["skills"] if s["skill_name"] == "config_translation")
        assert skill.get("module") == "config_translation"

    def test_skill_has_rules(self):
        r = _get("/api/skills")
        skill = next(s for s in r["skills"] if s["skill_name"] == "config_translation")
        rules = skill.get("rules", [])
        assert "do_not_modify_deployable_config" in rules


# ── Translate ──

class TestTranslate:
    def test_translate_returns_deployable_config(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert r["ok"] is True
        assert "deployable_config" in r
        assert isinstance(r["deployable_config"], str)

    def test_translate_returns_manual_review(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "manual_review" in r
        assert isinstance(r["manual_review"], list)

    def test_translate_returns_semantic_near(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "semantic_near" in r
        assert isinstance(r["semantic_near"], list)

    def test_translate_returns_unsupported(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "unsupported" in r
        assert isinstance(r["unsupported"], list)

    def test_translate_returns_audit(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "audit" in r
        assert "counts" in r["audit"]

    def test_manual_review_count_matches_list(self):
        r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert r["manual_review_count"] == len(r["manual_review"])


# ── Agent Run ──

class TestAgentRun:
    def test_agent_run_translate_config_uses_skill(self):
        r = _post("/api/agent/run", {
            "intent": "translate_config",
            "payload": {
                "source_config": SAMPLE_CONFIG,
                "source_vendor": "cisco",
                "target_vendor": "huawei",
            }
        })
        assert r["ok"] is True
        assert r["skill_used"] == "config_translation"

    def test_agent_result_equals_translate_result(self):
        agent_r = _post("/api/agent/run", {
            "intent": "translate_config",
            "payload": {
                "source_config": SAMPLE_CONFIG,
                "source_vendor": "cisco",
                "target_vendor": "huawei",
            }
        })
        translate_r = _post("/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        agent_deployable = agent_r["result"]["deployable_config"]
        translate_deployable = translate_r["deployable_config"]
        assert agent_deployable == translate_deployable

    def test_agent_does_not_call_graph_agent(self):
        """Agent run must not call GraphAgent; only translate_bundle via HTTP."""
        r = _post("/api/agent/run", {
            "intent": "translate_config",
            "payload": {
                "source_config": SAMPLE_CONFIG,
                "source_vendor": "cisco",
                "target_vendor": "huawei",
            }
        })
        # translate_bundle path does not produce full_output
        assert "full_output" not in r
        assert r.get("translator_entry") == "translate_bundle"


# ── Code Safety ──

class TestCodeSafety:
    """Verify no legacy/LLM paths are referenced in backend code."""

    BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
    SERVICE_DIR = os.path.join(BACKEND_DIR, "services", "config_translation")

    def test_no_legacy_rule_translator_in_service(self):
        content = _read_all_py_files(self.SERVICE_DIR)
        assert "legacy_rule_translator" not in content, \
            "backend services must not reference legacy_rule_translator"

    def test_no_translate_separated_in_service(self):
        content = _read_all_py_files(self.SERVICE_DIR)
        assert "translate_separated" not in content, \
            "backend services must not reference translate_separated"

    def test_no_full_output_as_deployable_in_service(self):
        content = _read_all_py_files(self.SERVICE_DIR)
        # We only use bundle.deployable_config, never full_output
        assert "full_output" not in content, \
            "full_output is never used as deployable_config"


# ── Frontend ──

class TestFrontend:
    """Verify unified frontend exists with required elements."""

    FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")

    def test_frontend_exists(self):
        assert os.path.exists(self.FRONTEND_PATH), "frontend/index.html must exist"

    def test_frontend_contains_network_agent_title(self):
        with open(self.FRONTEND_PATH, encoding="utf-8") as f:
            html = f.read()
        assert "Network Agent" in html

    def test_frontend_has_translate_button(self):
        with open(self.FRONTEND_PATH, encoding="utf-8") as f:
            html = f.read()
        assert "配置翻译" in html, "frontend must have config translate module button"

    def test_frontend_has_build_commit_display(self):
        with open(self.FRONTEND_PATH, encoding="utf-8") as f:
            html = f.read()
        assert "build_commit" in html or "build-hash" in html or "build-id" in html, \
            "frontend must display build commit"

    def test_frontend_css_has_overflow_auto_or_minheight(self):
        with open(self.FRONTEND_PATH, encoding="utf-8") as f:
            html = f.read()
        has_overflow = "overflow:auto" in html.replace(" ", "") or "overflow: auto" in html
        has_minheight = "min-height:0" in html.replace(" ", "") or "min-height: 0" in html
        assert has_overflow or has_minheight, "frontend must prevent bottom text clipping"


# ── Helpers ──

def _read_all_py_files(directory: str) -> str:
    """Read all .py files in a directory into a single string for grep-style checks."""
    import glob
    content = ""
    for path in glob.glob(os.path.join(directory, "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            content += f.read() + "\n"
    return content
