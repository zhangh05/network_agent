# agent/nodes/skill_executor.py
"""Skill executor — routes to skill adapter, records tool_call and trace events."""

import time
from agent.state import NetworkAgentState


def execute(state: NetworkAgentState) -> NetworkAgentState:
    """Execute the selected skill via its adapter."""
    skill = state.selected_skill
    if not skill:
        state.error = "No skill selected"
        return state

    ws_id = state.workspace_id or "default"
    trace_id = state.trace_id or ""
    capability_id = state.context.get("capability_id", "")

    # ── Check if skill is planned/disabled via registry ──
    try:
        from registry.loader import get_skill, get_capability
        skill_spec = get_skill(skill)
        if skill_spec and skill_spec.is_planned():
            state.tool_results = {"ok": False, "error": f"Skill '{skill}' is planned (coming_soon)"}
            state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")
            _add_event(state, "warning", f"planned_skill:{skill}", trace_id, ws_id, status="skipped")
            return state
        if skill_spec and skill_spec.status == "disabled":
            state.error = f"Skill '{skill}' is disabled"
            return state
    except Exception:
        pass

    # ── Record skill_call_start (with capability_id) ──
    _add_event(state, "skill_call_start", f"skill:{skill}", trace_id, ws_id,
               metadata={"capability_id": capability_id})
    skill_start = time.time()

    call = {
        "skill": skill,
        "module": state.active_module,
        "entrypoint": "python_adapter",
        "status": "failed",
    }

    if skill == "config_translation" and state.intent == "translate_config":
        try:
            # ── Record module_call_start ──
            _add_event(state, "module_call_start", "module:config_translation", trace_id, ws_id,
                       metadata={"translator_entry": "translate_bundle"})
            mod_start = time.time()

            from skills.config_translation.adapter import translate
            result = translate(
                source_config=state.payload.get("source_config", state.user_input),
                source_vendor=state.payload.get("source_vendor", "auto"),
                target_vendor=state.payload.get("target_vendor", "huawei"),
            )
            state.tool_results = result
            call["status"] = "success" if result.get("ok") else "failed"

            mod_dur = round((time.time() - mod_start) * 1000, 2)
            _add_event(state, "module_call_end", "module:config_translation",
                       trace_id, ws_id, status=call["status"], duration_ms=mod_dur,
                       summary=f"translate_bundle: {call['status']} ({mod_dur}ms)",
                       metadata={"ok": result.get("ok"), "translator_entry": "translate_bundle"})

            if not result.get("ok"):
                state.error = result.get("error", "translate failed")
        except Exception as exc:
            call["status"] = "failed"
            state.error = str(exc)
            _add_event(state, "module_call_end", "module:config_translation",
                       trace_id, ws_id, status="failed")
    elif state.intent == "context_qa":
        ws = state.payload.get("workspace_summary", {})
        state.tool_results = {
            "ok": True, "workspace_summary": ws,
            "question": state.payload.get("question", ""),
            "manual_review_count": ws.get("last_result_counts", {}).get("manual_review_count", 0),
            "unsupported_count": ws.get("last_result_counts", {}).get("unsupported_count", 0),
            "translator_entry": "context_qa",
        }
        call["status"] = "success"
    else:
        state.tool_results = {"ok": False, "error": f"Skill '{skill}' not implemented"}
        call["status"] = "planned"
        state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")

    state.tool_calls.append(call)

    # ── Record skill_call_end ──
    skill_dur = round((time.time() - skill_start) * 1000, 2)
    _add_event(state, "skill_call_end", f"skill:{skill}",
               trace_id, ws_id, status=call["status"], duration_ms=skill_dur,
               summary=f"skill:{skill}: {call['status']} ({skill_dur}ms)")

    state.context["skill_call_count"] = len(state.tool_calls)
    state.context["module_call_count"] = 1 if skill == "config_translation" and state.intent == "translate_config" else 0

    return state


def _add_event(state, event_type, name, trace_id, ws_id, status="started", duration_ms=0.0,
               summary="", metadata=None):
    state.trace_events.append({
        "event_id": f"{name}_{event_type}",
        "trace_id": trace_id,
        "run_id": state.request_id,
        "workspace_id": ws_id,
        "event_type": event_type,
        "name": name,
        "status": status,
        "duration_ms": duration_ms,
        "summary": summary or f"{event_type}: {name}",
        "metadata": metadata or {},
        "redaction_applied": False,
    })
