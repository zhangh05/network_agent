# agent/nodes/composer.py
"""Composer — deterministic by default, LLM-enhanced when available and safe."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response. Uses LLM if enabled and safe, otherwise deterministic."""
    result = state.tool_results or {}
    intent = state.intent

    # Default deterministic response
    deterministic = _deterministic(result, intent)

    # Try LLM
    try:
        from agent.llm.runtime import safe_generate
        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()

        state.context.setdefault("llm", {})
        state.context["llm"].update({
            "enabled": cfg.get("enabled", False),
            "config_source": cfg.get("config_source", "default"),
            "enabled_by_ui": cfg.get("enabled_by_ui"),
            "key_source": cfg.get("key_source", "none"),
            "provider_type": cfg.get("provider_type", "disabled"),
            "provider": cfg.get("provider", cfg.get("default_provider", "disabled")),
            "model": cfg.get("model", ""),
        })

        if cfg.get("enabled") and cfg.get("provider_type") != "disabled":
            # Select task based on intent and context
            task = _select_prompt_task(state)
            output = safe_generate(task, state, user_input=state.user_input)
            state.context["llm"].update({
                "used": output.llm_used,
                "task": task,
                "prompt_task": task,
                "prompt_id": (output.metadata or {}).get("prompt_id", "") if output.metadata else "",
                "prompt_version": (output.metadata or {}).get("prompt_version", "") if output.metadata else "",
                "prompt_runtime_used": (output.metadata or {}).get("prompt_runtime_used", False) if output.metadata else False,
                "prompt_policy_pass": (output.metadata or {}).get("prompt_policy_pass", False) if output.metadata else False,
                "policy_pass": output.policy_decision.allowed if output.policy_decision else False,
                "fallback_reason": output.fallback_reason,
                "violations": output.warnings,
            })

            if output.llm_used and output.safe_to_show:
                state.final_response = output.answer
                state.warnings.extend(output.warnings)
                return state
    except Exception:
        pass

    # Fallback to deterministic
    state.final_response = deterministic
    return state


def _deterministic(result: dict, intent: str) -> str:
    if intent == "translate_config" and result.get("ok"):
        dc = result.get("deployable_config", "")
        mr = result.get("manual_review", [])
        sn = result.get("semantic_near", [])
        us = result.get("unsupported", [])
        lines = dc.strip().split("\n") if dc else []
        return (
            f"Configuration translation completed successfully.\n"
            f"  Deployable lines: {len(lines)}\n"
            f"  Manual review items: {len(mr)}\n"
            f"  Semantic near: {len(sn)}\n"
            f"  Unsupported: {len(us)}\n"
            f"Please review the result in the Config Translation panel."
        )
    elif intent == "context_qa":
        mr = result.get("manual_review_count", 0)
        us = result.get("unsupported_count", 0)
        if mr == 0 and us == 0:
            return "当前摘要里没有人工复核项，也没有不支持项。翻译结果看起来可以直接查看配置翻译面板。"
        parts = ["根据上次翻译结果："]
        if mr > 0:
            parts.append(f"  - {mr} 个项目需要人工复核确认")
        if us > 0:
            parts.append(f"  - {us} 个配置项当前不支持自动翻译")
        parts.append("请切换到「配置翻译」面板查看详情。")
        return "\n".join(parts)
    elif intent in ("topology_draw", "inspection_analyze", "knowledge_search"):
        return f"Module '{result.get('active_module', intent)}' is planned and coming soon. No results available."
    elif intent == "unknown":
        return "I didn't understand your request. Supported: translate_config, topology_draw, inspection_analyze, knowledge_search."
    return "Request processed."


def _select_prompt_task(state: NetworkAgentState) -> str:
    """Select prompt task based on intent, context, and user input."""
    ui = (state.user_input or "").lower()
    result = state.tool_results or {}

    if state.intent == "context_qa":
        if any(kw in ui for kw in ["失败", "失败原因", "为什么失败", "error", "failed"]):
            return "job_failure_explain"
        if any(kw in ui for kw in ["报告", "report", "导出", "文件在哪"]):
            return "report_summary"
        if any(kw in ui for kw in ["artifact", "文件", "输入", "输出", "是什么"]):
            return "artifact_summary_explain"
        return "context_qa"

    mr = result.get("manual_review", [])
    if mr and any(kw in ui for kw in ["人工复核", "为什么复核", "风险", "manual", "什么意思"]):
        return "manual_review_explain"

    if state.error or state.verification.get("status") == "fail":
        return "job_failure_explain"

    if any(kw in ui for kw in ["总结", "摘要", "summarize"]):
        return "result_summarize"

    return "response_compose"
