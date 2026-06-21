# agent/runtime/retrieval/unknown_feedback.py
"""UnknownFeedback — structured miss reporting for retrieval.

When memory/knowledge/file-evidence retrieval returns no results,
the system MUST explain why, not just return an empty array.

This module provides canonical miss reasons and next-action
suggestions that are machine-readable (for decision reports)
and human-readable (for prompt/UI display).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MissReason(str, Enum):
    """Canonical reasons why retrieval returned no results."""
    NO_INDEX = "no_index"
    SCOPE_EMPTY = "scope_empty"
    QUERY_TOO_BROAD = "query_too_broad"
    FILTERED_BY_SENSITIVITY = "filtered_by_sensitivity"
    NOT_SEARCHED = "not_searched"
    NO_MATCH = "no_match"
    ERROR = "error"


class NextAction(str, Enum):
    """Suggested next actions when retrieval misses."""
    UPLOAD_DOCS = "upload_docs"
    BROADEN_SCOPE = "broaden_scope"
    ASK_USER_CLARIFICATION = "ask_user_clarification"
    RUN_FILE_TOOL = "run_file_tool"
    RETRY_WITH_BROADER_QUERY = "retry_with_broader_query"
    PROCEED_WITHOUT_EVIDENCE = "proceed_without_evidence"
    CHECK_INDEX = "check_index"


# ── Human-readable labels (for prompt/UI) ──

MISS_REASONS: dict[str, str] = {
    MissReason.NO_INDEX.value: "検索インデックスが存在しません。ドキュメントをアップロードしてください。",
    MissReason.SCOPE_EMPTY.value: "現在のワークスペース/セッションに検索対象がありません。",
    MissReason.QUERY_TOO_BROAD.value: "検索クエリが広すぎるため、具体化が必要です。",
    MissReason.FILTERED_BY_SENSITIVITY.value: "秘匿情報を含むため、検索結果がフィルタされました。",
    MissReason.NOT_SEARCHED.value: "このターンでは検索が実行されませんでした。",
    MissReason.NO_MATCH.value: "関連する情報が見つかりませんでした。",
    MissReason.ERROR.value: "検索中にエラーが発生しました。",
}

NEXT_ACTIONS: dict[str, str] = {
    NextAction.UPLOAD_DOCS.value: "関連ドキュメントをアップロードしてください。",
    NextAction.BROADEN_SCOPE.value: "検索範囲を広げるか、別のキーワードで試してください。",
    NextAction.ASK_USER_CLARIFICATION.value: "ユーザーにもう少し具体的に確認してください。",
    NextAction.RUN_FILE_TOOL.value: "ファイルツールを使用して直接ファイルを確認してください。",
    NextAction.RETRY_WITH_BROADER_QUERY.value: "より一般的な検索クエリで再試行してください。",
    NextAction.PROCEED_WITHOUT_EVIDENCE.value: "検索なしで回答を続行してください（信頼性は低くなります）。",
    NextAction.CHECK_INDEX.value: "インデックスの状態を確認してください。",
}


@dataclass
class UnknownFeedback:
    """Structured miss report for one retrieval source.

    Used to populate the miss_reason and next_action fields
    in RetrievalDecision.memory / .knowledge / .file_evidence.
    """

    miss_reason: str = ""
    next_action: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "miss_reason": self.miss_reason,
            "next_action": self.next_action,
            "detail": self.detail[:200] if self.detail else "",
        }

    @classmethod
    def for_no_index(cls, source: str = "retrieval") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.NO_INDEX.value,
            next_action=NextAction.UPLOAD_DOCS.value,
            detail=f"{source}: no index exists",
        )

    @classmethod
    def for_empty_scope(cls, source: str = "retrieval") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.SCOPE_EMPTY.value,
            next_action=NextAction.UPLOAD_DOCS.value,
            detail=f"{source}: scope is empty",
        )

    @classmethod
    def for_no_match(cls, source: str = "retrieval", query: str = "") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.NO_MATCH.value,
            next_action=NextAction.BROADEN_SCOPE.value,
            detail=f"{source}: no match for query '{query[:100]}'",
        )

    @classmethod
    def for_not_searched(cls, reason: str = "") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.NOT_SEARCHED.value,
            next_action=NextAction.PROCEED_WITHOUT_EVIDENCE.value,
            detail=reason or "retrieval was not triggered for this turn",
        )

    @classmethod
    def for_filtered(cls, source: str = "retrieval") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.FILTERED_BY_SENSITIVITY.value,
            next_action=NextAction.ASK_USER_CLARIFICATION.value,
            detail=f"{source}: results filtered due to sensitivity",
        )

    @classmethod
    def for_error(cls, error_detail: str = "") -> "UnknownFeedback":
        return cls(
            miss_reason=MissReason.ERROR.value,
            next_action=NextAction.CHECK_INDEX.value,
            detail=f"retrieval error: {error_detail[:200]}",
        )


# ═══════════════════════════════════════════════════════════════════════
# Convenience: enrich a RetrievalDecision with post-execution results
# ═══════════════════════════════════════════════════════════════════════


def enrich_retrieval_decision(
    decision: "RetrievalDecision",  # noqa: F821
    *,
    memory_results: list = None,
    knowledge_results: list = None,
    file_refs: list = None,
    memory_feedback: "UnknownFeedback" = None,  # noqa: F821
    knowledge_feedback: "UnknownFeedback" = None,  # noqa: F821
    file_feedback: "UnknownFeedback" = None,  # noqa: F821
) -> "RetrievalDecision":  # noqa: F821
    """Enrich a RetrievalDecision with post-execution results.

    Called after the evidence pipeline has completed.
    Populates the .memory, .knowledge, .file_evidence dicts
    with actual hit/miss/error status.
    """
    from agent.runtime.retrieval.trigger_policy import RetrievalDecision

    # ── Memory ──
    mem_results = list(memory_results or [])
    if decision.memory_status != "skipped" and decision.memory_status != "not_applicable":
        if mem_results:
            decision.memory = {
                "status": "hit",
                "hit_count": len(mem_results),
                "query": decision.queries[0] if decision.queries else "",
                "top_k": 5,
                "miss_reason": "",
                "next_action": "",
            }
        elif memory_feedback:
            decision.memory = {
                "status": "miss",
                "hit_count": 0,
                "query": decision.queries[0] if decision.queries else "",
                "top_k": 5,
                "miss_reason": memory_feedback.miss_reason,
                "next_action": memory_feedback.next_action,
            }
        else:
            decision.memory = {
                "status": "miss",
                "hit_count": 0,
                "query": decision.queries[0] if decision.queries else "",
                "top_k": 5,
                "miss_reason": "no_match",
                "next_action": "broaden_scope",
            }

    # ── Knowledge ──
    k_results = list(knowledge_results or [])
    if decision.knowledge_status != "skipped" and decision.knowledge_status != "not_applicable":
        if k_results:
            decision.knowledge = {
                "status": "hit",
                "hit_count": len(k_results),
                "query": decision.queries[0] if decision.queries else "",
                "rewritten_query": "",
                "top_k": 8,
                "min_score": 0.1,
                "miss_reason": "",
                "next_action": "",
            }
        elif knowledge_feedback:
            decision.knowledge = {
                "status": "miss",
                "hit_count": 0,
                "query": decision.queries[0] if decision.queries else "",
                "rewritten_query": "",
                "top_k": 8,
                "min_score": 0.1,
                "miss_reason": knowledge_feedback.miss_reason,
                "next_action": knowledge_feedback.next_action,
            }
        else:
            decision.knowledge = {
                "status": "miss",
                "hit_count": 0,
                "query": decision.queries[0] if decision.queries else "",
                "rewritten_query": "",
                "top_k": 8,
                "min_score": 0.1,
                "miss_reason": "no_match",
                "next_action": "broaden_scope",
            }

    # ── File evidence ──
    f_refs = list(file_refs or [])
    if decision.file_evidence_status != "skipped" and decision.file_evidence_status != "not_applicable":
        if f_refs:
            decision.file_evidence = {
                "status": "hit",
                "file_ids": [f.get("file_id", "") for f in f_refs if isinstance(f, dict)],
                "artifact_ids": [f.get("artifact_id", "") for f in f_refs if isinstance(f, dict)],
                "hit_count": len(f_refs),
                "miss_reason": "",
                "next_action": "",
            }
        elif file_feedback:
            decision.file_evidence = {
                "status": "miss",
                "file_ids": [],
                "artifact_ids": [],
                "hit_count": 0,
                "miss_reason": file_feedback.miss_reason,
                "next_action": file_feedback.next_action,
            }
        else:
            decision.file_evidence = {
                "status": "miss",
                "file_ids": [],
                "artifact_ids": [],
                "hit_count": 0,
                "miss_reason": "no_active_file_refs",
                "next_action": "upload_docs",
            }

    return decision
