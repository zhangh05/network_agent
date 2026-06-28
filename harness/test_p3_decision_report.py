"""P3 decision-report truth contracts."""

from types import SimpleNamespace

from agent.runtime.decision_report.builder import build_decision_report
from agent.runtime.decision_report.models import REPORT_SCHEMA_VERSION


def test_decision_report_preserves_business_capability_guidance():
    context = SimpleNamespace(metadata={
        "scene_decision": {"category": "pcap", "signals": {"has_file": True}},
        "tool_planning_decision": {
            "visible_tools": ["pcap.manage"],
            "required_tools": ["pcap.manage"],
            "business_capabilities": [{"capability_id": "pcap_analysis"}],
        },
        "retrieval_decision": {
            "memory": {"status": "skipped", "reason": "not_required"},
            "knowledge": {"status": "hit", "count": 2},
        },
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
    assert report["business_capabilities"][0]["capability_id"] == "pcap_analysis"
    assert report["scene_decision"]["signals"]["has_file"] is True
    assert "catalog_expansions" not in report
    assert report["context_pipeline"]["status"] == "ok"
    assert report["decision_status"] == "complete"
