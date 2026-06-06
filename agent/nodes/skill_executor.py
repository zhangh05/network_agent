# agent/nodes/skill_executor.py
"""Skill executor — dynamically loads adapter via registry. No hardcoded imports."""

import importlib
import time
from agent.state import NetworkAgentState


def execute(state: NetworkAgentState) -> NetworkAgentState:
    """Execute selected skill via registry-driven dynamic adapter loading."""
    skill = state.selected_skill
    capability_id = state.context.get("capability_id", "")
    cap_status = state.context.get("capability_status", "unknown")

    if not skill:
        state.error = "No skill selected"
        return state

    ws_id = state.workspace_id or "default"
    trace_id = state.trace_id or ""

    # ── 1. Look up skill + capability from registry ──
    skill_spec = None
    cap_spec = None
    try:
        from registry.loader import get_skill, get_capability
        skill_spec = get_skill(skill)
        cap_spec = get_capability(capability_id) if capability_id else None
    except Exception:
        pass

    # ── 2. Block planned/disabled ──
    if cap_status == "planned":
        state.tool_results = {"ok": False, "error": f"Intent '{state.intent}' is planned (coming_soon)"}
        state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")
        _add_event(state, "warning", f"planned_skill:{skill}", trace_id, ws_id, status="planned",
                   metadata={"capability_id": capability_id})
        state.tool_calls.append({"capability_id": capability_id, "skill": skill, "status": "planned"})
        return state

    if (skill_spec and skill_spec.status == "disabled") or cap_status == "disabled":
        state.error = f"Skill '{skill}' is disabled"
        _add_event(state, "error", f"disabled_skill:{skill}", trace_id, ws_id, status="failed")
        return state

    # ── 3. Resolve adapter path + function from registry ──
    adapter_path = ""
    entrypoint_fn = ""

    if skill_spec:
        adapter_path = skill_spec.adapter_path or ""
        entrypoint_fn = skill_spec.entrypoint_function or ""

    # Capability may override the function
    if cap_spec and capability_id:
        # Look for capability-specific function in skill.yaml capabilities list
        for cap_entry in (skill_spec.capabilities if skill_spec else []):
            if isinstance(cap_entry, dict) and cap_entry.get("capability_id") == capability_id:
                fn = cap_entry.get("function", "")
                if fn:
                    entrypoint_fn = fn
                break

    if not adapter_path:
        state.error = f"No adapter path for skill '{skill}'"
        return state
    if not entrypoint_fn:
        state.error = f"No entrypoint function for capability '{capability_id}'"
        return state

    # ── 4. Record skill_call_start ──
    _add_event(state, "skill_call_start", f"skill:{skill}", trace_id, ws_id,
               metadata={"capability_id": capability_id, "adapter_path": adapter_path, "entrypoint": entrypoint_fn})
    skill_start = time.time()

    tool_call = {
        "capability_id": capability_id, "skill": skill,
        "module": state.active_module, "adapter_path": adapter_path,
        "entrypoint": entrypoint_fn, "status": "failed",
    }

    # ── 5. Dynamically load and call adapter ──
    try:
        # Record module_call_start
        _add_event(state, "module_call_start", f"module:{state.active_module}", trace_id, ws_id,
                   metadata={"adapter_path": adapter_path, "entrypoint": entrypoint_fn})
        mod_start = time.time()

        func = _load_adapter(adapter_path, entrypoint_fn)

        result = func(
            source_config=state.payload.get("source_config", state.user_input),
            source_vendor=state.payload.get("source_vendor", "auto"),
            target_vendor=state.payload.get("target_vendor", "huawei"),
        )

        state.tool_results = result if isinstance(result, dict) else {"ok": True, "data": result}
        tool_call["status"] = "success" if result.get("ok", True) else "failed"

        if isinstance(result, dict) and not result.get("ok"):
            state.error = result.get("error", "execution failed")

        mod_dur = round((time.time() - mod_start) * 1000, 2)
        _add_event(state, "module_call_end", f"module:{state.active_module}",
                   trace_id, ws_id, status=tool_call["status"], duration_ms=mod_dur,
                   summary=f"{entrypoint_fn}: {tool_call['status']} ({mod_dur}ms)",
                   metadata={"entrypoint": entrypoint_fn, "ok": tool_call["status"] == "success"})

    except Exception as exc:
        tool_call["status"] = "failed"
        state.error = str(exc)
        _add_event(state, "module_call_end", f"module:{state.active_module}",
                   trace_id, ws_id, status="failed",
                   metadata={"error": str(exc)[:200]})

    state.tool_calls.append(tool_call)

    skill_dur = round((time.time() - skill_start) * 1000, 2)
    _add_event(state, "skill_call_end", f"skill:{skill}",
               trace_id, ws_id, status=tool_call["status"], duration_ms=skill_dur,
               summary=f"skill:{skill}: {tool_call['status']} ({skill_dur}ms)",
               metadata={"capability_id": capability_id, "adapter_path": adapter_path})

    state.context["skill_call_count"] = len(state.tool_calls)
    state.context["module_call_count"] = state.context.get("module_call_count", 0) + 1

    return state


def _load_adapter(adapter_path: str, function_name: str):
    """Dynamically load an adapter function from a path like 'skills/config_translation/adapter.py'."""
    # Convert path → module: skills/config_translation/adapter.py → skills.config_translation.adapter
    mod_path = adapter_path.replace(".py", "").replace("/", ".")
    mod = importlib.import_module(mod_path)
    return getattr(mod, function_name)


def _add_event(state, event_type, name, trace_id, ws_id, status="started", duration_ms=0.0,
               summary="", metadata=None):
    state.trace_events.append({
        "event_id": f"{name}_{event_type}_{len(state.trace_events)}",
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
