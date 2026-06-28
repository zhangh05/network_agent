"""P3 decision-report truth and catalog-expansion contracts."""

from types import SimpleNamespace

from agent.runtime.decision_report.builder import build_decision_report
from agent.runtime.decision_report.models import REPORT_SCHEMA_VERSION
from agent.runtime.tool_execution.catalog_stage import expand_tools_from_catalog_result


def test_decision_report_preserves_nested_routing_structure():
    context = SimpleNamespace(metadata={
        "scene_decision": {"category": "pcap", "signals": {"has_file": True}},
        "capability_routing": {
            "capability_ids": ["pcap_analysis"],
            "route_confidence": {"pcap_analysis": 0.9},
            "candidate_scores": {"pcap_analysis": 8.0},
        },
        "retrieval_decision": {
            "memory": {"status": "skipped", "reason": "not_required"},
            "knowledge": {"status": "hit", "count": 2},
        },
        "dynamic_tool_expansions": [{
            "step": 2,
            "query": "packet sequence",
            "added_tool_ids": ["pcap.manage"],
        }],
        "context_pipeline_meta": {"status": "ok", "stages_run": 13},
    })

    report = build_decision_report(
        run_id="run_1",
        session_id="session_1",
        workspace_id="default",
        context=context,
        result=None,
        result_dict={"tool_calls": []},
    )

    assert REPORT_SCHEMA_VERSION == "decision_report.v2"
    assert report["capability_route"]["route_confidence"]["pcap_analysis"] == 0.9
    assert report["scene_decision"]["signals"]["has_file"] is True
    assert report["catalog_expansions"][0]["added_tool_ids"] == ["pcap.manage"]
    assert report["context_pipeline"]["status"] == "ok"
    assert report["decision_status"] == "complete"


class _Router:
    def expand_dynamic_visibility(self, tool_ids):
        return list(tool_ids)


class _Emitter:
    def emit(self, *_args, **_kwargs):
        return None


def test_catalog_expansion_is_bounded_and_auditable():
    result = SimpleNamespace(
        tool_id="skill.manage",
        ok=True,
        metadata={
            "tool_catalog_expansion": {
                "query": "many tools",
                "load_tool_ids": [f"tool.{i}" for i in range(20)],
                "matched_count": 20,
                "ranking_version": "catalog_rank.v2",
            },
        },
        data={},
        raw={},
    )
    context = SimpleNamespace(
        tool_router=_Router(),
        visible_tool_ids=["skill.manage"],
        metadata={},
    )
    session = SimpleNamespace(session_id="session_1")
    turn = SimpleNamespace(turn_id="turn_1", warnings=[])

    added = expand_tools_from_catalog_result(
        result, context, session, turn, 2, None, _Emitter(),
    )

    assert len(added) == 8
    audit = context.metadata["dynamic_tool_expansions"][0]
    assert audit["requested_count"] == 20
    assert audit["added_count"] == 8
    assert audit["truncated"] is True
    assert audit["ranking_version"] == "catalog_rank.v2"
