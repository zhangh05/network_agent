# agent/llm/runtime.py
"""LLM Runtime — safe_generate with Prompt Runtime (yaml+template primary)."""

import re
from typing import Optional
from agent.state import NetworkAgentState
from agent.llm.schemas import LLMRequest, LLMMessage, SafeLLMOutput, PolicyDecision


def safe_generate(
    task: str,
    state_or_context=None,
    context_bundle=None,
    safe_context=None,
    user_input: str = "",
    extra: dict = None,
) -> SafeLLMOutput:
    """Safe LLM generation with Prompt Runtime (prompts/registry.yaml + templates)."""

    # Resolve state
    state = None
    if isinstance(state_or_context, NetworkAgentState):
        state = state_or_context
        ctx = state.context or {}
        if context_bundle is None:
            context_bundle = ctx.get("context_bundle", {})
        if safe_context is None:
            safe_context = ctx.get("safe_llm_context", {})
        user_input = user_input or state.user_input

    safe_ctx = safe_context or {}

    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()

    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        return SafeLLMOutput(answer="LLM is disabled.", llm_used=False, fallback_reason="disabled")

    # ── Prompt Runtime (primary path) ──
    prompt_runtime_used = True
    prompt_runtime_fallback = False
    prompt_id = ""
    prompt_version = ""
    prompt_policy_pass = True
    prompt_block_reason = ""
    injection_detected = False

    try:
        from prompts.loader import get_prompt_by_task
        from prompts.renderer import render_prompt
        from prompts.policy import check_prompt_input, check_prompt_text, check_prompt_output, detect_prompt_injection

        # Injection detection
        inj_result = detect_prompt_injection(user_input)
        injection_detected = inj_result.injection_detected

        spec = get_prompt_by_task(task)
        prompt_id = spec.prompt_id
        prompt_version = spec.version

        # Input policy
        inp_result = check_prompt_input(spec, safe_ctx)
        if not inp_result.ok:
            return SafeLLMOutput(
                answer="LLM blocked by prompt input policy.",
                llm_used=False, fallback_reason=f"prompt_input_blocked: {inp_result.issues}",
                metadata={"prompt_runtime_used": True, "prompt_id": prompt_id,
                          "prompt_version": prompt_version, "prompt_policy_pass": False,
                          "prompt_block_reason": str(inp_result.issues),
                          "prompt_injection_detected": injection_detected},
            )

        # Render
        citations = safe_ctx.get("citations", []) if isinstance(safe_ctx, dict) else []
        rendered = render_prompt(task, safe_ctx, user_input, citations, extra)

        # Text policy — BLOCK on failure
        txt_result = check_prompt_text(rendered.text, spec)
        if not txt_result.ok:
            return SafeLLMOutput(
                answer="LLM blocked: prompt text contains unsafe content.",
                llm_used=False, fallback_reason=f"prompt_text_blocked",
                metadata={"prompt_runtime_used": True, "prompt_id": prompt_id,
                          "prompt_version": prompt_version, "prompt_policy_pass": False,
                          "prompt_block_reason": str(txt_result.issues),
                          "prompt_injection_detected": injection_detected,
                          "rendered_prompt_used": True, "old_prompts_default_path": False},
            )

        # Use rendered.text in messages
        messages = [
            LLMMessage(role="system", content="You are Network Agent explanation layer. Follow prompt exactly."),
            LLMMessage(role="user", content=rendered.text),
        ]

        req = LLMRequest(
            task=task, safe_context=safe_ctx, messages=messages,
            model=cfg["model"], temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
        )

    except Exception:
        # Prompt runtime unavailable — fallback
        prompt_runtime_fallback = True
        prompt_id = "fallback"
        safe_ctx = _old_safe_context(state)
        system_prompt = _get_system_prompt(task)
        messages = _build_messages(task, safe_ctx, user_input, system_prompt)
        req = LLMRequest(
            task=task, safe_context=safe_ctx, messages=messages,
            model=cfg["model"], temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
        )

    # Existing policy check
    from agent.llm.policy import check_request, check_response
    policy_req = check_request(req, state)
    if not policy_req.allowed:
        return SafeLLMOutput(
            answer="LLM blocked by policy.", warnings=policy_req.violations,
            llm_used=False, fallback_reason=f"policy_blocked: {policy_req.reason}",
            metadata={"prompt_runtime_used": prompt_runtime_used, "prompt_id": prompt_id},
        )

    from agent.llm.provider import generate
    try:
        resp = generate(req)
    except Exception as e:
        return SafeLLMOutput(answer="Provider error.", llm_used=False,
                             fallback_reason=f"provider: {_redact(str(e))}")

    if resp.error:
        return SafeLLMOutput(answer="Provider unavailable.", llm_used=False,
                             fallback_reason=f"provider: {_redact(resp.error)}")

    cleaned_content, reasoning_stripped = _sanitize_provider_output(resp.content)
    resp.content = cleaned_content

    # ── Output policy — BLOCK on failure, discard provider output ──
    output_accepted = True
    try:
        from prompts.policy import check_prompt_output
        out_result = check_prompt_output(None, resp.content, citations)
        if not out_result.ok:
            prompt_policy_pass = False
            prompt_block_reason = str(out_result.issues)
            output_accepted = False
            return SafeLLMOutput(
                answer="Response blocked by prompt output policy.",
                llm_used=False, fallback_reason="prompt_output_blocked",
                metadata={
                    "prompt_runtime_used": True, "prompt_id": prompt_id,
                    "prompt_version": prompt_version, "prompt_task": task,
                    "prompt_policy_pass": False, "prompt_block_reason": prompt_block_reason,
                    "prompt_injection_detected": injection_detected,
                    "rendered_prompt_used": True, "old_prompts_default_path": False,
                    "provider_called": True, "output_accepted": False,
                },
            )
    except Exception:
        pass

    policy_resp = check_response(resp, state)
    if not policy_resp.allowed:
        return SafeLLMOutput(answer="Response blocked by safety policy.",
                             warnings=policy_resp.violations, llm_used=False,
                             fallback_reason=f"response_policy: {policy_resp.reason}")

    return SafeLLMOutput(
        summary=resp.content, answer=resp.content, safe_to_show=True,
        llm_used=True, policy_decision=policy_resp,
        metadata={
            "prompt_runtime_used": True, "prompt_id": prompt_id,
            "prompt_version": prompt_version, "prompt_task": task,
            "prompt_policy_pass": prompt_policy_pass,
            "prompt_block_reason": prompt_block_reason,
            "prompt_injection_detected": injection_detected,
            "prompt_runtime_fallback": prompt_runtime_fallback,
            "rendered_prompt_used": True, "old_prompts_default_path": False,
            "output_accepted": output_accepted,
            "reasoning_stripped": reasoning_stripped,
        },
    )


