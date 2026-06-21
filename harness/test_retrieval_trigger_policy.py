# harness/test_retrieval_trigger_policy.py
"""P1-B: RetrievalTriggerPolicy contract tests.

Coverage:
  - Continuation keywords → memory required
  - Factual/domain keywords → knowledge required
  - Simple chat → all skipped
  - File refs → file evidence required
  - Tool retry → memory optional
  - No index → not_applicable
  - Miss/UnknownFeedback correctness
"""

import pytest
from agent.runtime.retrieval.trigger_policy import (
    RetrievalTriggerPolicy,
    RetrievalDecision,
    RetrievalStatus,
)
from agent.runtime.retrieval.unknown_feedback import (
    UnknownFeedback,
    enrich_retrieval_decision,
    MissReason,
    NextAction,
)


@pytest.fixture
def policy():
    return RetrievalTriggerPolicy()


# ─────────────────────────────────────────────────────────────────────
# Memory trigger tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("user_input,expected_status,expected_reason_part", [
    ("继续之前的任务", RetrievalStatus.REQUIRED, "continuation"),
    ("上次的翻译结果还在吗", RetrievalStatus.REQUIRED, "continuation"),
    ("按我的习惯处理", RetrievalStatus.REQUIRED, "continuation"),  # "习惯" hits continuation first
    ("记得我上次的设置", RetrievalStatus.REQUIRED, "continuation"),
    ("Please continue the previous analysis", RetrievalStatus.REQUIRED, "continuation"),
    ("我的偏好是使用H3C", RetrievalStatus.REQUIRED, "continuation"),  # "preference" hits continuation
    ("我一直都这么设置", RetrievalStatus.REQUIRED, "decision_or_preference"),
])
def test_memory_required_for_continuation(policy, user_input, expected_status, expected_reason_part):
    decision = policy.evaluate(
        user_input=user_input,
        has_memory_index=True,
        has_knowledge_index=True,
        session_has_history=True,
    )
    assert decision.memory_status == expected_status.value
    assert expected_reason_part in decision.memory_reason
    assert decision.memory_required is True


def test_memory_optional_for_tool_retry(policy):
    decision = policy.evaluate(
        user_input="再试一次配置分析",
        has_memory_index=True,
        has_knowledge_index=True,
        is_tool_retry=True,
    )
    assert decision.memory_status == RetrievalStatus.OPTIONAL.value
    assert "retry" in decision.memory_reason
    assert decision.memory_required is False


def test_memory_skipped_for_simple_chat(policy):
    decision = policy.evaluate(
        user_input="你好",
        is_simple_chat=True,
        has_memory_index=True,
        has_knowledge_index=True,
    )
    assert decision.memory_status == RetrievalStatus.SKIPPED.value
    assert "simple_chat" in decision.memory_reason
    assert decision.memory_required is False


def test_memory_not_applicable_without_index(policy):
    decision = policy.evaluate(
        user_input="继续之前的任务",
        has_memory_index=False,
        has_knowledge_index=True,
    )
    assert decision.memory_status == RetrievalStatus.NOT_APPLICABLE.value
    assert "no_memory_index" in decision.memory_reason


# ─────────────────────────────────────────────────────────────────────
# Knowledge trigger tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("user_input,expected_status,expected_reason_part", [
    ("这个协议的工作原理是什么", RetrievalStatus.REQUIRED, "domain_knowledge"),
    ("H3C和华为的配置有什么区别", RetrievalStatus.REQUIRED, "domain_knowledge"),
    ("请解释一下OSPF的规范", RetrievalStatus.REQUIRED, "domain_knowledge"),
    ("这个故障的原因是什么", RetrievalStatus.REQUIRED, "domain"),
    ("给我看看配置说明", RetrievalStatus.REQUIRED, "domain"),
    ("How does BGP work?", RetrievalStatus.REQUIRED, "domain_knowledge"),
    ("What is the RFC standard for this?", RetrievalStatus.REQUIRED, "domain_knowledge"),
])
def test_knowledge_required_for_domain_queries(policy, user_input, expected_status, expected_reason_part):
    decision = policy.evaluate(
        user_input=user_input,
        has_knowledge_index=True,
    )
    assert decision.knowledge_status == expected_status.value
    assert expected_reason_part in decision.knowledge_reason
    assert decision.knowledge_required is True


def test_knowledge_required_for_file_ref_with_analysis(policy):
    decision = policy.evaluate(
        user_input="帮我看看这个文件里的配置",
        has_knowledge_index=True,
        has_file_refs=True,
        file_ids=["f_001"],
    )
    assert decision.knowledge_required is True
    assert decision.knowledge_status == RetrievalStatus.REQUIRED.value


def test_knowledge_skipped_for_simple_chat(policy):
    decision = policy.evaluate(
        user_input="你好",
        is_simple_chat=True,
        has_knowledge_index=True,
    )
    assert decision.knowledge_status == RetrievalStatus.SKIPPED.value
    assert decision.knowledge_required is False


def test_knowledge_required_for_factual_query(policy):
    decision = policy.evaluate(
        user_input="配置分析完成了吗",
        is_factual_query=True,
        has_knowledge_index=True,
    )
    assert decision.knowledge_status == RetrievalStatus.REQUIRED.value
    assert decision.knowledge_required is True
    assert "factual" in decision.knowledge_reason.lower()


# ─────────────────────────────────────────────────────────────────────
# File evidence trigger tests
# ─────────────────────────────────────────────────────────────────────


