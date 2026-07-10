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
    assert tracking["summary"]["raw_artifact_ids"] == ["art_raw_1"]


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
    assert second[0].id == "n0_i2_1"
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
        "n0": ToolResult(node_id="n0", tool="system.manage", success=True),
        "n0_i2_1": ToolResult(
            node_id="n0_i2_1",
            tool="workspace.artifact",
            success=False,
            error="not found",
        ),
    }
    metrics = MetricsCollector()
    metrics.capture_query_loop_execution(125.5, results, 2)
    snapshot = metrics.to_dict()

    assert snapshot["tool_calls"] == 2
    assert snapshot["tool_success"] == 1
    assert snapshot["tool_failed"] == 1
    assert snapshot["execution_duration_ms"] == 125.5
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


def test_memory_retrieval_only_returns_governed_active_records():
    from core.context.unified_retriever import UnifiedRetriever

    retriever = object.__new__(UnifiedRetriever)
    retriever.search = lambda *args, **kwargs: [
        {"item_id": "active", "status": "active"},
        {"item_id": "pending", "memory_status": "pending"},
        {"item_id": "rejected", "status": "rejected"},
        {"item_id": "confirmed", "memory_status": "confirmed"},
    ]

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
        "review_agent",
        "Review the current state",
    )
    result = subagent.run_subagent_task(created["subtask_id"], workspace_id)

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert _live_tasks[created["subtask_id"]]["status"] == "failed"
    assert _live_tasks[created["subtask_id"]].get("finished_at")
