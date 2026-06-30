# harness/test_directory_level_tools.py
"""Tests for directory-level tool handlers (config.manage, pcap.manage)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool_runtime.schemas import ToolInvocation


def _inv(tool_id, args=None):
    return ToolInvocation(tool_id=tool_id, arguments=args or {}, workspace_id="default")


def test_config_analysis_missing_action():
    from tool_runtime.canonical_registry import get_entry
    # v3.9.2: config.manage is the merged tool.
    entry = get_entry("config.manage")
    result = entry.handler(_inv("config.manage", {}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower() or "unsupported" in str(result.get("errors", []))


def test_config_analysis_unsupported_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("config.manage")
    result = entry.handler(_inv("config.manage", {"action": "explode"}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower()


def test_pcap_analysis_missing_action():
    from tool_runtime.canonical_registry import get_entry
    # v3.9.2: pcap.manage is the merged tool.
    entry = get_entry("pcap.manage")
    result = entry.handler(_inv("pcap.manage", {}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower() or "unsupported" in str(result.get("errors", []))


def test_pcap_analysis_unsupported_action():
    from tool_runtime.canonical_registry import get_entry
    entry = get_entry("pcap.manage")
    result = entry.handler(_inv("pcap.manage", {"action": "explode"}))
    assert not result["ok"]
    assert "unsupported" in result.get("summary", "").lower()


def test_pcap_session_returns_protocol_counts(tmp_path):
    from agent.modules.pcap.core import PCAP_SESSIONS
    from tool_runtime.canonical_registry import get_entry

    capture = tmp_path / "sample.pcap"
    capture.write_bytes(b"placeholder")
    PCAP_SESSIONS["sid_proto"] = {
        "filepath": str(capture),
        "packets": [{"proto_name": "TCP"}, {"proto_name": "UDP"}],
        "groups": [
            {"proto_name": "TCP", "src": "10.0.0.1", "dst": "10.0.0.2"},
            {"proto_name": "UDP", "src": "10.0.0.3", "dst": "10.0.0.4"},
            {"proto_name": "TCP", "src": "10.0.0.5", "dst": "10.0.0.6"},
        ],
    }
    try:
        entry = get_entry("pcap.manage")
        result = entry.handler(_inv("pcap.manage", {"action": "session", "session_id": "sid_proto"}))
        assert result["ok"] is True
        assert result["protocol_counts"] == {"TCP": 2, "UDP": 1}
    finally:
        PCAP_SESSIONS.pop("sid_proto", None)


def test_config_analysis_translate_without_config():
    """translate action should delegate to config_translation service."""
    from tool_runtime.canonical_registry import get_entry
    # v3.9.2: config.manage is the merged tool.
    entry = get_entry("config.manage")
    result = entry.handler(_inv("config.manage", {
        "action": "translate",
        "source_config": "",
        "target_vendor": "cisco",
    }))
    # May fail because no actual config provided, but should not crash
    assert isinstance(result, dict)
    assert "ok" in result
