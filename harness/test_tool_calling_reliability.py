import json


def test_handler_dict_adapter_replaces_old_adapter_name():
    from agent.protocol.tool_result import ToolResult

    assert hasattr(ToolResult, "from_handler_dict")
    retired_name = "from_" + "".join(chr(c) for c in (108, 101, 103, 97, 99, 121)) + "_dict"
    assert not hasattr(ToolResult, retired_name)

    result = ToolResult.from_handler_dict(
        tool_id="host.shell.exec",
        call_id="call_1",
        d={"ok": True, "summary": "done", "stdout": "hello"},
    )

    assert result.ok is True
    assert result.raw["stdout"] == "hello"


def test_tool_message_payload_preserves_stdout_tail():
    from agent.protocol.tool_result import ToolResult
    from agent.runtime.tool_result_utils import build_tool_message_payload
    from agent.runtime.loop import _preserve_tool_payload_edges

    stdout = ("noise\n" * 1200) + "IMPORTANT_IP=198.19.0.1\n"
    result = ToolResult.from_handler_dict(
        tool_id="host.shell.exec",
        call_id="call_1",
        d={
            "ok": True,
            "summary": "shell complete",
            "exit_code": 0,
            "stdout": stdout,
        },
    )

    payload = build_tool_message_payload(result)
    serialized = json.dumps(payload, ensure_ascii=False)
    shown = _preserve_tool_payload_edges(serialized, 20000)

    assert "stdout" in payload
    assert "IMPORTANT_IP=198.19.0.1" in payload["stdout"]
    assert "IMPORTANT_IP=198.19.0.1" in shown


def test_ip_prompt_enables_tool_contract_and_approval_note():
    from agent.runtime.prompts import build_system_prompt

    prompt = build_system_prompt(intent="assistant_chat", user_input="查看本机IP地址")

    assert "required steps" in prompt
    assert "High-risk tools open an approval popup" in prompt
    assert "Never say tools are unavailable" in prompt


def test_tool_followup_detection_keeps_previous_scene():
    from agent.runtime.context_tools import is_tool_followup

    assert is_tool_followup("不对，你肯定搞错了，能显示的，你调用有问题")
    assert is_tool_followup("有shell")
    assert not is_tool_followup("搜索 Kubernetes 官方文档")


def test_provider_parses_function_call_shape():
    from agent.llm.provider import _parse_message_tool_calls

    calls = _parse_message_tool_calls({
        "content": "",
        "function_call": {
            "name": "host__shell__exec",
            "arguments": "{\"command\":\"ifconfig\"}",
        },
    })

    assert len(calls) == 1
    assert calls[0].name == "host__shell__exec"
    assert calls[0].arguments["command"] == "ifconfig"


def test_uploaded_file_without_reference_needs_clarification():
    from agent.runtime.tool_planner import _needs_file_clarification

    assert _needs_file_clarification(
        "帮我分析上传的华三配置，并整理成报告保存",
        {},
        {"signals": {}},
    )
    assert not _needs_file_clarification(
        "帮我分析上传的华三配置，并整理成报告保存",
        {"artifact_refs": [{"artifact_id": "a1"}]},
        {"signals": {}},
    )
