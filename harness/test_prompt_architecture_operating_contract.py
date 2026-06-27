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
            "visible_tools": ["workspace.file.read", "exec.run"],
        },
        "visible_tool_ids": ["workspace.file.read", "exec.run"],
        "workspace_id": "default",
        "session_id": "sess_123",
        "requested_by": "turn_runner",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_system_contract_includes_agent_operating_protocol():
    prompt = compile_runtime_prompt(_ctx()).final_prompt

    assert "Before calling any tool" in prompt
    assert "complex task" in prompt
    assert "pending -> in_progress -> completed" in prompt
    assert "Verify before finalizing" in prompt
    assert "Skill usage" in prompt


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
