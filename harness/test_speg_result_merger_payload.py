"""SPEG merger should expose nested tool payloads for final synthesis."""

from __future__ import annotations


def test_result_merger_unwraps_nested_output_payload():
    from speg_engine.models import ExecutionDAG, ExecutionNode, StatelessContext, ToolResult
    from speg_engine.result_merger import ResultMerger

    dag = ExecutionDAG(
        nodes=[ExecutionNode(id="weather", tool="web.manage", args={"action": "weather"})],
        total_nodes=1,
        max_depth=0,
    )
    result = ToolResult(
        node_id="weather",
        tool="web.manage",
        success=True,
        data={
            "ok": True,
            "summary": "one-line summary",
            "output": {
                "forecast_daily": [{"date": "2026-07-01"}, {"date": "2026-07-02"}],
                "count": 2,
            },
        },
    )

    merged = ResultMerger().merge(
        dag,
        {"weather": result},
        StatelessContext(workspace_id="default", session_id="s", request_id="r", user_input="天气"),
    )

    item = merged["all_results"]["weather"]
    assert item["data"]["summary"] == "one-line summary"
    assert item["data_unwrapped"]["count"] == 2
    assert len(item["data_unwrapped"]["forecast_daily"]) == 2