def test_file_evidence_required_with_file_ids(policy):
    decision = policy.evaluate(
        user_input="分析这个报文",
        file_ids=["f_pcap_001"],
        artifact_ids=["art_pcap_001"],
    )
    assert decision.file_evidence_status == RetrievalStatus.REQUIRED.value
    assert decision.file_evidence_required is True
    assert "active_file_refs" in decision.file_evidence_reason


def test_file_evidence_skipped_without_refs(policy):
    decision = policy.evaluate(
        user_input="你好",
        is_simple_chat=True,
    )
    assert decision.file_evidence_status == RetrievalStatus.SKIPPED.value
    assert decision.file_evidence_required is False


# ─────────────────────────────────────────────────────────────────────
# UnknownFeedback tests
# ─────────────────────────────────────────────────────────────────────


def test_unknown_feedback_no_match():
    fb = UnknownFeedback.for_no_match("memory", "session settings")
    assert fb.miss_reason == MissReason.NO_MATCH.value
    assert fb.next_action == NextAction.BROADEN_SCOPE.value


def test_unknown_feedback_no_index():
    fb = UnknownFeedback.for_no_index("knowledge")
    assert fb.miss_reason == MissReason.NO_INDEX.value
    assert fb.next_action == NextAction.UPLOAD_DOCS.value


def test_unknown_feedback_not_searched():
    fb = UnknownFeedback.for_not_searched("simple chat, no trigger")
    assert fb.miss_reason == MissReason.NOT_SEARCHED.value
    assert fb.next_action == NextAction.PROCEED_WITHOUT_EVIDENCE.value


def test_unknown_feedback_for_filtered():
    fb = UnknownFeedback.for_filtered("memory")
    assert fb.miss_reason == MissReason.FILTERED_BY_SENSITIVITY.value
    assert fb.next_action == NextAction.ASK_USER_CLARIFICATION.value


# ─────────────────────────────────────────────────────────────────────
# Enrichment tests
# ─────────────────────────────────────────────────────────────────────


def test_enrich_retrieval_decision_hit():
    policy = RetrievalTriggerPolicy()
    decision = policy.evaluate(
        user_input="继续之前的配置翻译",
        has_memory_index=True,
        has_knowledge_index=True,
    )
    # Enrich with hits
    decision = enrich_retrieval_decision(
        decision,
        memory_results=[{"memory_id": "m1", "content": "test memory"}],
    )
    assert decision.memory["status"] == "hit"
    assert decision.memory["hit_count"] == 1


def test_enrich_retrieval_decision_miss():
    policy = RetrievalTriggerPolicy()
    decision = policy.evaluate(
        user_input="继续之前的配置翻译",
        has_memory_index=True,
        has_knowledge_index=True,
    )
    fb = UnknownFeedback.for_no_match("memory")
    decision = enrich_retrieval_decision(
        decision,
        memory_results=[],
        memory_feedback=fb,
    )
    assert decision.memory["status"] == "miss"
    assert decision.memory["hit_count"] == 0
    assert decision.memory["miss_reason"] == "no_match"


def test_enrich_retrieval_decision_skipped_source_not_enriched():
    """Skipped sources should NOT be overwritten by enrichment."""
    policy = RetrievalTriggerPolicy()
    decision = policy.evaluate(
        user_input="你好",
        is_simple_chat=True,
        has_memory_index=True,
        has_knowledge_index=True,
    )
    # Memory was skipped — enrichment should not change its status
    original_mem = dict(decision.memory)
    decision = enrich_retrieval_decision(
        decision,
        memory_results=[{"memory_id": "m1", "content": "unexpected hit"}],
    )
    # Skipped should remain unchanged
    assert decision.memory == original_mem


def test_enrich_retrieval_decision_with_file_refs():
    policy = RetrievalTriggerPolicy()
    decision = policy.evaluate(
        user_input="分析这个报文",
        file_ids=["f_pcap_001"],
        has_file_refs=True,
    )
    decision = enrich_retrieval_decision(
        decision,
        file_refs=[{"file_id": "f_pcap_001"}],
    )
    assert decision.file_evidence["status"] == "hit"
    assert "f_pcap_001" in decision.file_evidence["file_ids"]


# ─────────────────────────────────────────────────────────────────────
# Decision Report integration test
# ─────────────────────────────────────────────────────────────────────


def test_retrieval_decision_to_dict():
    policy = RetrievalTriggerPolicy()
    decision = policy.evaluate(
        user_input="继续之前的任务，帮我解释这个协议的工作原理",
        has_memory_index=True,
        has_knowledge_index=True,
        has_file_refs=True,
        file_ids=["f_001"],
        session_has_history=True,
    )
    fb = UnknownFeedback.for_no_match("knowledge")
    decision = enrich_retrieval_decision(
        decision,
        memory_results=[{"memory_id": "m1"}],
        knowledge_results=[],
        knowledge_feedback=fb,
        file_refs=[{"file_id": "f_001"}],
    )
    d = decision.to_dict()
    # Check structure
    assert "memory" in d
    assert "knowledge" in d
    assert "file_evidence" in d
    assert "_pre_decisions" in d
    # Memory hit
    assert d["memory"]["status"] == "hit"
    assert d["memory"]["hit_count"] == 1
    # Knowledge miss with feedback
    assert d["knowledge"]["status"] == "miss"
    assert d["knowledge"]["miss_reason"] == "no_match"
    # File evidence hit
    assert d["file_evidence"]["status"] == "hit"
    # Pre-decisions preserved
    assert d["_pre_decisions"]["memory_required"] is True
    assert d["_pre_decisions"]["knowledge_required"] is True
