from agent.runtime.prompts import build_system_prompt


def test_runtime_prompt_uses_operator_console_tone():
    """v3.0 prompt: concise console tone, no fabricating data."""
    prompt = build_system_prompt()

    assert "network operations console" in prompt
    assert "Never fabricate" in prompt
    assert "AI assistant" not in prompt
