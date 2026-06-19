from agent.runtime.prompting.profile import PromptProfile


def test_runtime_prompt_uses_operator_console_tone():
    """v3.0 prompt: concise console tone, no fabricating data."""
    prompt = PromptProfile.from_classify_intent().build()

    assert "network operations console" in prompt
    assert "Never fabricate" in prompt
    assert "AI assistant" not in prompt
