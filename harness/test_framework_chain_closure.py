"""Focused contracts for the SSOT runtime and branch-chain closure."""

from __future__ import annotations

import asyncio
import uuid


def test_inspection_duration_deadline_and_raw_artifact_projection():
    from agent.modules.inspection.models import (
        CommandResult,
        DeviceResult,
        InspectionScope,
        InspectionTask,
    )
    from agent.modules.inspection.runner import _task_duration_ms
    from agent.modules.inspection.tracking import ensure_tracking

    task = InspectionTask(
        task_id="ins_contract",
        workspace_id="ws_contract",
        scope=InspectionScope(limit=1),
        profile_id="auto",
        status="succeeded",
        started_at="2026-07-10T00:00:00+00:00",
        finished_at="2026-07-10T00:00:02.500000+00:00",
        total_assets=1,
        succeeded=1,
        devices={
            "asset_1": DeviceResult(
                task_id="ins_contract",
                asset_id="asset_1",
                status="succeeded",
                command_results=[
                    CommandResult(
                        check_id="collect",
                        category="health",
                        command_key="display version",
                        ok=True,
                        artifact_id="art_raw_1",
                    ),
                ],
            ),
        },
    )

    assert _task_duration_ms(task) == 2500
    tracking = ensure_tracking(task)
    assert tracking["deadline_at"] == "2026-07-10T00:05:00+00:00"
    assert tracking["suggested_next_action"] == "analyze_artifacts"


def test_query_loop_namespaces_reused_provider_call_ids():
    from agent.llm.schemas import LLMToolCall
    from core.runtime_engine.query_loop import QueryLoop

    used: set[str] = set()
    first = QueryLoop._unique_call_ids(
        [LLMToolCall(id="n0", name="system__manage", arguments={"action": "health"})],
        1,
        used,
    )
    second = QueryLoop._unique_call_ids(
        [LLMToolCall(id="n0", name="system__manage", arguments={"action": "health"})],
        2,
        used,
    )

    assert first[0].id == "n0"
    assert second[0].id != "n0"  # 碰撞时必须改名
    assert second[0].id.startswith("n0_i2_")  # 格式: base_i{iter}_{suffix}
    assert len(used) == 2


def test_query_loop_tracks_generic_long_tasks_without_keyword_guessing():
    from core.runtime_engine.query_loop import QueryLoop

    tracking = {
        "kind": "long_task",
        "done": False,
        "suggested_next_action": "poll_get",
    }
    assert QueryLoop._should_poll_tracking("please process this", tracking) is True
    assert QueryLoop._should_poll_tracking("anything", {**tracking, "done": True}) is False


def test_merged_tool_concurrency_is_action_aware():
    from agent.llm.schemas import LLMToolCall
    from core.runtime_engine.models import SSOTRuntimeConfig
    from core.runtime_engine.query_loop import StreamingToolExecutor

    executor = StreamingToolExecutor(object(), SSOTRuntimeConfig())
    read = LLMToolCall(
        id="read",
        name="device__manage",
        arguments={"action": "list"},
    )
    write = LLMToolCall(
        id="write",
        name="device__manage",
        arguments={"action": "update"},
    )
    unknown = LLMToolCall(
        id="unknown",
        name="device__manage",
        arguments={},
    )

    assert executor._is_read_only_call(read) is True
    assert executor._is_read_only_call(write) is False
    assert executor._is_read_only_call(unknown) is False


def test_query_loop_metrics_count_every_unique_action():
    from core.runtime_engine.metrics import MetricsCollector
    from core.runtime_engine.models import ToolResult

    results = {
        "a": ToolResult(node_id="a", tool="x.y", success=True),
        "b": ToolResult(node_id="b", tool="x.z", success=False, error="nope"),
    }
    metrics = MetricsCollector()
    metrics.capture_query_loop_execution(88.0, results, 2)
    snapshot = metrics.to_dict()

    assert snapshot["tool_calls"] == 2
    assert snapshot["tool_success"] == 1
    assert snapshot["tool_failed"] == 1
    assert snapshot["execution_duration_ms"] == 88.0
    assert snapshot["max_parallel_width"] == 2