def _get_system_prompt(task: str) -> str:
    try:
        from prompts.loader import get_prompt_by_task
        from prompts.renderer import render_prompt
        r = render_prompt(task, {}, "")
        return r.text[:2000]
    except Exception:
        pass
    return "You are a helpful network assistant. Be factual and concise."


def _old_safe_context(state) -> dict:
    try:
        from agent.llm.context_builder import build_safe_context
        return build_safe_context(state)
    except Exception:
        return {}


def _build_messages(task, safe_ctx, user_question, system_prompt):
    user_msg = user_question or f"Task: {task}\nProvide a concise summary."
    return [LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_msg)]


def _redact(msg: str) -> str:
    for kw in ["Authorization", "Bearer", "api_key", "key", "password"]:
        if kw.lower() in msg.lower():
            return "[REDACTED]"
    return msg[:100]


def _sanitize_provider_output(content: str) -> tuple[str, bool]:
    """Remove provider reasoning markup before UI/history/policy handling."""
    text = content or ""
    original = text
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"(?ism)^\s*(reasoning|思考过程)\s*[:：].*?(?=\n\s*(answer|回答|结论)\s*[:：]|\Z)", "", text)
    text = re.sub(r"(?i)</?(think|reasoning)\b[^>]*>", "", text)
    return text.strip(), text != original


def get_llm_status() -> dict:
    from agent.llm.config import get_llm_status as _gs
    return _gs()
