"""
Harness tests for network_agent.

Run: pytest harness/ -v
"""

import json
import os
import sys
import time
import pytest
import urllib.request

TRANSLATOR_PORT = int(os.environ.get("TRANSLATOR_SERVICE_PORT", "8010"))
AGENT_PORT = int(os.environ.get("AGENT_SERVICE_PORT", "8020"))
TRANSLATOR_URL = f"http://127.0.0.1:{TRANSLATOR_PORT}"
AGENT_URL = f"http://127.0.0.1:{AGENT_PORT}"

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


def _post(url, body, timeout=120):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Still return the JSON body even on HTTP errors
        return json.loads(e.read().decode("utf-8"))


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Translator Service Tests ──


class TestTranslatorVersion:
    def test_version_returns_build_commit(self):
        result = _get(f"{TRANSLATOR_URL}/api/version")
        assert result["ok"] is True
        assert "build_commit" in result
        assert result["translator_entry"] == "translate_bundle"

    def test_version_is_reachable(self):
        result = _get(f"{TRANSLATOR_URL}/api/version")
        assert result.get("service") == "translator_service"


class TestTranslatorTranslate:
    def test_translate_returns_deployable_config(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["ok"] is True
        assert "deployable_config" in result
        assert isinstance(result["deployable_config"], str)
        # Must not be from full_output
        assert "full_output" not in result

    def test_translate_returns_manual_review(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "manual_review" in result
        assert isinstance(result["manual_review"], list)

    def test_translate_returns_semantic_near(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "semantic_near" in result
        assert isinstance(result["semantic_near"], list)

    def test_translate_returns_unsupported(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "unsupported" in result
        assert isinstance(result["unsupported"], list)

    def test_translate_returns_audit(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "audit" in result
        assert "counts" in result["audit"]

    def test_translate_empty_config_returns_error(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": "",
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["ok"] is False

    def test_manual_review_count_matches_list(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["manual_review_count"] == len(result["manual_review"])

    def test_semantic_near_count_matches_list(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["semantic_near_count"] == len(result["semantic_near"])

    def test_unsupported_count_matches_list(self):
        result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["unsupported_count"] == len(result["unsupported"])


# ── Agent Service Tests ──


class TestAgentHealth:
    def test_health_ok(self):
        result = _get(f"{AGENT_URL}/health")
        assert result["ok"] is True
        assert result["service"] == "agent_service"


class TestAgentSkills:
    def test_skills_lists_config_translate(self):
        result = _get(f"{AGENT_URL}/skills")
        assert "skills" in result
        skill_names = [s["skill_name"] for s in result["skills"]]
        assert "config_translate" in skill_names

    def test_config_translate_has_endpoint(self):
        result = _get(f"{AGENT_URL}/skills")
        skill = next(s for s in result["skills"] if s["skill_name"] == "config_translate")
        assert "endpoint" in skill
        assert "input_schema" in skill
        assert "output_schema" in skill


class TestAgentRun:
    def test_run_translate_config_returns_deployable(self):
        result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["ok"] is True
        assert result["skill"] == "config_translate"
        assert "deployable_config" in result
        assert isinstance(result["deployable_config"], str)

    def test_run_translate_config_returns_manual_review(self):
        result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "manual_review" in result
        assert isinstance(result["manual_review"], list)

    def test_run_translate_config_deployable_matches_translator(self):
        agent_result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        translator_result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert agent_result["deployable_config"] == translator_result["deployable_config"]

    def test_run_translate_config_mr_count_matches(self):
        agent_result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        translator_result = _post(f"{TRANSLATOR_URL}/api/translate", {
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert agent_result["manual_review_count"] == translator_result["manual_review_count"]

    def test_run_unsupported_intent(self):
        result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "unknown_intent",
            "source_config": SAMPLE_CONFIG,
        })
        assert result["ok"] is False
        assert "unsupported intent" in result.get("error", "")

    def test_run_no_llm_path(self):
        """Agent must NOT call GraphAgent/LLM translation path."""
        result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        # translate_bundle does NOT produce full_output; agent must not add it
        assert "full_output" not in result
        # The translator_entry must be translate_bundle, not GraphAgent
        assert result.get("translator_entry") == "translate_bundle"

    def test_manual_review_field_complete(self):
        result = _post(f"{AGENT_URL}/agent/run", {
            "intent": "translate_config",
            "source_config": SAMPLE_CONFIG,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        for mr in result.get("manual_review", []):
            assert "source_excerpt" in mr
            assert "reason" in mr
            assert "category" in mr
            assert "risk_level" in mr