def test_query_loop_reprompts_once_after_empty_post_tool_response():
    from agent.llm.schemas import LLMResponse, LLMToolCall
    from core.runtime_engine.budget_controller import BudgetController
    from core.runtime_engine.models import SSOTRuntimeConfig, StatelessContext
    from core.runtime_engine.query_loop import QueryLoop

    responses = iter([
        LLMResponse(tool_calls=[
            LLMToolCall(
                id="n0",
                name="system__manage",
                arguments={"action": "health"},
            ),
        ]),
        LLMResponse(content=""),
        LLMResponse(content="系统运行正常。"),
    ])

    class RuntimeStub:
        def has_tool(self, name):
            return name == "system.manage"

        def invoke_raw(self, tool_id, arguments):
            return {"ok": True, "status": "healthy"}

    config = SSOTRuntimeConfig(
        enable_finalizer=True,
        max_query_loop_iterations=4,
        tracking_enabled=False,
    )
    loop = QueryLoop(
        config=config,
        tool_registry={
            "system.manage": {
                "description": "System health",
                "args_schema": {
                    "required": ["action"],
                    "properties": {"action": {"type": "string"}},
                },
            },
        },
        tool_runtime=RuntimeStub(),
    )

    async def fake_call(messages, ctx):
        return next(responses)

    loop._call_llm = fake_call
    result = asyncio.run(loop.run(
        StatelessContext("default", "session", "request", "检查系统"),
        BudgetController(config),
        metrics=None,
    ))

    assert result.final_response == "系统运行正常。"
    assert result.llm_calls == 3
    assert result.total_tool_calls == 1
    assert result.metrics["tool_calls"] == 1
    assert result.metrics["execution_duration_ms"] > 0


def test_complete_inspection_artifact_is_delivered_in_one_tool_message():
    import json

    from agent.llm.schemas import LLMMessage, LLMToolCall
    from core.runtime_engine.models import SSOTRuntimeConfig
    from core.runtime_engine.query_loop import QueryLoop, StreamingToolResult

    class RuntimeStub:
        def has_tool(self, name):
            return name == "workspace.artifact"

    loop = QueryLoop(
        config=SSOTRuntimeConfig(),
        tool_registry={"workspace.artifact": {"description": "Artifact read"}},
        tool_runtime=RuntimeStub(),
    )
    raw_content = "display version\n" + ("device output line\n" * 900)
    messages = loop._append_tool_round(
        [
            LLMMessage(role="system", content="system"),
            LLMMessage(role="user", content="analyze artifact art_1"),
        ],
        [
            LLMToolCall(
                id="read_artifact",
                name="workspace.artifact",
                arguments={"action": "read", "artifact_id": "art_1"},
            ),
        ],
        [
            StreamingToolResult(
                tool_name="workspace.artifact",
                call_id="read_artifact",
                ok=True,
                output={
                    "ok": True,
                    "artifact_id": "art_1",
                    "artifact_type": "inspection_raw",
                    "content_complete": True,
                    "content_chars": len(raw_content),
                    "preview": raw_content,
                },
            ),
        ],
    )

    tool_message = next(message for message in messages if message.role == "tool")
    payload = json.loads(str(tool_message.content))
    assert payload["preview"] == raw_content
    assert payload["content_complete"] is True
    assert payload["content_returned_chars"] == len(raw_content)
    # 契约: tool message 必须足够大以容纳完整内容 (不硬编码具体阈值)
    assert len(str(tool_message.content)) > len(raw_content) * 0.5

    final_messages = loop._append_turn_nudge(
        messages,
        "[FINAL_RESPONSE_ONLY] Analyze the complete artifact.",
    )
    projected = loop._messages_to_user_text(final_messages)
    assert len(projected) > len(raw_content)
    assert "[truncated" not in projected
    # 契约: 所有内容行都被保留 (不硬编码具体系数)
    assert "device output line" in projected
    assert "ASSISTANT TOOL_CALLS" not in projected


def test_complete_artifact_forces_second_call_to_finalize_without_tools():
    import json

    from core.runtime_engine.budget_controller import BudgetController
    from core.runtime_engine.models import SSOTRuntimeConfig, StatelessContext
    from core.runtime_engine.query_loop import QueryLoop

    calls = {"count": 0}

    def fake_llm(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            assert kwargs["tools"]
            return json.dumps({
                "nodes": [{
                    "id": "read_artifact",
                    "tool": "workspace.artifact",
                    "args": {"action": "read", "artifact_id": "art_1"},
                }],
            })
        assert kwargs["tools"] == []
        assert "[FINAL_RESPONSE_ONLY]" in kwargs["user"]
        return "已根据完整制品完成分析。"

    class RuntimeStub:
        def has_tool(self, name):
            return name == "workspace.artifact"

        def invoke_raw(self, tool_id, arguments):
            return {
                "ok": True,
                "artifact_id": "art_1",
                "artifact_type": "inspection_raw",
                "content_complete": True,
                "content_chars": 20,
                "preview": "complete inspection output",
            }

    config = SSOTRuntimeConfig(max_query_loop_iterations=4)
    loop = QueryLoop(
        config=config,
        tool_registry={
            "workspace.artifact": {
                "description": "Artifact read",
                "args_schema": {
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string"},
                        "artifact_id": {"type": "string"},
                    },
                },
            },
        },
        tool_runtime=RuntimeStub(),
        llm_invoke=fake_llm,
    )
    result = asyncio.run(loop.run(
        StatelessContext("default", "session", "request", "analyze art_1"),
        BudgetController(config),
        metrics=None,
    ))

    assert result.final_response == "已根据完整制品完成分析。"
    assert result.llm_calls == 2
    assert result.total_tool_calls == 1
    assert calls["count"] == 2


