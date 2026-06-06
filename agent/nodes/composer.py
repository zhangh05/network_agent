# agent/nodes/composer.py
"""Composer — deterministic by default, LLM-enhanced when available and safe."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response. Uses LLM if enabled and safe, otherwise deterministic."""
    result = state.skill_results or state.tool_results or {}
    intent = state.intent

    # Default deterministic response — assistant_chat uses full state context
    if intent == "assistant_chat":
        deterministic = _assistant_response(state)
    else:
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
        return ("I didn't understand your request. Try:\n"
                "- \"翻译配置\" for config translation\n"
                "- \"你好\" for basic chat\n"
                "- \"你能做什么\" to see capabilities")
    return "Request processed."


def _assistant_response(state: NetworkAgentState) -> str:
    """Generate deterministic assistant response for basic conversation."""
    ui = (state.user_input or "").lower().strip()
    # Greetings
    if any(kw in ui for kw in ["你好", "hello", "hi", "hey"]):
        return ("你好！我是 Network Agent，一个本地网络工程 AI 平台。\n\n"
                "当前唯一启用的业务模块：**配置翻译**（支持 Cisco ↔ 华为 ↔ H3C ↔ 锐捷）\n"
                "我可以帮你：\n"
                "- 翻译网络设备配置\n"
                "- 解释配置翻译结果\n"
                "- 回答关于系统能力的问题\n\n"
                "请输入 \"你能做什么\" 了解更多。")
    # Identity
    if any(kw in ui for kw in ["你是谁", "who are you"]):
        return ("我是 Network Agent，一个 LangGraph 驱动的本地网络工程 AI 助手。\n"
                "当前运行模式：deterministic fallback（LLM 未启用）。\n"
                "我通过 7 个处理节点（router → context → planner → executor → verifier → composer → memory）工作。\n"
                "唯一启用的业务模块是 config_translation（配置翻译）。")
    # Capability
    if any(kw in ui for kw in ["能做", "可以做什么", "what can you do", "help", "帮助"]):
        return ("当前支持的功能：\n\n"
                "**已启用：**\n"
                "- 配置翻译（config_translation）：Cisco ↔ 华为 ↔ H3C ↔ 锐捷 网络设备配置互译\n"
                "- 基础对话（assistant_chat）：回答关于系统能力和使用方式的问题\n\n"
                "**规划中（coming soon）：**\n"
                "- 拓扑绘图（topology）：从设备配置中提取和绘制网络拓扑\n"
                "- 巡检分析（inspection）：合规检查和最佳实践审计\n"
                "- 知识库（knowledge）：网络工程知识库搜索\n\n"
                "安全说明：\n"
                "- 配置翻译输出必须经过人工复核\n"
                "- 不直接生成可下发的配置\n"
                "- 不包含真实设备执行能力")
    # Thanks / Goodbye
    if any(kw in ui for kw in ["谢谢", "thank", "bye", "再见"]):
        return "再见！如有配置翻译需求，随时可以使用 \"翻译配置\" 功能。"
    # Quality / manual_review
    if any(kw in ui for kw in ["质量", "quality", "人工", "manual_review", "风险"]):
        return ("关于配置翻译质量：\n\n"
                "每次翻译都会生成质量摘要（quality_summary），包含：\n"
                "- source_residue_count：源厂商语法残留数\n"
                "- silent_drop_count：静默丢弃的语义行数\n"
                "- review_required_count：需要人工复核的项目数\n\n"
                "如果 source_residue_count > 0 或 silent_drop_count > 0，结果必须经过人工复核。\n"
                "配置翻译不声称可直接下发。")
    # Default friendly response
    return ("你好！有什么我可以帮助你的吗？\n\n"
            "你可以尝试：\n"
            "- \"翻译配置\" — 打开配置翻译\n"
            "- \"你能做什么\" — 查看我的能力\n"
            "- \"解释上次翻译结果\" — 查看上次结果摘要\n"
            "直接粘贴网络配置文本也可以触发翻译。")


def _select_prompt_task(state: NetworkAgentState) -> str:
    """Select prompt task based on intent, context, and user input."""
    ui = (state.user_input or "").lower()
    result = state.skill_results or state.tool_results or {}

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
