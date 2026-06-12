from agent.runtime.prompts import build_system_prompt


def test_runtime_prompt_uses_operator_console_tone():
    prompt = build_system_prompt()

    assert "network operations console" in prompt
    assert "Avoid emoji" in prompt
    assert "AI assistant" not in prompt
    assert "3-5 core points" in prompt
