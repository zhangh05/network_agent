"""Guards for legacy prompt/safe_context cleanup."""

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.prompting.safe_context_renderer import render_safe_context
from agent.runtime.prompting.compiler import PromptCompiler


OLD_CONCRETE_TOOLS = [
    "network.config.parse",
    "network.config.translate",
    "network.interface.extract",
    "network.route.extract",
    "network.pcap.parse",
    "network.pcap.session",
    "network.pcap.filter",
    "network.pcap.align",
]


def test_safe_context_drops_loaded_skills_section():
    text = render_safe_context({
        "workspace_id": "default",
        "loaded_skills_section": "SHOULD_NOT_APPEAR",
    })

    assert "SHOULD_NOT_APPEAR" not in text
    assert "loaded_skills_section" not in text
    assert "workspace_id" in text


def test_safe_context_filters_internal_tool_mentions_recursively():
    text = render_safe_context({
        "workspace_id": "default",
        "last_result_summary": "Use network.config.translate next",
        "artifact_refs": [
            {"title": "pcap", "hint": "call network.pcap.parse"},
        ],
    })

    assert "[internal-tool].translate" in text
    assert "[internal-tool].parse" in text
    for tool_id in OLD_CONCRETE_TOOLS:
        assert tool_id not in text


def test_safe_context_does_not_render_legacy_tool_planning_payloads():
    text = render_safe_context({
        "workspace_id": "default",
        "tool_scene": {
            "primary_category": "network",
            "candidate_tools": ["network.config.translate", "config.analysis.run"],
            "tool_plan": [{"tool_candidates": ["network.pcap.parse"]}],
            "tool_chain": [{"preferred_tools": ["network.pcap.align"]}],
            "tool_planner": {"warnings": ["network.config.parse"]},
            "governance": {"non_active_tools_filtered": ["network.pcap.session"]},
            "reason": "network analysis",
        },
    })

    assert "tool_scene_evidence" in text
    assert "primary_category" in text
    assert "reason" in text
    for forbidden_key in ("candidate_tools", "tool_plan", "tool_chain", "tool_planner", "governance"):
        assert forbidden_key not in text
    for tool_id in OLD_CONCRETE_TOOLS:
        assert tool_id not in text


def test_prompt_compiler_no_longer_depends_on_prompt_profile():
    source = inspect.getsource(PromptCompiler)
    assert "PromptProfile" not in source
    assert "compile_runtime_prompt" in source
