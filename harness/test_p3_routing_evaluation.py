"""P3 deterministic routing quality gate."""

from agent.runtime.capability_routing.evaluation import (
    DEFAULT_ROUTING_CASES,
    evaluate_router,
)


def test_default_routing_evaluation_meets_production_gate():
    report = evaluate_router(DEFAULT_ROUTING_CASES)
    assert report["case_count"] >= 15
    assert report["required_capability_recall"] >= 0.95
    assert report["top1_accuracy"] >= 0.90
    assert report["unexpected_capability_rate"] <= 0.10
    assert report["failures"] == []
