# agent/runtime/retrieval/trigger_policy.py
"""RetrievalTriggerPolicy — hard rules for when to retrieve memory/knowledge.

Unlike keyword-based signal detection in scene_decision.py,
this policy checks the SEMANTIC STATE of the turn:
  - Context (history decisions, active files, artifacts)
  - User intent (continuation, factual query, tool retry, file references)
  - Environmental state (session stage, previous errors)

Output: RetrievalDecision — structured per-source decision with
  required/skipped/not_applicable status, reason, query scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RetrievalStatus(str, Enum):
    """Whether a retrieval source must / may / must-not be queried."""
    REQUIRED = "required"       # Must query — risk of incomplete answer otherwise
    OPTIONAL = "optional"       # May query — adds value but not critical
    SKIPPED = "skipped"         # Not queried — with mandatory reason
    NOT_APPLICABLE = "not_applicable"  # Source has no index / never loaded


@dataclass
class RetrievalDecision:
    """Unified retrieval strategy for the current turn.

    One instance per turn. Populated before evidence building,
    enriched after retrieval execution.
    """

    # ── Pre-retrieval decisions ──

    memory_status: str = RetrievalStatus.NOT_APPLICABLE.value
    memory_required: bool = False
    memory_reason: str = ""

    knowledge_status: str = RetrievalStatus.NOT_APPLICABLE.value
    knowledge_required: bool = False
    knowledge_reason: str = ""

    file_evidence_status: str = RetrievalStatus.NOT_APPLICABLE.value
    file_evidence_required: bool = False
    file_evidence_reason: str = ""

    # Common query parameters
    queries: list[str] = field(default_factory=list)
    scope: dict = field(default_factory=lambda: {"session": True, "workspace": True, "global": False})

    # ── Post-retrieval results (filled after execution) ──

    memory: dict = field(default_factory=lambda: {
        "status": "not_executed",          # hit|miss|error|not_executed
        "hit_count": 0,
        "query": "",
        "top_k": 5,
        "miss_reason": "",                 # from UnknownFeedback if miss
        "next_action": "",                 # from UnknownFeedback if miss
    })

    knowledge: dict = field(default_factory=lambda: {
        "status": "not_executed",
        "hit_count": 0,
        "query": "",
        "rewritten_query": "",
        "top_k": 8,
        "min_score": 0.1,
        "miss_reason": "",
        "next_action": "",
    })

    file_evidence: dict = field(default_factory=lambda: {
        "status": "not_executed",
        "file_ids": [],
        "artifact_ids": [],
        "hit_count": 0,
        "miss_reason": "",
        "next_action": "",
    })

    def to_dict(self) -> dict:
        """Serialise for Decision Report."""
        return {
            "memory": dict(self.memory),
            "knowledge": dict(self.knowledge),
            "file_evidence": dict(self.file_evidence),
            "_pre_decisions": {
                "memory_status": self.memory_status,
                "memory_required": self.memory_required,
                "memory_reason": self.memory_reason,
                "knowledge_status": self.knowledge_status,
                "knowledge_required": self.knowledge_required,
                "knowledge_reason": self.knowledge_reason,
                "file_evidence_status": self.file_evidence_status,
                "file_evidence_required": self.file_evidence_required,
                "file_evidence_reason": self.file_evidence_reason,
                "queries": list(self.queries),
                "scope": dict(self.scope),
            },
        }


# ═══════════════════════════════════════════════════════════════════════
# RetrievalTriggerPolicy
# ═══════════════════════════════════════════════════════════════════════

# ── Keyword triggers ──

_MEMORY_CONTINUATION_KEYWORDS = (
    "之前", "上次", "继续", "刚才", "刚刚", "上回",
    "记得", "记住", "回忆", "你之前说", "你上次",
    "按我的习惯", "我的偏好", "我的设置", "profile",
    "continue", "previous", "last time", "remember",
    "recall", "preference", "my settings",
)

_MEMORY_DECISION_KEYWORDS = (
    "偏好", "preference", "习惯", "默认", "default",
    "一直", "总是", "usually", "always",
)

_KNOWLEDGE_FACTUAL_KEYWORDS = (
    "文档", "资料", "规范", "手册", "配置解释", "配置说明",
    "故障原因", "故障", "原因是什么", "原因", "报文原因", "工作原理", "协议标准",
    "厂商差异", "产品对比", "版本说明", "技术参数",
    "命令说明", "命令参考", "操作指南", "最佳实践",
    "document", "manual", "spec", "specification",
    "rfc", "standard", "protocol", "best practice",
    "how does", "what is", "explain", "describe",
    "定义", "概念", "术语", "含义", "区别",
)

_KNOWLEDGE_FILE_KEYWORDS = (
    "这个文件", "上传的", "这个文档", "这份资料",
    "这份配置", "这个报文", "这个pcap",
    "this file", "uploaded", "this doc",
)

_RETRY_KEYWORDS = (
    "再试", "重试", "还是不行", "又失败", "retry", "again",
)

# ── RetrievalTriggerPolicy ──


class RetrievalTriggerPolicy:
    """Production-grade retrieval trigger strategy.

    Usage:
        policy = RetrievalTriggerPolicy()
        decision = policy.evaluate(
            user_input=..., session_meta=..., ctx_meta=...,
            has_memory_index=True, has_knowledge_index=True,
        )
        # decision.memory_status → "required" / "optional" / "skipped"
        # decision.knowledge_status → same
        # decision.file_evidence_status → same

    Rules:
      1. Simple chat → all skipped (unless explicit memory/knowledge keywords)
      2. Continuation keywords → memory required
      3. Factual/domain keywords → knowledge required
      4. File refs (file_id/artifact_id) → file evidence required
      5. Tool retry → memory optional, file evidence required
      6. No index → not_applicable (must not query)
    """

    def evaluate(
        self,
        *,
        user_input: str = "",
        session_meta: dict = None,
        ctx_meta: dict = None,
        has_memory_index: bool = True,
        has_knowledge_index: bool = True,
        is_simple_chat: bool = False,
        is_factual_query: bool = False,
        session_has_history: bool = False,
        has_file_refs: bool = False,
        file_ids: list = None,
        artifact_ids: list = None,
        is_tool_retry: bool = False,
    ) -> RetrievalDecision:
        """Evaluate retrieval requirements and return a structured decision."""
        session_meta = session_meta or {}
        ctx_meta = ctx_meta or {}
        lower = (user_input or "").lower()
        decision = RetrievalDecision()

        # ── 1. Memory evaluation ──

        if not has_memory_index:
            decision.memory_status = RetrievalStatus.NOT_APPLICABLE.value
            decision.memory_reason = "no_memory_index"
        else:
            decision.memory_status, decision.memory_required, decision.memory_reason = (
                self._evaluate_memory(
                    lower, session_meta, ctx_meta,
                    is_simple_chat, session_has_history, is_tool_retry,
                )
            )

        # ── 2. Knowledge evaluation ──

        if not has_knowledge_index:
            decision.knowledge_status = RetrievalStatus.NOT_APPLICABLE.value
            decision.knowledge_reason = "no_knowledge_index"
        else:
            decision.knowledge_status, decision.knowledge_required, decision.knowledge_reason = (
                self._evaluate_knowledge(
                    lower, ctx_meta,
                    is_simple_chat, is_factual_query, has_file_refs,
                )
            )

        # ── 3. File evidence evaluation ──

        decision.file_evidence_status, decision.file_evidence_required, decision.file_evidence_reason = (
            self._evaluate_file_evidence(
                ctx_meta, has_file_refs, file_ids, artifact_ids, is_tool_retry,
            )
        )

        # ── 4. Build query scope ──
        decision = self._build_query_scope(decision, lower, session_meta)

        return decision

    # ── Private evaluators ──

    def _evaluate_memory(
        self, lower: str, session_meta: dict, ctx_meta: dict,
        is_simple_chat: bool, session_has_history: bool, is_tool_retry: bool,
    ) -> tuple[str, bool, str]:
        """Determine memory retrieval requirements."""

        # Check for continuation keywords
        if any(kw in lower for kw in _MEMORY_CONTINUATION_KEYWORDS):
            return RetrievalStatus.REQUIRED.value, True, "user_mentioned_continuation_or_memory"

        # Check for decision/preference keywords
        if any(kw in lower for kw in _MEMORY_DECISION_KEYWORDS):
            return RetrievalStatus.REQUIRED.value, True, "user_mentioned_decision_or_preference"

        # Tool retry — memory optional (might have past retry patterns)
        if is_tool_retry:
            return RetrievalStatus.OPTIONAL.value, False, "tool_retry: memory_may_have_past_patterns"

        # Session has significant history — memory optional
        if session_has_history:
            return RetrievalStatus.OPTIONAL.value, False, "session_has_history"

        # Simple chat — skip
        if is_simple_chat:
            return RetrievalStatus.SKIPPED.value, False, "simple_chat: no memory retrieval needed"

        # Default: not applicable (no explicit trigger)
        return RetrievalStatus.SKIPPED.value, False, "no_explicit_memory_trigger"

    def _evaluate_knowledge(
        self, lower: str, ctx_meta: dict,
        is_simple_chat: bool, is_factual_query: bool, has_file_refs: bool,
    ) -> tuple[str, bool, str]:
        """Determine knowledge retrieval requirements."""

        # Explicit factual/domain keywords
        if any(kw in lower for kw in _KNOWLEDGE_FACTUAL_KEYWORDS):
            return RetrievalStatus.REQUIRED.value, True, "user_requested_domain_knowledge"

        # File-related keywords + analysis intent
        if any(kw in lower for kw in _KNOWLEDGE_FILE_KEYWORDS):
            return RetrievalStatus.REQUIRED.value, True, "user_referenced_file_needing_knowledge"

        # Factual query (from scene decision)
        if is_factual_query:
            return RetrievalStatus.REQUIRED.value, True, "factual_query_detected"

        # Has file refs — knowledge may help interpret
        if has_file_refs:
            return RetrievalStatus.OPTIONAL.value, False, "has_file_refs: knowledge_may_help_interpret"

        # Simple chat — skip
        if is_simple_chat:
            return RetrievalStatus.SKIPPED.value, False, "simple_chat: no knowledge retrieval needed"

        # Default: skip
        return RetrievalStatus.SKIPPED.value, False, "no_explicit_knowledge_trigger"

    def _evaluate_file_evidence(
        self, ctx_meta: dict, has_file_refs: bool,
        file_ids: list, artifact_ids: list, is_tool_retry: bool,
    ) -> tuple[str, bool, str]:
        """Determine file evidence retrieval requirements."""
        fids = list(file_ids or []) or []
        aids = list(artifact_ids or []) or []

        if fids or aids:
            return RetrievalStatus.REQUIRED.value, True, f"active_file_refs: {len(fids)} files, {len(aids)} artifacts"

        if has_file_refs:
            return RetrievalStatus.REQUIRED.value, True, "has_file_refs_in_context"

        if is_tool_retry:
            return RetrievalStatus.OPTIONAL.value, False, "tool_retry: file_evidence_may_help"

        return RetrievalStatus.SKIPPED.value, False, "no_active_file_refs"

    def _build_query_scope(
        self, decision: RetrievalDecision, lower: str, session_meta: dict,
    ) -> RetrievalDecision:
        """Set query text and scope based on evaluation results."""
        queries: list[str] = []

        if decision.memory_required or decision.memory_status == RetrievalStatus.OPTIONAL.value:
            queries.append(lower)

        if decision.knowledge_required or decision.knowledge_status == RetrievalStatus.OPTIONAL.value:
            queries.append(lower)

        decision.queries = list(dict.fromkeys(queries))

        # Scope: session only for continuation, workspace+session for normal
        is_continuation = any(kw in lower for kw in _MEMORY_CONTINUATION_KEYWORDS)
        decision.scope = {
            "session": True,
            "workspace": True,
            "global": False if is_continuation else False,
        }

        return decision
