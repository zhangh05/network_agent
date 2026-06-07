# agent/llm/schemas.py
"""LLM schemas — task types, messages, safe output."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class LLMTask(str, Enum):
    ASSISTANT_CHAT = "assistant_chat"
    RESPONSE_COMPOSE = "response_compose"
    MANUAL_REVIEW_EXPLAIN = "manual_review_explain"
    RESULT_SUMMARIZE = "result_summarize"
    CONTEXT_QA = "context_qa"
    JOB_FAILURE_EXPLAIN = "job_failure_explain"
    REPORT_SUMMARY = "report_summary"
    ARTIFACT_SUMMARY_EXPLAIN = "artifact_summary_explain"


ALLOWED_TASKS = {t.value for t in LLMTask}

BLOCKED_TASKS = {
    "generate_deployable_config",
    "modify_deployable_config",
    "approve_manual_review",
    "bypass_translate_bundle",
    "bypass_skill_executor",
    "call_module_directly",
    "fake_planned_module_result",
}


@dataclass
class LLMMessage:
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMRequest:
    task: str
    messages: List[LLMMessage] = field(default_factory=list)
    safe_context: Dict[str, Any] = field(default_factory=dict)
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str = ""
    provider: str = ""
    model: str = ""
    usage: Optional[Dict[str, Any]] = None
    finish_reason: str = ""
    raw: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class PolicyDecision:
    allowed: bool = True
    reason: str = ""
    violations: List[str] = field(default_factory=list)
    redactions: List[str] = field(default_factory=list)


@dataclass
class SafeLLMOutput:
    summary: str = ""
    answer: str = ""
    warnings: List[str] = field(default_factory=list)
    next_questions: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    safe_to_show: bool = True
    policy_decision: Optional[PolicyDecision] = None
    llm_used: bool = False
    fallback_reason: str = ""
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "summary": self.summary,
            "answer": self.answer,
            "warnings": self.warnings,
            "safe_to_show": self.safe_to_show,
            "llm_used": self.llm_used,
            "fallback_reason": self.fallback_reason,
        }