def test_ssot_tool_handler_keeps_canonical_payload_flat():
    from agent.runtime.ssot_runtime import _make_tool_handler
    from core.tools.schemas import ToolResult

    class ClientStub:
        def invoke(self, tool_id, args, context=None):
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                output={
                    "ok": True,
                    "artifact_type": "inspection_raw",
                    "content_complete": True,
                    "preview": "full artifact",
                },
                summary="artifact",
                redacted=True,
            )

    handler = _make_tool_handler(
        client=ClientStub(),
        tool_id="workspace.artifact",
        workspace_id="default",
        session_id="session",
        run_id="run",
        trace_id="trace",
        requested_by="turn_runner",
    )
    payload = asyncio.run(handler({"action": "read", "artifact_id": "art_1"}))

    assert "output" not in payload
    assert payload["content_complete"] is True
    assert payload["preview"] == "full artifact"
    assert payload["redacted"] is True


def test_prefetched_artifact_skips_planner_and_uses_one_llm_call():
    from core.runtime_engine.budget_controller import BudgetController
    from core.runtime_engine.models import SSOTRuntimeConfig, StatelessContext
    from core.runtime_engine.query_loop import QueryLoop

    calls = {"llm": 0, "tool": 0}

    def fake_llm(**kwargs):
        calls["llm"] += 1
        assert kwargs["tools"] == []
        assert "complete output" in kwargs["user"]
        return "prefetched artifact analysis"

    class RuntimeStub:
        def has_tool(self, name):
            return name == "workspace.artifact"

        def invoke_raw(self, tool_id, arguments):
            calls["tool"] += 1
            assert arguments["artifact_id"] == "art_prefetch"
            return {
                "ok": True,
                "artifact_id": "art_prefetch",
                "artifact_type": "inspection_raw",
                "content_complete": True,
                "preview": "complete output",
            }

    config = SSOTRuntimeConfig(max_query_loop_iterations=4)
    loop = QueryLoop(
        config=config,
        tool_registry={
            "workspace.artifact": {
                "description": "Artifact read",
                "args_schema": {
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string"},
                        "artifact_id": {"type": "string"},
                    },
                },
            },
        },
        tool_runtime=RuntimeStub(),
        llm_invoke=fake_llm,
    )
    ctx = StatelessContext("default", "session", "request", "analyze inspection")
    ctx.extras["prefetch_artifact_ids"] = ["art_prefetch"]
    result = asyncio.run(loop.run(ctx, BudgetController(config), metrics=None))

    assert result.final_response == "prefetched artifact analysis"
    assert result.llm_calls == 1
    assert result.total_tool_calls == 1
    assert calls == {"llm": 1, "tool": 1}


def test_memory_retrieval_only_returns_governed_active_records():
    from core.context.unified_retriever import UnifiedRetriever

    retriever = object.__new__(UnifiedRetriever)
    retriever.workspace_id = "default"

    all_items = [
        {"item_id": "active", "status": "active", "scope": "workspace", "workspace_id": "default"},
        {"item_id": "pending", "memory_status": "pending", "scope": "workspace", "workspace_id": "default"},
        {"item_id": "rejected", "status": "rejected", "scope": "workspace", "workspace_id": "default"},
        {"item_id": "confirmed", "memory_status": "confirmed", "scope": "workspace", "workspace_id": "default"},
    ]

    def _search(*args, **kwargs):
        result_filter = kwargs.get("result_filter")
        if result_filter is not None:
            return [item for item in all_items if result_filter(item)]
        return all_items

    retriever.search = _search
    retriever._memory_scope_visible = lambda hit, **kw: True

    hits = UnifiedRetriever.search_memory(retriever, "router", top_k=5)
    assert [hit["item_id"] for hit in hits] == ["active", "confirmed"]


def test_subagent_runtime_failure_reaches_terminal_projection(monkeypatch):
    from agent.runtime.durable import subagent
    from agent.runtime.durable.trajectory import _live_tasks

    def fail_turn(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("agent.runtime.ssot_runtime.run_ssot_turn", fail_turn)
    workspace_id = f"ws_chain_{uuid.uuid4().hex[:8]}"
    created = subagent.create_subagent_task(
        "parent_task",
        workspace_id,
        "session_1",
        "network_diag_agent",
        "Review the current state",
    )
    result = subagent.run_subagent_task(created["subtask_id"], workspace_id)

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert _live_tasks[created["subtask_id"]]["status"] == "failed"
    assert _live_tasks[created["subtask_id"]].get("finished_at")
