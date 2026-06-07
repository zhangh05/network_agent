# agent/nodes/composer.py
"""Composer — deterministic by default, LLM-enhanced when available and safe."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response. Uses LLM if enabled and safe, otherwise deterministic."""
    result = state.skill_results or state.tool_results or {}
    intent = state.intent

    # ── assistant_chat: try LLM first, fallback to deterministic ──
    if intent == "assistant_chat":
        _compose_assistant_chat(state)
        return state

    # ── context_qa: term explain shortcut ──
    if intent == "context_qa":
        term = _quality_term_response(state.user_input or "")
        if term:
            state.final_response = term
            _set_llm_bypass_metadata(state, "local_term_explain")
            return state
        deterministic = _deterministic(result, intent)
    else:
        deterministic = _deterministic(result, intent)

    # Try LLM for non-chat intents
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


def _compose_assistant_chat(state: NetworkAgentState):
    """Compose assistant_chat response: try LLM, fallback to deterministic."""
    import traceback
    state.context.setdefault("llm", {})
    llm = state.context["llm"]

    # 1. Try LLM
    try:
        from agent.llm.runtime import safe_generate
        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()

        llm.update({
            "enabled": cfg.get("enabled", False),
            "config_source": cfg.get("config_source", "default"),
            "provider_type": cfg.get("provider_type", "disabled"),
            "provider": cfg.get("provider", cfg.get("default_provider", "disabled")),
            "model": cfg.get("model", ""),
        })

        if cfg.get("enabled") and cfg.get("provider_type") != "disabled":
            try:
                output = safe_generate("assistant_chat", state, user_input=state.user_input)
                llm.update({
                    "used": output.llm_used,
                    "task": "assistant_chat",
                    "prompt_id": (output.metadata or {}).get("prompt_id", "") if output.metadata else "",
                    "policy_pass": output.policy_decision.allowed if output.policy_decision else False,
                })
                if output.llm_used and output.safe_to_show:
                    state.final_response = output.answer
                    state.warnings.extend(output.warnings)
                    llm["fallback"] = False
                    return
                else:
                    llm["fallback"] = True
                    llm["fallback_reason"] = output.fallback_reason or "llm output blocked by policy"
            except Exception as e:
                llm["fallback"] = True
                llm["fallback_reason"] = f"provider unavailable: {str(e)[:100]}"
        else:
            llm["fallback"] = True
            llm["fallback_reason"] = "llm disabled"
    except Exception as e:
        llm["fallback"] = True
        llm["fallback_reason"] = f"config error: {str(e)[:100]}"

    # 2. Deterministic fallback
    state.final_response = _assistant_response(state)
    if not llm.get("fallback"):
        llm["fallback"] = True
        llm["fallback_reason"] = llm.get("fallback_reason") or "deterministic fallback"


def _deterministic(result: dict, intent: str) -> str:
    if intent == "translate_config" and result.get("ok"):
        dc = result.get("deployable_config", "")
        mr = result.get("manual_review", [])
        sn = result.get("semantic_near", [])
        us = result.get("unsupported", [])
        qs = result.get("quality_summary", {}) if isinstance(result.get("quality_summary", {}), dict) else {}
        residue = int(qs.get("source_residue_count", 0) or 0)
        silent = int(qs.get("silent_drop_count", 0) or 0)
        safe_drop = int(qs.get("safe_drop_count", 0) or 0)
        review_required = int(qs.get("review_required_count", len(mr)) or 0)
        lines = dc.strip().split("\n") if dc else []
        headline = "Configuration translation completed with review required." if (residue or silent or review_required) else "Configuration translation completed."
        return (
            f"{headline}\n"
            f"  Deployable lines: {len(lines)}\n"
            f"  Manual review items: {len(mr)}\n"
            f"  Semantic near: {len(sn)}\n"
            f"  Unsupported: {len(us)}\n"
            f"  Quality summary: source_residue={residue}, silent_drop={silent}, "
            f"unsupported={len(us)}, safe_drop={safe_drop}, review_required={review_required}\n"
            f"请回顾配置翻译面板；生产使用前仍需人工复核。"
        )
    elif intent == "context_qa":
        mr = result.get("manual_review_count", 0)
        us = result.get("unsupported_count", 0)
        if mr == 0 and us == 0:
            return "当前没有人工复核项和不支持项。翻译结果已生成，请在配置翻译面板查看；生产使用前仍需人工复核。"
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
        return ("你好，我是 Network Agent，一个本地网络工程 Agent。\n"
                "当前正式启用的业务模块是配置翻译；拓扑、巡检、知识库、CMDB 还在规划中。")
    # Identity
    if any(kw in ui for kw in ["什么模型", "你是什么", "model", "what are you"]):
        return _model_response()
    if any(kw in ui for kw in ["你是谁", "who are you"]):
        return ("我是 Network Agent，本地网络工程 Agent 平台。\n"
                "你可以和我正常对话；当你明确提出配置翻译需求时，我会进入配置翻译流程。")
    # Capability
    if any(kw in ui for kw in ["能做", "可以做什么", "what can you do", "help", "帮助"]):
        return ("目前我能正常对话、解释平台能力，并处理配置翻译。\n"
                "拓扑、巡检、知识库、CMDB 仍是 planned，不会伪造结果。")
    if any(kw in ui for kw in ["状态", "健康", "后端", "连接", "端口", "地址"]):
        return _status_response()
    if any(kw in ui for kw in ["memory", "记忆", "历史", "history", "run history"]):
        return _memory_response()
    # Thanks / Goodbye
    if any(kw in ui for kw in ["谢谢", "thank", "bye", "再见"]):
        return "再见！如有配置翻译需求，随时可以使用 \"翻译配置\" 功能。"
    # Quality / manual_review
    if any(kw in ui for kw in ["质量", "quality", "人工", "manual_review", "风险"]):
        return ("配置翻译质量摘要包含 source_residue_count（源残留）、silent_drop_count（静默丢弃）、"
                "review_required_count（需复核）。\n"
                "如有残留或丢弃项，结果必须经过人工复核；配置翻译不声明结果可用于设备执行。")
    # Weather / real-time / news — no tools available
    if any(kw in ui for kw in ["天气", "weather", "新闻", "news", "股票", "stock", "热搜"]):
        return ("我当前没有接入实时查询工具，无法查询最新天气、新闻或股票数据。\n"
                "后续接入对应工具后才能处理这类实时问题。")
    # Default friendly response
    return ("你好！有什么我可以帮助你的吗？\n\n"
            "你可以尝试：\n"
            "- \"翻译配置\" — 打开配置翻译\n"
            "- \"你能做什么\" — 查看我的能力\n"
            "直接粘贴网络配置文本也可以触发翻译。")


