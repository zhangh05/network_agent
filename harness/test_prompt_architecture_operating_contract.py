"""Operating-contract prompt tests for the runtime system prompt."""

from types import SimpleNamespace

from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt


def _ctx(**overrides):
    base = {
        "runtime_snapshot": {
            "status": "ok",
            "enabled_skills": ["assistant_chat", "config_translation"],
            "selected_skills": ["assistant_chat"],
        },
        "safe_context": {
            "workspace_id": "default",
            "session_id": "sess_123",
        },
        "metadata": {
            "selected_skills": ["assistant_chat"],
            "visible_tools": ["workspace.file", "exec.run"],
        },
        "visible_tool_ids": ["workspace.file", "exec.run"],
        "workspace_id": "default",
        "session_id": "sess_123",
        "requested_by": "turn_runner",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_system_contract_includes_agent_operating_protocol():
    """v3.9.6: prompt contract was rewritten. The legacy literal strings
    ``"complex task"`` and ``"Skill usage"`` no longer appear; the
    operating protocol is now phrased as an enumerated list. We pin
    the canonical contract snippets that survived the rewrite.
    """
    prompt = compile_runtime_prompt(_ctx()).final_prompt

    # Surviving invariants
    assert "Before calling any tool" in prompt
    assert "pending \u2192 in_progress \u2192 completed" in prompt
    assert "Verify before finalizing" in prompt

    # New operating-protocol markers (replacement assertions)
    assert "Operating protocol" in prompt
    assert "preamble" in prompt
    assert "environment context" in prompt


def test_prompt_injects_dynamic_environment_context():
    assembly = compile_runtime_prompt(_ctx())
    block_ids = {block.block_id for block in assembly.blocks}

    assert "environment_context" in block_ids
    assert "Working directory:" in assembly.final_prompt
    assert "Git branch:" in assembly.final_prompt
    assert "OS:" in assembly.final_prompt
    assert "Requested by: turn_runner" in assembly.final_prompt


def test_prompt_explains_skill_loading_without_inlining_skill_files():
    prompt = compile_runtime_prompt(_ctx()).final_prompt

    assert "Load or consult a skill" in prompt
    assert "assistant_chat" in prompt
    assert "config_translation" in prompt
    assert "SKILL.md" not in prompt


def test_prompt_contract_stays_compact():
    prompt = compile_runtime_prompt(_ctx()).final_prompt

    assert len(prompt) < 8000
