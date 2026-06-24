# harness/test_skill_runtime_refactor.py
"""v3.2: Tests for skill_tools using CapabilityPackage directly.

The old skill_runtime/ directory has been removed. All skill
tool handlers now read CAPABILITY_PACKAGES directly via
tool_runtime/general_tools/skill_tools.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool_runtime.schemas import ToolInvocation
from tool_runtime.general_tools.skill_tools import (
    handle_skill_list,
    handle_skill_load,
    handle_skill_find,
    handle_skill_inspect,
)


def _inv(tool_id: str = "skill.load", **args) -> ToolInvocation:
    return ToolInvocation(tool_id=tool_id, arguments=args, workspace_id="default")


def test_skill_list_returns_capability_packages():
    result = handle_skill_list(_inv("skill.list"))
    assert result.get("ok")
    assert result["count"] > 0
    ids = {r["skill_id"] for r in result["results"]}
    assert "config_translation" in ids
    assert "pcap_analysis" in ids
    assert "cmdb" in ids


def test_skill_load_returns_capability_contract():
    result = handle_skill_load(_inv(skill_name="config_translation"))
    assert result.get("ok")
    assert "config_translation" in result["capability_ids"]
    assert "config.analysis.run" in result["tool_ids"]


def test_skill_find_finds_by_keyword():
    result = handle_skill_find(_inv("skill.search", query="pcap"))
    assert result.get("ok")
    ids = {r["skill_id"] for r in result["results"]}
    assert "pcap_analysis" in ids


def test_unknown_skill_fails_closed():
    result = handle_skill_load(_inv(skill_name="does_not_exist"))
    assert not result.get("ok")


def test_skill_inspect_returns_details():
    result = handle_skill_inspect(_inv("skill.get", skill_name="workspace_read"))
    assert result.get("ok")
    assert result.get("skill_id") == "workspace_read"
    assert result.get("source") == "capability_package"


def test_skill_inspect_unknown_returns_error():
    result = handle_skill_inspect(_inv("skill.get", skill_name="nonexistent"))
    assert not result.get("ok")
