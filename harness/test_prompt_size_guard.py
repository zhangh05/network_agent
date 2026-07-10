# harness/test_prompt_size_guard.py
"""Guard: default prompt must stay small."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt


class SmallCtx:
    runtime_snapshot = {"status": "ok"}
    safe_context = {"workspace_id": "default"}
    metadata = {"selected_skills": [], "visible_tools": ["workspace.file"]}
    visible_tool_ids = ["workspace.file"]


def test_default_prompt_is_not_huge():
    assembly = compile_runtime_prompt(SmallCtx())
    assert len(assembly.final_prompt) < 8000, f"prompt too large: {len(assembly.final_prompt)} chars"


def test_prompt_with_evidence_still_small():
    class CtxWithEvidence:
        runtime_snapshot = {"status": "ok", "task": "translate"}
        safe_context = {
            "workspace_id": "default",
            "session_id": "s1",
            "knowledge_hits": [{"title": "OSPF", "score": 0.8}],
            "memory_hits": [{"title": "user pref"}],
        }
        metadata = {"selected_skills": ["config_translation"], "visible_tools": ["config.manage"]}
        visible_tool_ids = ["config.manage", "workspace.file"]

    assembly = compile_runtime_prompt(CtxWithEvidence())
    # SYSTEM_CONTRACT grew with inspection playbook, artifact_id rules,
    # and memory/knowledge integration. 9000 chars still bounds bloat.
    assert len(assembly.final_prompt) < 9000, f"prompt too large: {len(assembly.final_prompt)} chars"
