# agent/nodes/skill_executor.py
"""Skill executor — dynamically loads adapter via registry. Generic and skill.yaml-driven.

New skill additions ONLY require:
  1. modules/<name>/...          — business logic
  2. skills/<name>/adapter.py    — thin adapter function(payload) -> dict
  3. skills/<name>/skill.yaml     — registration + config

No executor/composer code changes needed.
"""

import importlib
import time
from typing import Dict, Any, Callable
from agent.state import NetworkAgentState


def execute(state: NetworkAgentState) -> NetworkAgentState:
    """Execute selected skill via registry-driven dynamic adapter loading.

    Generic flow:
      1. Resolve skill spec from registry
      2. Gate-check: enabled/planned/disabled
      3. Resolve artifact_id → read content into payload
      4. Auto-save input artifact (if skill.yaml says so)
      5. Dynamically load and call adapter function(payload)
      6. Auto-save output artifact (if skill.yaml says so)
      7. Record trace events
    """
    skill = state.selected_skill
    capability_id = state.context.get("capability_id", "")
    cap_status = state.context.get("capability_status", "unknown")
    ws_id = state.workspace_id or "default"
    trace_id = state.trace_id or ""

    # ── 0. No-op for builtins ──
    if state.intent in ("assistant_chat", "knowledge_query") or (not skill and not capability_id):
        state.skill_results = {"ok": True, "intent": state.intent, "mode": "builtin"}
        state.tool_results = state.skill_results
        _add_event(state, "skill_call_start", "skill:noop", ws_id=ws_id,
                   metadata={"intent": state.intent, "status": "noop"})
        _add_event(state, "skill_call_end", "skill:noop", ws_id=ws_id, status="success",
                   summary=f"noop for {state.intent}")
        state.context["skill_call_count"] = 0
        return state

    if not skill:
        state.error = "No skill selected"
        return state

    # ── 1. Load skill spec ──
    skill_spec = _load_skill_spec(skill)
    if not skill_spec:
        state.error = f"skill_spec_not_found: {skill}"
        return state

    # ── 2. Gate check ──
    if cap_status == "planned":
        state.skill_results = {"ok": False, "error": f"Intent '{state.intent}' is planned (coming_soon)"}
        state.tool_results = state.skill_results
        state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")
        _add_event(state, "warning", f"planned_skill:{skill}", ws_id=ws_id, status="planned")
        state.skill_calls.append({"capability_id": capability_id, "skill": skill, "status": "planned"})
        state.tool_calls = state.skill_calls
        return state

    if skill_spec.get("status") == "disabled" or cap_status == "disabled":
        state.error = f"Skill '{skill}' is disabled"
        return state

    # ── 3. Resolve artifact_id → source_config ──
    _resolve_artifact_input(state)

    # ── 4. Auto-save input artifact ──
    _auto_save_input(state, skill_spec)

    # ── 5. Load and call adapter ──
    entrypoint_fn = _resolve_entrypoint(skill_spec, capability_id)
    if not entrypoint_fn:
        state.error = f"No entrypoint for capability '{capability_id}'"
        return state

    adapter_path = skill_spec.get("adapter_path", "")
    skill_call = {"capability_id": capability_id, "skill": skill,
                  "module": state.active_module, "adapter_path": adapter_path,
                  "entrypoint": entrypoint_fn, "status": "failed"}

    _add_event(state, "skill_call_start", f"skill:{skill}", ws_id=ws_id,
               metadata={"capability_id": capability_id, "adapter_path": adapter_path})
    _add_event(state, "module_call_start", f"module:{state.active_module}", ws_id=ws_id)

    t0 = time.time()
    try:
        func = _load_adapter(adapter_path, entrypoint_fn)

        # Universal signature: adapter receives payload dict
        result = func(payload=state.payload)

        state.skill_results = result if isinstance(result, dict) else {"ok": True, "data": result}
        state.tool_results = state.skill_results

        skill_call["status"] = "success" if result.get("ok", True) else "failed"
        if not result.get("ok"):
            state.error = result.get("error", "execution_failed")
        if result.get("warnings"):
            state.warnings.extend(str(w) for w in result.get("warnings", [])[:20])

    except Exception as exc:
        skill_call["status"] = "failed"
        state.error = str(exc)
        _add_event(state, "module_call_end", f"module:{state.active_module}",
                   ws_id=ws_id, status="failed", metadata={"error": str(exc)[:200]})

    dur = round((time.time() - t0) * 1000, 2)
    _add_event(state, "module_call_end", f"module:{state.active_module}",
               ws_id=ws_id, status=skill_call["status"], duration_ms=dur,
               summary=f"{entrypoint_fn}: {skill_call['status']} ({dur}ms)")
    _add_event(state, "skill_call_end", f"skill:{skill}", ws_id=ws_id,
               status=skill_call["status"], duration_ms=dur)

    state.skill_calls.append(skill_call)
    state.tool_calls = state.skill_calls
    state.context["skill_call_count"] = len(state.skill_calls)
    state.context["module_call_count"] = state.context.get("module_call_count", 0) + 1

    # ── 6. Auto-save output artifact ──
    _auto_save_output(state, skill_spec)

    return state


# ═══════════════ Helpers ═══════════════

