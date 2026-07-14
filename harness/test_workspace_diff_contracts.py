"""Regression coverage for current workspace contract fixes."""

from __future__ import annotations

import pytest


def test_tool_result_projection_preserves_summary_and_content():
    from agent.protocol.module_result import ModuleResult
    from agent.protocol.tool_result import ToolResult

    module_result = ModuleResult(ok=True, summary="导入完成", data={"count": 3})
    projected = ToolResult.from_module_result("knowledge.manage", "call_1", module_result)

    assert projected.summary == "导入完成"
    assert isinstance(projected.content, str)
    assert '"count": 3' in projected.content

    handler_result = {"ok": True, "summary": "执行完成", "stdout": "done"}
    call = ToolResult.from_handler_dict("exec.run", "call_2", handler_result)

    assert call.summary == "执行完成"
    assert call.data["stdout"] == "done"


def test_redaction_key_matching_avoids_operational_false_positives():
    from core.tools.redaction import contains_secret, redact_tool_output

    assert contains_secret({"community_name": "public"}) is False
    assert redact_tool_output({"community_name": "public"}) == {"community_name": "public"}

    assert contains_secret({"snmp_community": "public"}) is True
    assert redact_tool_output({"snmp_community": "public"}) == {"snmp_community": "[REDACTED]"}

    assert contains_secret({"noteworthy_token": "plain text"}) is False
    assert contains_secret({"auth_token": "secret-token"}) is True
    assert contains_secret({"nested": [{"password": "short"}]}) is True


def test_pcap_filter_returns_bounded_packet_preview(monkeypatch):
    from agent.modules.pcap import service

    packets = [{"idx": i} for i in range(service._PCAP_PACKET_PREVIEW_LIMIT + 5)]
    monkeypatch.setitem(service.PCAP_SESSIONS, "sess_preview", {"packets": packets})
    monkeypatch.setattr(service, "filter_by_5tuple", lambda packets, *args: list(packets))

    result = service.filter_pcap_session("sess_preview")

    assert result["ok"] is True
    assert result["count"] == service._PCAP_PACKET_PREVIEW_LIMIT + 5
    assert len(result["packets"]) == service._PCAP_PACKET_PREVIEW_LIMIT
    assert result["truncated"] is True
    assert result["returned_packets"] == service._PCAP_PACKET_PREVIEW_LIMIT


def test_query_loop_compaction_keeps_control_fields_before_bulk_output():
    import json

    from core.runtime_engine.query_loop import _json_compact

    compacted = _json_compact({
        "stdout": "x" * 100_000,
        "task_id": "task_contract_123",
        "status": "running",
        "report_url": "/reports/task_contract_123",
    }, max_chars=500)

    assert "task_contract_123" in compacted
    assert '"status":"running"' in compacted
    assert "/reports/task_contract_123" in compacted
    assert len(compacted) <= 500
    assert json.loads(compacted)["_truncated"] is True


def test_history_compaction_reads_actual_tool_result_messages():
    from agent.llm.schemas import LLMMessage
    from core.runtime_engine.query_loop import _compact_messages

    messages = [
        LLMMessage(role="system", content="system"),
        LLMMessage(role="user", content="original request"),
    ]
    for index in range(7):
        call_id = f"call_{index}"
        messages.extend([
            LLMMessage(role="assistant", content="", tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {"name": "knowledge__manage", "arguments": "{}"},
            }]),
            LLMMessage(
                role="tool",
                content='{"ok":false,"summary":"source lookup failed"}',
                tool_call_id=call_id,
            ),
        ])
    messages.extend([
        LLMMessage(role="user", content="continue"),
        LLMMessage(role="assistant", content="working"),
    ])

    compacted, info = _compact_messages(messages, max_tokens=180)

    assert info.compacted is True
    assert info.tool_stats["knowledge__manage"]["failed"] > 0
    assert "source lookup failed" in compacted[2].content


def test_context_budget_accounts_for_complete_tool_schema_surface():
    from core.runtime_engine.context_budget import RuntimeContextBudget

    small = RuntimeContextBudget.build(
        tools=[{"type": "function", "function": {"name": "one", "parameters": {}}}],
        context_window_tokens=20_000,
        max_input_tokens=18_000,
    )
    large = RuntimeContextBudget.build(
        tools=[{
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": "network operation " * 40,
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        } for index in range(20)],
        context_window_tokens=20_000,
        max_input_tokens=18_000,
    )

    assert large.tool_schema_tokens > small.tool_schema_tokens
    assert large.message_tokens < small.message_tokens


