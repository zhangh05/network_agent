# agent/llm/runtime.py
"""LLM Runtime — safe_generate with Prompt Runtime (yaml+template primary).

Policy checks are NON-BLOCKING: results are recorded in metadata/warnings,
but LLM provider is ALWAYS called when enabled=true and api_key exists.
"""

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
    """Safe LLM generation — policy failures NEVER block the provider call."""

    # ── Resolve state ──
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
    injection_detected = False

    # Policy result containers (all non-blocking)
    prompt_input_ok = True
    prompt_input_issues = []
    prompt_text_ok = True
    prompt_text_issues = []
    request_policy_ok = True
    request_policy_violations = []
    output_policy_ok = True
    output_policy_issues = []
    response_policy_ok = True
    response_policy_violations = []

    try:
        from prompts.loader import get_prompt_by_task
        from prompts.renderer import render_prompt
        from prompts.policy import check_prompt_input, check_prompt_text, check_prompt_output, detect_prompt_injection

        # ── Injection detection (non-blocking, record only) ──
        try:
            inj_result = detect_prompt_injection(user_input)
            injection_detected = inj_result.injection_detected
            if inj_result.injection_detected:
                prompt_input_issues.append({"rule": "injection_detected", "warnings": inj_result.warnings})
        except Exception:
            pass

        spec = get_prompt_by_task(task)
        prompt_id = spec.prompt_id
        prompt_version = spec.version

        # ── Input policy (NON-BLOCKING) ──
        try:
            inp_result = check_prompt_input(spec, safe_ctx)
            if not inp_result.ok:
                prompt_input_ok = False
                prompt_input_issues.extend(inp_result.issues)
                prompt_policy_pass = False
        except Exception:
            pass

        # Render
        citations = safe_ctx.get("citations", []) if isinstance(safe_ctx, dict) else []
        rendered = render_prompt(task, safe_ctx, user_input, citations, extra)

        # ── Text policy (NON-BLOCKING) ──
        try:
            txt_result = check_prompt_text(rendered.text, spec)
            if not txt_result.ok:
                prompt_text_ok = False
                prompt_text_issues.extend(txt_result.issues)
                prompt_policy_pass = False
        except Exception:
            pass

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

    # ── Request policy (NON-BLOCKING) ──
    try:
        from agent.llm.policy import check_request
        policy_req = check_request(req, state)
        if not policy_req.allowed:
            request_policy_ok = False
            request_policy_violations = policy_req.violations
    except Exception:
        pass

    # ── ALWAYS call provider if enabled ──
    from agent.llm.provider import generate
    try:
        resp = generate(req)
    except Exception as e:
        redacted = _redact(str(e))
        return SafeLLMOutput(
            answer=f"Provider error: {redacted}",
            llm_used=False,
            fallback_reason=f"provider_error: {redacted}",
            warnings=[f"provider_exception: {redacted}"],
            metadata=_build_metadata(
                prompt_runtime_used, prompt_id, prompt_version, prompt_policy_pass,
                injection_detected, prompt_input_ok, prompt_input_issues,
                prompt_text_ok, prompt_text_issues,
                request_policy_ok, request_policy_violations,
                output_policy_ok=False, output_policy_issues=[],
                response_policy_ok=False, response_policy_violations=[],
                provider_called=False, output_accepted=False,
            ),
        )

    if resp.error:
        redacted = _redact(resp.error)
        return SafeLLMOutput(
            answer=f"Provider unavailable: {redacted}",
            llm_used=False,
            fallback_reason=f"provider_unavailable: {redacted}",
            warnings=[f"provider_error: {redacted}"],
            metadata=_build_metadata(
                prompt_runtime_used, prompt_id, prompt_version, prompt_policy_pass,
                injection_detected, prompt_input_ok, prompt_input_issues,
                prompt_text_ok, prompt_text_issues,
                request_policy_ok, request_policy_violations,
                output_policy_ok=False, output_policy_issues=[],
                response_policy_ok=False, response_policy_violations=[],
                provider_called=True, output_accepted=False,
            ),
        )

    cleaned_content, reasoning_stripped = _sanitize_provider_output(resp.content)
    resp.content = cleaned_content

    # ── Output policy (NON-BLOCKING) ──
    try:
        from prompts.policy import check_prompt_output
        out_result = check_prompt_output(None, resp.content,
                                           safe_ctx.get("citations", []) if isinstance(safe_ctx, dict) else [])
        if not out_result.ok:
            output_policy_ok = False
            output_policy_issues = out_result.issues
            prompt_policy_pass = False
    except Exception:
        pass

    # ── Response policy (NON-BLOCKING) ──
    try:
        from agent.llm.policy import check_response
        policy_resp = check_response(resp, state)
        if not policy_resp.allowed:
            response_policy_ok = False
            response_policy_violations = policy_resp.violations
    except Exception:
        pass

    # ── Build warnings from all policy failures ──
    warnings = []
    if not prompt_input_ok:
        warnings.append(f"prompt_input_policy_failed: {prompt_input_issues}")
    if not prompt_text_ok:
        warnings.append(f"prompt_text_policy_failed: {prompt_text_issues}")
    if not request_policy_ok:
        warnings.extend(request_policy_violations)
    if not output_policy_ok:
        warnings.append(f"output_policy_failed: {output_policy_issues}")
    if not response_policy_ok:
        warnings.extend(response_policy_violations)

    # safe_to_show = hint to UI (true if all policies pass), but answer is ALWAYS returned
    safe_to_show = prompt_policy_pass and request_policy_ok and output_policy_ok and response_policy_ok

    return SafeLLMOutput(
        summary=resp.content, answer=resp.content, safe_to_show=safe_to_show,
        llm_used=True,
        policy_decision=PolicyDecision(allowed=True, reason="non_blocking_mode"),
        warnings=warnings,
        metadata=_build_metadata(
            prompt_runtime_used, prompt_id, prompt_version, prompt_policy_pass,
            injection_detected, prompt_input_ok, prompt_input_issues,
            prompt_text_ok, prompt_text_issues,
            request_policy_ok, request_policy_violations,
            output_policy_ok, output_policy_issues,
            response_policy_ok, response_policy_violations,
            provider_called=True, output_accepted=True,
            reasoning_stripped=reasoning_stripped,
        ),
    )


