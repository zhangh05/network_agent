# harness/test_directory_level_tools.py
"""Tests for directory-level tool handlers (config.analysis.run, pcap.analysis.run)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool_runtime.schemas import ToolInvocation


def _inv(tool_id, args=None):
    return ToolInvocation(tool_id=tool_id, arguments=args or {}, workspace_id="default")


def test_config_analysis_missing_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("config.analysis.run")
    result = entry.handler(_inv("config.analysis.run", {}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower() or "unsupported" in str(result.get("errors", []))


def test_config_analysis_unsupported_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("config.analysis.run")
    result = entry.handler(_inv("config.analysis.run", {"action": "explode"}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower()


def test_pcap_analysis_missing_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("pcap.analysis.run")
    result = entry.handler(_inv("pcap.analysis.run", {}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower() or "unsupported" in str(result.get("errors", []))


def test_pcap_analysis_unsupported_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("pcap.analysis.run")
    result = entry.handler(_inv("pcap.analysis.run", {"action": "explode"}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower()


def test_config_analysis_translate_without_config():
    """translate action should delegate to config_translation service."""
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("config.analysis.run")
    result = entry.handler(_inv("config.analysis.run", {
        "action": "translate",
        "source_config": "",
        "target_vendor": "cisco",
    }))
    # May fail because no actual config provided, but should not crash
    assert isinstance(result, dict)
    assert "ok" in result
