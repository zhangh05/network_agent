# agent/llm/runtime.py
"""LLM Runtime — safe_generate with config, policy, and deterministic fallback."""

from typing import Optional
from agent.state import NetworkAgentState
from agent.llm.schemas import (
    LLMRequest, LLMMessage, SafeLLMOutput, PolicyDecision,
)
from agent.llm.context_builder import build_safe_context
from agent.llm.policy import check_request, check_response


def safe_generate(
    task: str,
    state: NetworkAgentState,
    user_question: Optional[str] = None,
) -> SafeLLMOutput:
    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()

    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        return SafeLLMOutput(answer="LLM is disabled.", llm_used=False, fallback_reason="disabled")

    safe_ctx = build_safe_context(state)

    system_prompt = _get_task_prompt(task)
    messages = _build_messages(task, safe_ctx, user_question, system_prompt)

    req = LLMRequest(task=task, safe_context=safe_ctx, messages=messages,
                     model=cfg["model"], temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])

    policy_req = check_request(req, state)
    if not policy_req.allowed:
        return SafeLLMOutput(answer="LLM blocked by policy.", warnings=policy_req.violations,
                             llm_used=False, fallback_reason=f"policy_blocked: {policy_req.reason}")

    from agent.llm.provider import generate
    try:
        resp = generate(req)
    except Exception as e:
        return SafeLLMOutput(answer="Provider error.", llm_used=False,
                             fallback_reason=f"provider: {_redact(str(e))}")

    if resp.error:
        return SafeLLMOutput(answer="Provider unavailable.", llm_used=False,
                             fallback_reason=f"provider: {_redact(resp.error)}")

    policy_resp = check_response(resp, state)
    if not policy_resp.allowed:
        return SafeLLMOutput(answer="Response blocked by safety policy.", warnings=policy_resp.violations,
                             llm_used=False, fallback_reason=f"response_policy: {policy_resp.reason}")

    return SafeLLMOutput(
        summary=resp.content, answer=resp.content, safe_to_show=True,
        policy_decision=policy_resp, llm_used=True,
    )


def _get_task_prompt(task: str) -> str:
    try:
        from agent.llm.tasks.prompts import PROMPTS
        return PROMPTS.get(task, PROMPTS["response_compose"])
    except Exception:
        return "You are a helpful network assistant. Be factual and concise."


def _build_messages(task, safe_ctx, user_question, system_prompt):
    user_msg = user_question or f"Task: {task}\nContext: {safe_ctx}\nProvide a concise summary."
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_msg),
    ]


def _redact(msg: str) -> str:
    for kw in ["Authorization", "Bearer", "api_key", "key", "password"]:
        if kw.lower() in msg.lower():
            return "[REDACTED]"
    return msg[:100]


def get_llm_status() -> dict:
    from agent.llm.config import get_llm_status as _get_status
    return _get_status()
