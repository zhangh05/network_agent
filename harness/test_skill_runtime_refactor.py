# harness/test_skill_runtime_refactor.py
"""Tests for the capability-first skill runtime."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.skill_runtime.registry import (
    list_skill_manifests,
    get_skill_manifest,
    search_skill_manifests,
)
from agent.runtime.skill_runtime.loader import load_skill
from agent.runtime.skill_runtime.session import skill_session_record


def test_builtin_skills_are_capability_packages():
    manifests = list_skill_manifests()
    assert manifests
    ids = {m.skill_id for m in manifests}
    assert "config_translation" in ids
    assert "pcap_analysis" in ids
    for manifest in manifests:
        assert manifest.capability_ids
        assert manifest.module_ids
        assert manifest.tool_ids
        assert manifest.source == "capability_package"


def test_skill_load_returns_capability_contract_not_prompt():
    result = load_skill("config_translation")
    assert result.ok
    assert "config_translation" in result.capability_ids
    assert "config.analysis.run" in result.tool_ids
    assert not hasattr(result, "skill_prompt")


def test_skill_search_finds_business_capability():
    results = search_skill_manifests("pcap")
    ids = {r.skill_id for r in results}
    assert "pcap_analysis" in ids


def test_unknown_skill_fails_closed():
    result = load_skill("does_not_exist")
    assert not result.ok
    assert result.status == "not_found"


def test_skill_session_record_has_capability_contract():
    result = load_skill("pcap_analysis")
    assert result.ok
    record = skill_session_record(result)
    assert record["skill_id"] == "pcap_analysis"
    assert "pcap_analysis" in record["capability_ids"]
    assert "pcap.analysis.run" in record["tool_ids"]
    assert "skill_prompt" not in record


def test_get_skill_manifest_returns_manifest():
    m = get_skill_manifest("workspace_read")
    assert m is not None
    assert m.skill_id == "workspace_read"
    assert m.source == "capability_package"


def test_get_skill_manifest_unknown_returns_none():
    m = get_skill_manifest("nonexistent")
    assert m is None
