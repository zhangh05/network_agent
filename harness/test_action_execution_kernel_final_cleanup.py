"""Focused tests for the final Action Execution Kernel cleanup."""

from __future__ import annotations

from types import SimpleNamespace

from agent.runtime.actions.models import ActionPlan, ActionResult, RiskDecision
from agent.runtime.actions.executor import ActionExecutor
from agent.runtime.actions.risk import RiskPolicy
from agent.runtime.actions.evidence_update import EvidenceUpdate
from agent.runtime.actions.scanner import ResultScanner


def test_action_executor_passes_evidence_bundle_to_risk_policy(monkeypatch):
    captured = {}

    class FakeRiskPolicy:
        def evaluate(self, plan, *, ctx=None, evidence_bundle=None):
            captured["ctx"] = ctx
            captured["evidence_bundle"] = evidence_bundle
            return RiskDecision(action_id=plan.action_id, risk_level="low")

    class FakeApprovalGate:
        def decide(self, plan, risk, *, ctx=None):
            return SimpleNamespace(status="not_required", reason="", prompt="")

    class FakeDispatcher:
        def dispatch(self, plan, tool_call, *, ctx=None, state=None):
            return ActionResult(
                action_id=plan.action_id,
                tool_id=plan.tool_id,
                ok=True,
                status="success",
                result={"ok": True, "summary": "listed"},
            )

    executor = ActionExecutor()
    executor.risk_policy = FakeRiskPolicy()
    executor.approval_gate = FakeApprovalGate()
    executor.dispatcher = FakeDispatcher()

    ctx = SimpleNamespace(metadata={}, evidence_bundle=object())
    plan = ActionPlan(tool_id="workspace.file", action_class="read")

    executor.execute(plan, tool_call=object(), ctx=ctx)

    assert captured["ctx"] is ctx
    assert captured["evidence_bundle"] is ctx.evidence_bundle


def test_risk_policy_reads_evidence_bundle_from_ctx_for_write():
    ctx = SimpleNamespace(
        evidence_bundle=SimpleNamespace(conflicts=[object()]),
    )
    plan = ActionPlan(
        tool_id="workspace.file.write",
        action_class="write",
        arguments={"path": "a.txt", "content": "x"},
    )

    risk = RiskPolicy().evaluate(plan, ctx=ctx)

    assert risk.approval_required is True
    assert "evidence_conflict_requires_approval" in risk.warnings



def test_evidence_update_writes_action_evidence_updates():
    ctx = SimpleNamespace(metadata={})
    plan = ActionPlan(action_id="a1", tool_id="workspace.file", action_class="read")
    result = ActionResult(
        action_id="a1",
        tool_id="workspace.file",
        ok=True,
        status="success",
        normalized_result={"summary": "read ok"},
    )

    EvidenceUpdate().update(plan, result, ctx=ctx)

    assert result.evidence_updates
    assert ctx.metadata["action_evidence_updates"]


def test_result_scanner_no_content_is_skipped():
    result = ActionResult(ok=True, status="success", normalized_result={})

    scanned = ResultScanner().scan(result)

    assert scanned.scan_status == "skipped"