def _load_skill_spec(skill_name: str) -> dict:
    """Load skill spec from registry as a plain dict."""
    try:
        from registry.loader import get_skill
        spec = get_skill(skill_name)
        if spec:
            return {
                "skill_name": spec.skill_name,
                "status": spec.status,
                "adapter_path": spec.adapter_path,
                "entrypoint_function": spec.entrypoint_function,
                "capabilities": spec.capabilities,
                "artifact": getattr(spec, "artifact", {}),
                "compose": getattr(spec, "compose", {}),
            }
    except Exception:
        pass
    return {}


def _resolve_entrypoint(skill_spec: dict, capability_id: str) -> str:
    """Resolve which adapter function to call."""
    # Capability-specific function takes priority
    for cap in skill_spec.get("capabilities", []):
        if isinstance(cap, dict) and cap.get("capability_id") == capability_id:
            fn = cap.get("function", "")
            if fn:
                return fn
    # Fallback to skill-level entrypoint
    return skill_spec.get("entrypoint_function", "")


def _resolve_artifact_input(state: NetworkAgentState):
    """If artifact_id is in payload, read content into source_config."""
    artifact_id = state.payload.get("artifact_id", "")
    if not artifact_id or state.payload.get("source_config"):
        return

    ws_id = state.workspace_id or "default"
    try:
        from artifacts.store import get_artifact, read_artifact_content
        art = get_artifact(ws_id, artifact_id)
        if not art:
            state.error = f"artifact_not_found: {artifact_id}"
            return
        if art.sensitivity == "secret":
            state.error = f"artifact_type_not_allowed: secret"
            return
        content = read_artifact_content(ws_id, artifact_id, allow_sensitive=True)
        if content is None:
            state.error = f"artifact_content_not_allowed: {artifact_id}"
            return
        state.payload["source_config"] = content
        _add_event(state, "artifact_read", f"artifact:{artifact_id}", ws_id=ws_id, status="success",
                   summary=f"read {art.artifact_type}:{art.title}",
                   metadata={"artifact_id": artifact_id, "artifact_type": art.artifact_type,
                             "size_bytes": art.size_bytes})
    except Exception as exc:
        state.error = f"artifact_read_failed: {str(exc)}"


def _auto_save_input(state: NetworkAgentState, skill_spec: dict):
    """Auto-save input artifact if skill.yaml says so."""
    artifact_cfg = skill_spec.get("artifact", {})
    if not artifact_cfg.get("auto_save_input"):
        return

    source_config = state.payload.get("source_config", "")
    if not source_config:
        return

    ws_id = state.workspace_id or "default"
    try:
        from artifacts.store import save_artifact
        art = save_artifact(
            workspace_id=ws_id, content=source_config,
            artifact_type=artifact_cfg.get("input_type", "input_config"),
            title="Agent input", scope=artifact_cfg.get("scope", "run"),
            sensitivity=artifact_cfg.get("sensitivity", "sensitive"),
            run_id=state.request_id, module=state.active_module,
            skill=state.selected_skill, capability_id=state.context.get("capability_id", ""),
            source="agent_generated",
        )
        if art:
            state.context.setdefault("input_artifacts", []).append(art.artifact_id)
            _add_event(state, "artifact_saved", f"artifact:{art.artifact_id}", ws_id=ws_id,
                       status="success", summary=f"saved input: {art.title}")
    except Exception:
        pass


def _auto_save_output(state: NetworkAgentState, skill_spec: dict):
    """Auto-save output artifact if skill.yaml says so."""
    artifact_cfg = skill_spec.get("artifact", {})
    if not artifact_cfg.get("auto_save_output"):
        return

    result = state.skill_results or {}
    output_field = artifact_cfg.get("output_field", "")
    content = result.get(output_field, "")
    if not content or not isinstance(content, str):
        return

    ws_id = state.workspace_id or "default"
    try:
        from artifacts.store import save_artifact
        art = save_artifact(
            workspace_id=ws_id, content=content,
            artifact_type=artifact_cfg.get("output_type", "output_config"),
            title="Output", scope=artifact_cfg.get("scope", "run"),
            sensitivity=artifact_cfg.get("sensitivity", "sensitive"),
            run_id=state.request_id, module=state.active_module,
            skill=state.selected_skill, capability_id=state.context.get("capability_id", ""),
            source="module_output",
        )
        if art:
            state.context.setdefault("output_artifacts", []).append(art.artifact_id)
            _add_event(state, "artifact_saved", f"artifact:{art.artifact_id}", ws_id=ws_id,
                       status="success", summary=f"saved output: {art.title}")
    except Exception:
        pass


def _load_adapter(adapter_path: str, function_name: str) -> Callable:
    """Dynamically load an adapter function from path like 'skills/<name>/adapter.py'."""
    mod_path = adapter_path.replace(".py", "").replace("/", ".")
    mod = importlib.import_module(mod_path)
    return getattr(mod, function_name)


def _add_event(state, event_type, name, ws_id="default", status="started",
               duration_ms=0.0, summary="", metadata=None):
    state.trace_events.append({
        "event_id": f"{name}_{event_type}_{len(state.trace_events)}",
        "trace_id": state.trace_id or "",
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
