from agent.runtime.prompting.blocks import CORE_PROMPT


def test_runtime_prompt_uses_operator_console_tone():
    """v3.0 prompt: concise console tone, no fabricating data."""
    prompt = CORE_PROMPT

    assert "network operations console" in prompt
    assert "Never fabricate" in prompt
    assert "AI assistant" not in prompt
