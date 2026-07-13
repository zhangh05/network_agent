"""Regression coverage for current workspace contract fixes."""

from __future__ import annotations


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

    compacted, info = _compact_messages(messages)

    assert info.compacted is True
    assert info.tool_stats["knowledge__manage"]["failed"] > 0
    assert "source lookup failed" in compacted[2].content


def test_knowledge_list_llm_schema_matches_registered_handler_options():
    from core.tools.canonical_registry import CANONICAL_REGISTRY

    entry = CANONICAL_REGISTRY["knowledge.manage"]
    properties = entry.input_schema["properties"]

    assert "query" in properties
    assert properties["include_disabled"]["type"] == "boolean"
    assert properties["include_deleted"]["type"] == "boolean"
