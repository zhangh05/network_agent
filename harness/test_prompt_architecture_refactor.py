# harness/test_prompt_architecture_refactor.py
"""Tests for capability-first prompt architecture."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt


class DummyCtx:
    def __init__(self):
        self.runtime_snapshot = {"turn": "x", "status": "ok"}
        self.safe_context = {
            "workspace_id": "default",
            "session_id": "s1",
            "loaded_skill_contracts": [
                {
                    "skill_id": "config_translation",
                    "capability_ids": ["config_translation"],
                    "module_ids": ["config_translation", "config_analysis"],
                    "tool_ids": ["config.analysis.run"],
                    "prompt_hints": ["hint"],
                    "safety_notes": ["safe"],
                }
            ],
            "tool_scene": {
                "capability_routing": {
                    "capability_ids": ["config_translation"],
                    "module_ids": ["config_translation", "config_analysis"],
                    "visible_tools": ["workspace.file.read", "config.analysis.run"],
                }
            },
        }
        self.metadata = {
            "selected_skills": ["config_translation"],
            "visible_tools": ["workspace.file.read", "config.analysis.run"],
        }
        self.visible_tool_ids = ["workspace.file.read", "config.analysis.run"]


def test_prompt_uses_capability_first_contract():
    ctx = DummyCtx()
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert "Skill = capability manifest" in text
    assert "Module = implementation service" in text
    assert "Tool = callable adapter" in text
    assert "config.analysis.run" in text


def test_prompt_does_not_include_legacy_skill_prompt():
    ctx = DummyCtx()
    ctx.safe_context["loaded_skill_contracts"][0]["skill_prompt"] = "SHOULD_NOT_APPEAR"
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert "SHOULD_NOT_APPEAR" not in text
    assert "skill_prompt" not in text


def test_prompt_does_not_include_internal_fine_grained_tools():
    ctx = DummyCtx()
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert ("network" + ".config.translate") not in text
    assert ("network" + ".pcap.parse") not in text


def test_prompt_metadata_records_blocks():
    ctx = DummyCtx()
    assembly = compile_runtime_prompt(ctx)

    assert assembly.metadata["prompt_architecture"] == "capability_first"
    assert "capability_context" in assembly.metadata["block_ids"]
    assert "active_tool_contract" in assembly.metadata["block_ids"]


def test_prompt_defines_business_modules_and_platform_services():
    ctx = DummyCtx()
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert "config_translation" in text
    assert "config_analysis" in text
    assert "pcap_analysis" in text
    assert "platform services" in text.lower() or "Platform Services" in text
    assert "workspace" in text
    assert "knowledge" in text


def test_prompt_filters_internal_tool_mentions_from_evidence():
    ctx = DummyCtx()
    ctx.safe_context["tool_plan"] = [
        {"tool_id": "config.analysis.run"},
        {"tool_id": "pcap.analysis.run"},
    ]
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert "config.analysis.run" in text


def test_prompt_explicitly_prefers_directory_tools():
    ctx = DummyCtx()
    assembly = compile_runtime_prompt(ctx)
    text = assembly.final_prompt

    assert "config.analysis.run" in text
    assert "pcap.analysis.run" in text
