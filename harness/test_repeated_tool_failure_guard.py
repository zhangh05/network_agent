def test_repeated_tool_failure_detects_same_failed_call_twice():
    from agent.runtime.tool_execution.pipeline import _repeated_tool_failure

    results = [
        {
            "tool_id": "network.config.translate",
            "ok": False,
            "summary": "需要提供源配置文本。",
            "errors": ["missing_source_config"],
        },
        {
            "tool_id": "network.config.translate",
            "ok": False,
            "summary": "需要提供源配置文本。",
            "errors": ["missing_source_config"],
        },
    ]

    repeated = _repeated_tool_failure(results)

    assert repeated
    assert repeated["tool_id"] == "network.config.translate"


def test_repeated_tool_failure_ignores_different_errors():
    from agent.runtime.tool_execution.pipeline import _repeated_tool_failure

    results = [
        {"tool_id": "network.config.translate", "ok": False, "errors": ["missing_source_config"]},
        {"tool_id": "network.config.translate", "ok": False, "errors": ["translation_error"]},
    ]

    assert _repeated_tool_failure(results) is None