def _quality_term_response(user_input: str) -> str:
    ui = (user_input or "").lower()
    explanations = {
        "manual_review": "manual_review 是配置翻译产生的人工复核清单，用来记录需要工程师确认的语义、风险或厂商差异项。",
        "quality_summary": "quality_summary 是配置翻译质量摘要，只包含计数类指标，例如 source_residue_count、silent_drop_count、unsupported_count、safe_drop_count 和 review_required_count。",
        "source_residue": "source_residue 表示目标配置中仍残留源厂商语法。只要 source_residue_count > 0，就必须进入 warning 和 manual_review。",
        "silent_drop": "silent_drop 表示源配置中的有意义语义没有进入目标配置、unsupported、semantic_near 或 manual_review。只要 silent_drop_count > 0，就必须人工复核。",
    }
    for key, text in explanations.items():
        if key in ui:
            return text
    return None


def _model_response() -> str:
    try:
        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()
        if cfg.get("enabled"):
            key_status = "key 已加载" if cfg.get("key_loaded") else "key 未加载"
            return (
                "我是 Network Agent，本地网络工程 Agent 平台里的基础助手。\n"
                f"当前后端 LLM 配置已启用：provider={cfg.get('provider')}, "
                f"model={cfg.get('model')}, source={cfg.get('config_source')}，{key_status}。\n"
                "但基础问候、身份说明和安全边界说明会优先使用本地 deterministic assistant_chat，"
                "避免把简单对话误路由到业务模块或生成不安全结论。"
            )
    except Exception:
        pass
    return (
        "我是 Network Agent，本地网络工程 Agent 平台里的基础助手。\n"
        "当前基础对话由 deterministic assistant_chat 处理；LLM 仅在允许的增强任务中使用。"
    )


def _status_response() -> str:
    try:
        from agent.llm.config import get_llm_status
        llm = get_llm_status()
    except Exception:
        llm = {}
    provider = llm.get("provider") or llm.get("default_provider") or "disabled"
    model = llm.get("model") or "未设置"
    source = llm.get("config_source") or "default"
    if llm.get("connected"):
        connected = "已连接"
    elif llm.get("enabled"):
        connected = "已启用，key 未加载或健康检查未通过"
    else:
        connected = "未启用"
    return (
        "当前平台状态：\n"
        "- 后端：已连接\n"
        "- 监听地址：0.0.0.0:8010（可用本网口 IP 访问）\n"
        "- 已启用业务模块：config_translation\n"
        "- 基础 Agent 对话：assistant_chat\n"
        f"- LLM：{connected}，provider={provider}，model={model}，source={source}\n"
        "- Topology / Inspection / CMDB / Knowledge：planned / coming_soon"
    )


def _memory_response() -> str:
    total = None
    try:
        from memory.store import get_store
        total = get_store().count()
    except Exception:
        pass
    total_line = f"- 当前可见记忆记录：{total}\n" if total is not None else ""
    return (
        "Memory 是后端工作区记忆层，不再靠浏览器 localStorage 伪造历史。\n"
        f"{total_line}"
        "- 记录范围：安全摘要、上下文线索、运行摘要\n"
        "- 不保存完整 source_config、deployable_config、prompt、密钥或绝对路径\n"
        "- 前端 Memory 管理页会从后端接口加载真实数据\n"
        "- Run History 也以后端 workspace_id 为主，同一个 workspace 可跨浏览器查看"
    )


def _set_llm_bypass_metadata(state: NetworkAgentState, reason: str):
    state.context.setdefault("llm", {})
    try:
        from agent.llm.config import resolve_provider_config
        cfg = resolve_provider_config()
        state.context["llm"].update({
            "enabled": cfg.get("enabled", False),
            "provider": cfg.get("provider", cfg.get("default_provider", "disabled")),
            "model": cfg.get("model", ""),
            "config_source": cfg.get("config_source", "default"),
            "enabled_by_ui": cfg.get("enabled_by_ui"),
            "used": False,
            "fallback_reason": reason,
        })
    except Exception:
        state.context["llm"].update({"used": False, "fallback_reason": reason})


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
