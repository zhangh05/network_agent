# harness/test_skill_context_builder_cleanup.py
"""Verify context_builder no longer injects skill prompts or uses full tool catalog.
v3.4 update: 'loaded_capabilities' replaces 'loaded_skill_contracts'."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class DummyCtx:
    def __init__(self):
        self.metadata = {}
        self.safe_context = {}


class DummySession:
    def __init__(self):
        self.metadata = {
            "loaded_capabilities": {
                "config_translation": {
                    "skill_prompt": "SHOULD_NOT_APPEAR",
                    "capability_ids": ["config_translation"],
                    "module_ids": ["config_translation"],
                    "tool_ids": ["config.manage"],
                    "prompt_hints": ["hint"],
                    "safety_notes": ["safe"],
                }
            }
        }


def test_loaded_capabilities_do_not_inject_prompt_text():
    from agent.runtime.context_builder import _inject_loaded_skills

    ctx = DummyCtx()
    session = DummySession()
    _inject_loaded_skills(ctx, session)

    assert "loaded_skills_section" not in ctx.safe_context
    dumped = str(ctx.safe_context)
    assert "SHOULD_NOT_APPEAR" not in dumped
    assert "skill_prompt" not in dumped
    assert "loaded_capabilities" in ctx.safe_context
    assert ctx.safe_context["loaded_capabilities"][0]["capability_ids"] == ["config_translation"]


def test_context_builder_does_not_use_full_tool_namespace_catalog():
    # v3.9.3: capability_routing removed. context_builder.py now uses
    # {"tools": list(TOOL_NAMESPACE), "capability_routing": {}} inline.
    text = Path("agent/runtime/context_builder.py").read_text(encoding="utf-8")
    assert "active_tool_catalog" not in text
    assert "list(TOOL_NAMESPACE)" in text


def test_context_builder_uses_full_tool_namespace_catalog():
    # v3.9.3: replaces test_context_builder_uses_active_tool_catalog.
    # The catalog is now a literal dict containing all 21 tools.
    text = Path("agent/runtime/context_builder.py").read_text(encoding="utf-8")
    assert '"tools": list(TOOL_NAMESPACE)' in text
