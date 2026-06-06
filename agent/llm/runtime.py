# agent/llm/runtime.py
"""LLM Runtime — safe_generate with policy gates and deterministic fallback."""

import traceback
from typing import Optional

from agent.state import NetworkAgentState
from agent.llm.schemas import (
    LLMRequest, LLMResponse, LLMMessage, SafeLLMOutput, PolicyDecision,
)
from agent.llm.context_builder import build_safe_context
from agent.llm.policy import check_request, check_response
from agent.llm.provider import generate, get_provider_config


def safe_generate(
    task: str,
    state: NetworkAgentState,
    user_question: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> SafeLLMOutput:
    """Safe LLM generation with full policy pipeline. Falls back to deterministic on any issue."""

    # 1. Config check
    cfg = get_provider_config()
    if not cfg.get("enabled") or cfg.get("type") == "disabled":
        return SafeLLMOutput(
            answer="LLM is disabled. Using deterministic composer.",
            llm_used=False,
            fallback_reason="llm_disabled",
        )

    # 2. Build safe context
    safe_ctx = build_safe_context(state)

    # 3. Request policy check
    req = LLMRequest(
        task=task,
        safe_context=safe_ctx,
        messages=build_messages(task, safe_ctx, user_question, system_prompt),
        model=cfg.get("model", ""),
    )
    policy_req = check_request(req, state)
    if not policy_req.allowed:
        return SafeLLMOutput(
            answer=f"LLM request blocked by policy: {policy_req.reason}",
            warnings=policy_req.violations,
            llm_used=False,
            fallback_reason=f"policy_blocked: {policy_req.reason}",
        )

    # 4. Call provider
    try:
        resp = generate(req)
    except Exception as e:
        return SafeLLMOutput(
            answer="LLM provider error. Using fallback.",
            llm_used=False,
            fallback_reason=f"provider_error: {e}",
        )

    if resp.error:
        return SafeLLMOutput(
            answer="LLM unavailable. Using deterministic composer.",
            llm_used=False,
            fallback_reason=f"provider_error: {resp.error}",
        )

    # 5. Response policy check
    policy_resp = check_response(resp, state)
    if not policy_resp.allowed:
        return SafeLLMOutput(
            answer="LLM response blocked by safety policy. Using deterministic composer.",
            warnings=policy_resp.violations,
            llm_used=False,
            fallback_reason=f"response_policy_blocked: {policy_resp.reason}",
        )

    # 6. Success
    return SafeLLMOutput(
        summary=resp.content,
        answer=resp.content,
        safe_to_show=True,
        policy_decision=policy_resp,
        llm_used=True,
    )


def build_messages(task, safe_ctx, user_question, system_prompt):
    """Build LLM messages from context."""
    default_system = (
        "You are a Network Agent assistant. You help explain network configuration "
        "translation results. Never generate or modify deployable configs. "
        "Never approve manual reviews. Stay within the provided summary context."
    )
    sys_msg = system_prompt or default_system

    if user_question:
        user_msg = user_question
    else:
        user_msg = f"Task: {task}\nContext: {safe_ctx}\nProvide a concise summary."

    return [
        LLMMessage(role="system", content=sys_msg),
        LLMMessage(role="user", content=user_msg),
    ]


def get_llm_status() -> dict:
    """Return current LLM status for /api/agent/status."""
    cfg = get_provider_config()

    from agent.llm.schemas import ALLOWED_TASKS, BLOCKED_TASKS

    return {
        "enabled": cfg.get("enabled", False),
        "connected": cfg.get("type") not in ("disabled", None),
        "provider": cfg.get("type", None),
        "model": cfg.get("model", None),
        "safe_mode": True,
        "allowed_tasks": sorted(ALLOWED_TASKS),
        "blocked_tasks": sorted(BLOCKED_TASKS),
        "config_source": "config/llm.yaml",
        "policy_red_lines": [
            "no_generate_deployable_config",
            "no_modify_deployable_config",
            "no_approve_manual_review",
            "no_bypass_translate_bundle",
            "no_bypass_skill_executor",
            "no_call_module_directly",
            "no_fake_planned_module_result",
        ],
    }
