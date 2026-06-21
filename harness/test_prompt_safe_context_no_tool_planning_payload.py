"""Guards for current prompt/safe_context cleanup."""

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.prompting.safe_context_renderer import render_safe_context
from agent.runtime.prompting.compiler import PromptCompiler


def test_safe_context_drops_loaded_skills_section():
    text = render_safe_context({
        "workspace_id": "default",
        "loaded_skills_section": "SHOULD_NOT_APPEAR",
    })

    assert "SHOULD_NOT_APPEAR" not in text
    assert "loaded_skills_section" not in text
    assert "workspace_id" in text


def test_safe_context_renders_evidence_values():
    text = render_safe_context({
        "workspace_id": "default",
        "last_result_summary": "Use config.analysis.run next",
        "artifact_refs": [
            {"title": "pcap", "hint": "call pcap.analysis.run"},
        ],
    })

    assert "config.analysis.run" in text
    assert "pcap.analysis.run" in text


def test_safe_context_does_not_render_tool_planning_payloads():
    text = render_safe_context({
        "workspace_id": "default",
        "tool_scene": {
            "primary_category": "network",
            "candidate_tools": ["config.analysis.run", "workspace.file.read"],
            "tool_plan": [{"tool_candidates": ["pcap.analysis.run"]}],
            "tool_chain": [{"preferred_tools": ["config.analysis.run"]}],
            "tool_planner": {"warnings": []},
            "governance": {"non_active_tools_filtered": []},
            "reason": "network analysis",
        },
    })

    assert "tool_scene_evidence" in text
    assert "primary_category" in text
    assert "reason" in text
    for forbidden_key in ("candidate_tools", "tool_plan", "tool_chain", "tool_planner", "governance"):
        assert forbidden_key not in text


def test_prompt_compiler_no_longer_depends_on_prompt_profile():
    source = inspect.getsource(PromptCompiler)
    assert "PromptProfile" not in source
    assert "compile_runtime_prompt" in source
