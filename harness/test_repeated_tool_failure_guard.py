def test_repeated_tool_failure_detects_same_failed_call_twice():
    from agent.runtime.tool_execution.retry_policy import detect_repeated_tool_failure

    results = [
        {
            "tool_id": "config.manage",
            "ok": False,
            "summary": "需要提供源配置文本。",
            "errors": ["missing_source_config"],
        },
        {
            "tool_id": "config.manage",
            "ok": False,
            "summary": "需要提供源配置文本。",
            "errors": ["missing_source_config"],
        },
    ]

    repeated = detect_repeated_tool_failure(results)

    assert repeated
    assert repeated["tool_id"] == "config.manage"


def test_repeated_tool_failure_ignores_different_errors():
    from agent.runtime.tool_execution.retry_policy import detect_repeated_tool_failure

    results = [
        {"tool_id": "config.manage", "ok": False, "errors": ["missing_source_config"]},
        {"tool_id": "config.manage", "ok": False, "errors": ["translation_error"]},
    ]

    assert detect_repeated_tool_failure(results) is None