def test_context_budget_rejects_impossible_fixed_costs():
    from core.runtime_engine.context_budget import RuntimeContextBudget

    with pytest.raises(ValueError, match="runtime context budget is impossible"):
        RuntimeContextBudget.build(
            tools=[{
                "type": "function",
                "function": {"name": "huge", "description": "x" * 20_000},
            }],
            context_window_tokens=4_000,
            max_input_tokens=3_000,
            reserved_output_tokens=2_000,
        )


def test_tool_api_projection_keeps_nested_json_structured():
    from backend.api.runtime_routes import _safe_output

    output = {
        "ok": True,
        "records": [{"id": index, "body": "x" * 4_000} for index in range(20)],
        "nested": {"items": ["y" * 4_000 for _ in range(20)]},
    }
    safe = _safe_output(output)

    assert safe["ok"] is True
    assert isinstance(safe.get("records"), list)
    assert isinstance(safe.get("nested"), dict)
    assert safe["_api_projection"]["truncated"] is True


def test_oversized_short_conversation_is_compacted_to_hard_budget():
    from agent.llm.schemas import LLMMessage
    from core.runtime_engine.query_loop import _compact_messages, _estimate_message_tokens

    messages = [
        LLMMessage(role="system", content="system"),
        LLMMessage(role="user", content="request"),
        LLMMessage(role="assistant", content="x" * 8000),
    ]
    compacted, info = _compact_messages(messages, max_tokens=500)

    assert info.compacted is True
    assert _estimate_message_tokens(compacted) <= 500


def test_tiny_budget_never_leaves_compaction_over_limit():
    from agent.llm.schemas import LLMMessage
    from core.runtime_engine.query_loop import _compact_messages, _estimate_message_tokens

    messages = [
        LLMMessage(role="system", content="system rules " * 300),
        LLMMessage(role="user", content="inspect the network " * 300),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[{
                "id": "call_large",
                "type": "function",
                "function": {"name": "exec__run", "arguments": "x" * 8_000},
            }],
        ),
        LLMMessage(role="tool", tool_call_id="call_large", content="y" * 20_000),
    ]

    compacted, info = _compact_messages(messages, max_tokens=160)

    assert info.compacted is True
    assert _estimate_message_tokens(compacted) <= 160
    assert all(message.role != "tool" for message in compacted)


def test_compaction_preserves_tool_call_result_pairs_and_control_references():
    from agent.llm.schemas import LLMMessage
    from core.runtime_engine.query_loop import _compact_messages, _estimate_message_tokens

    messages = [
        LLMMessage(role="system", content="system"),
        LLMMessage(role="user", content="inspect devices"),
    ]
    for index in range(4):
        call_id = f"call_{index}"
        messages.extend([
            LLMMessage(role="assistant", content="", tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {"name": "inspection__manage", "arguments": "{}"},
            }]),
            LLMMessage(
                role="tool",
                content=(
                    '{"ok":true,"status":"running","task_id":"task_%d",'
                    '"report_url":"/reports/task_%d","summary":"%s"}'
                ) % (index, index, "evidence " * 500),
                tool_call_id=call_id,
            ),
        ])

    compacted, info = _compact_messages(messages, max_tokens=600)
    retained_call_ids = {
        str(call.get("id"))
        for message in compacted
        for call in (message.tool_calls or [])
        if isinstance(call, dict)
    }
    retained_result_ids = {
        str(message.tool_call_id)
        for message in compacted
        if message.role == "tool"
    }

    assert info.compacted is True
    assert retained_result_ids <= retained_call_ids
    assert _estimate_message_tokens(compacted) <= 600
    assert "task_id=task_0" in str(compacted[2].content)


def test_query_loop_marks_normal_length_finish_as_partial_output():
    from agent.llm.schemas import LLMResponse
    from core.runtime_engine.models import SSOTRuntimeConfig
    from core.runtime_engine.query_loop import QueryLoop

    loop = QueryLoop(SSOTRuntimeConfig(), {}, object())
    response = loop._coerce_llm_response(LLMResponse(
        content="partial answer",
        finish_reason="length",
    ))

    assert response.metadata["output_truncated"] is True
    assert response.metadata["truncation_reason"] == "length"
    assert "可能不完整" in response.content


def test_knowledge_list_llm_schema_matches_registered_handler_options():
    from core.tools.canonical_registry import CANONICAL_REGISTRY

    entry = CANONICAL_REGISTRY["knowledge.manage"]
    properties = entry.input_schema["properties"]

    assert "query" in properties
    assert properties["include_disabled"]["type"] == "boolean"
    assert properties["include_deleted"]["type"] == "boolean"
