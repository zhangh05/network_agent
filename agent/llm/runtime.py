# agent/llm/runtime.py
"""LLM Runtime — unified invocation entry point (invoke_llm) + safe_generate wrapper.

Design:
- invoke_llm() is the SINGLE entry point that calls provider.generate().
- safe_generate() is the public API that wraps invoke_llm() and returns SafeLLMOutput.
- composer / LLMClient / orchestrator ALL go through invoke_llm(), never call generate() directly.
- Policy checks are NON-BLOCKING: results recorded in metadata/warnings only.
"""

import re
from typing import Optional, List
from agent.state import NetworkAgentState
from agent.llm.schemas import LLMRequest, LLMMessage, SafeLLMOutput, PolicyDecision, LLMResponse


def invoke_llm(
    task: str,
    messages: List[LLMMessage] = None,
    tools: List[dict] = None,
    state_or_context=None,
    safe_context: dict = None,
    user_input: str = "",
    extra: dict = None,
) -> LLMResponse:
    """Unified LLM invocation entry point — THE ONLY place that calls generate().

    All LLM calls (composer, orchestrator, LLMClient) MUST go through this function.
    provider.generate() is ONLY called from this function.

    Args:
        task: Prompt task name (used for prompt rendering if messages not provided)
        messages: Pre-built messages (if provided, skip prompt rendering)
        tools: OpenAI-format tool definitions (for function calling)
        state_or_context: NetworkAgentState or dict
        safe_context: Safe context dict for prompt rendering
        user_input: User input (used for prompt rendering)
        extra: Extra context for prompt rendering

    Returns:
        LLMResponse from provider
    """
    # ── Resolve config ──
    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()

    if not cfg.get("enabled") or cfg.get("provider_type") == "disabled":
        return LLMResponse(
            error="LLM is disabled.",
            metadata={
                "error_type": "disabled_by_user",
                "http_status": None,
                "error_detail": "LLM disabled by effective configuration",
            },
        )

    # ── Build messages if not provided ──
    if messages is None:
        messages = _build_prompt_messages(task, state_or_context, safe_context, user_input, extra)

    # ── Build request ──
    req = LLMRequest(
        task=task,
        messages=messages,
        safe_context=safe_context or {},
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        tools=tools,
    )

    # ── Call provider (ONLY place that calls generate()) ──
    from agent.llm.provider import generate, ERROR_TYPE_PROVIDER_TIMEOUT, ERROR_TYPE_PROVIDER_UNKNOWN
    try:
        resp = generate(req)
    except TimeoutError:
        return LLMResponse(
            error="LLM provider request timed out. Please try again.",
            metadata={
                "error_type": ERROR_TYPE_PROVIDER_TIMEOUT,
                "error_detail": "Request timed out",
                "http_status": None,
                "retryable": True,
            },
        )
    except Exception as e:
        redacted = _redact(str(e))
        return LLMResponse(
            error=f"Provider error: {redacted}",
            metadata={"error_type": ERROR_TYPE_PROVIDER_UNKNOWN, "error_detail": redacted[:200]},
        )

    return resp


def safe_generate(
    task: str,
    state_or_context=None,
    context_bundle=None,
    safe_context=None,
    user_input: str = "",
    extra: dict = None,
    messages: List[LLMMessage] = None,
    tools: List[dict] = None,
) -> SafeLLMOutput:
    """Safe LLM generation — policy failures NEVER block the provider call.

    Wraps invoke_llm() and returns SafeLLMOutput with policy metadata.
    """
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

        messages = messages or [
            LLMMessage(role="system", content="You are Network Agent explanation layer. Follow prompt exactly."),
            LLMMessage(role="user", content=rendered.text),
        ]

    except Exception:
        # Prompt runtime unavailable — fallback
        prompt_runtime_fallback = True
        prompt_id = "fallback"
        safe_ctx = _old_safe_context(state)
        system_prompt = _get_system_prompt(task)
        messages = messages or _build_messages(task, safe_ctx, user_input, system_prompt)

    # ── Request policy (NON-BLOCKING) ──
    try:
        from agent.llm.policy import check_request
        policy_req = check_request(LLMRequest(
            task=task,
            messages=messages,
            safe_context=safe_ctx,
            model=cfg.get("model", ""),
            temperature=cfg.get("temperature", 0.2),
            max_tokens=cfg.get("max_tokens", 4096),
            tools=tools,
        ), state)
        if not policy_req.allowed:
            request_policy_ok = False
            request_policy_violations = policy_req.violations
    except Exception:
        pass

    # ── ALWAYS call provider via unified entry point ──
    resp = invoke_llm(
        task=task,
        messages=messages,
        tools=tools,
        state_or_context=state,
        safe_context=safe_ctx,
        user_input=user_input,
        extra=extra,
    )

    if resp.error:
        provider_meta = resp.metadata or {}
        redacted = _redact(resp.error)
        base_meta = _build_metadata(
            prompt_runtime_used, prompt_id, prompt_version, prompt_policy_pass,
            injection_detected, prompt_input_ok, prompt_input_issues,
            prompt_text_ok, prompt_text_issues,
            request_policy_ok, request_policy_violations,
            output_policy_ok, output_policy_issues,
            response_policy_ok, response_policy_violations,
            provider_called=True, output_accepted=False,
        )
        # Merge provider diagnostics into metadata
        base_meta["provider_error_type"] = provider_meta.get("error_type")
        base_meta["http_status"] = provider_meta.get("http_status")
        base_meta["provider_error_message"] = provider_meta.get("error_detail")
        base_meta["raw_error_redacted"] = redacted[:200]
        return SafeLLMOutput(
            answer=f"Provider unavailable: {redacted}",
            llm_used=False,
            fallback_reason=f"provider_unavailable: {redacted}",
            warnings=[f"provider_error: {redacted}"],
            metadata=base_meta,
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


def _build_prompt_messages(
    task: str,
    state_or_context=None,
    safe_context: dict = None,
    user_input: str = "",
    extra: dict = None,
) -> List[LLMMessage]:
    """Build messages by rendering prompt (used when messages not provided to invoke_llm())."""
    try:
        from prompts.loader import get_prompt_by_task
        from prompts.renderer import render_prompt
        spec = get_prompt_by_task(task)
        citations = (safe_context or {}).get("citations", []) if isinstance(safe_context, dict) else []
        rendered = render_prompt(task, safe_context or {}, user_input, citations, extra)
        return [
            LLMMessage(role="system", content="You are Network Agent explanation layer. Follow prompt exactly."),
            LLMMessage(role="user", content=rendered.text),
        ]
    except Exception:
        # Fallback
        safe_ctx = safe_context or {}
        system_prompt = _get_system_prompt(task)
        return _build_messages(task, safe_ctx, user_input, system_prompt)


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