def _build_metadata(
    prompt_runtime_used, prompt_id, prompt_version, prompt_policy_pass,
    injection_detected,
    prompt_input_ok, prompt_input_issues,
    prompt_text_ok, prompt_text_issues,
    request_policy_ok, request_policy_violations,
    output_policy_ok, output_policy_issues,
    response_policy_ok, response_policy_violations,
    provider_called, output_accepted,
    reasoning_stripped=False,
) -> dict:
    """Build metadata dict with all policy results."""
    return {
        "prompt_runtime_used": prompt_runtime_used,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "prompt_policy_pass": prompt_policy_pass,
        "prompt_injection_detected": injection_detected,
        "prompt_input_ok": prompt_input_ok,
        "prompt_input_issues": prompt_input_issues,
        "prompt_text_ok": prompt_text_ok,
        "prompt_text_issues": prompt_text_issues,
        "request_policy_ok": request_policy_ok,
        "request_policy_violations": request_policy_violations,
        "output_policy_ok": output_policy_ok,
        "output_policy_issues": output_policy_issues,
        "response_policy_ok": response_policy_ok,
        "response_policy_violations": response_policy_violations,
        "rendered_prompt_used": True,
        "old_prompts_default_path": False,
        "provider_called": provider_called,
        "output_accepted": output_accepted,
        "reasoning_stripped": reasoning_stripped,
    }


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
    for kw in ["Authorization", "Bearer", "api_key", "key", "password", "secret"]:
        if kw.lower() in msg.lower():
            return "[REDACTED]"
    return msg[:200]


def sanitize_provider_output(content: str) -> tuple[str, bool]:
    """Remove provider reasoning markup. Public API."""
    text = content or ""
    original = text
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"(?ism)^\s*(reasoning|思考过程)\s*[:：].*?(?=\n\s*(answer|回答|结论)\s*[:：]|\Z)", "", text)
    text = re.sub(r"(?i)</?(think|reasoning)\b[^>]*>", "", text)
    return text.strip(), text != original


_sanitize_provider_output = sanitize_provider_output


def get_llm_status() -> dict:
    from agent.llm.config import get_llm_status as _gs
    return _gs()
