# registry/loader.py
"""Registry loader — reads module/skill registries and generates capabilities."""

import json
import os
import yaml
from pathlib import Path
from typing import Optional

from registry.schemas import ModuleSpec, SkillSpec, CapabilitySpec

ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "modules"
SKILLS_DIR = ROOT / "skills"

# Cache
_cache = {"modules": None, "skills": None, "capabilities": None}

_COMPAT_CAPABILITY_ALIASES = {
    "config.translate": "config_translation",
    "config.review": "review",
    "knowledge.search": "knowledge",
    "topology.draw": "topology",
    "inspection.analyze": "inspection",
}


def _read_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) or {}
    except Exception:
        return {}


# ═══════════════════════════════════
# MODULE LOADING
# ═══════════════════════════════════

def load_module_registry(reload: bool = False) -> list:
    global _cache
    if not reload and _cache["modules"] is not None:
        return _cache["modules"]

    projected = _project_runtime_modules()
    if projected:
        _cache["modules"] = projected
        return projected

    modules = {}

    # 1. Read registry.json (master list)
    reg = _read_json(MODULES_DIR / "registry.json")
    for entry in reg.get("modules", []):
        name = entry.get("module_name", "")
        if not name:
            continue
        modules[name] = _parse_module_json(entry)

    # 2. Override/merge with module.yaml (authoritative per-module)
    for mod_dir in MODULES_DIR.iterdir():
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        myaml = mod_dir / "module.yaml"
        if not myaml.is_file():
            continue
        data = _read_yaml(myaml)
        name = data.get("module_name", mod_dir.name)
        spec = _parse_module_yaml(data, name, str(mod_dir))
        if name in modules:
            _merge_module_spec(modules[name], spec)
        else:
            modules[name] = spec

    result = list(modules.values())
    _cache["modules"] = result
    return result


def _parse_module_json(entry: dict) -> ModuleSpec:
    return ModuleSpec(
        module_name=entry.get("module_name", ""),
        display_name=entry.get("display_name", ""),
        description=entry.get("description", ""),
        status=entry.get("status", "planned"),
        maturity=entry.get("maturity", "planned"),
        module_path=entry.get("module_path", ""),
        api_base=entry.get("api_base", f"/api/modules/{entry.get('module_name', '')}"),
        primary_endpoint=entry.get("primary_api", entry.get("primary_endpoint", "")),
        has_ui=entry.get("has_ui", False),
        ui_route=entry.get("ui_route", ""),
        ui_owned_by=entry.get("ui_owned_by", "network_agent_unified_ui"),
        has_own_retired_frontend=entry.get("has_own_retired_frontend", False),
        requires_llm=entry.get("llm_dependency", entry.get("requires_llm", False)),
    )


def _parse_module_yaml(data: dict, name: str, path: str) -> ModuleSpec:
    be = data.get("backend", {})
    ui = data.get("ui", {})
    rt = data.get("runtime", {})
    risk = data.get("risk", {})
    art = data.get("artifacts", {})
    mem = data.get("memory", {})
    trace = data.get("trace", {})
    sec = data.get("security", {})

    inputs = [
        {"name": i.get("name", ""), "type": i.get("type", ""),
         "required": i.get("required"), "sensitivity": i.get("sensitivity")}
        for i in data.get("inputs", [])
    ]
    outputs = [
        {"name": o.get("name", ""), "type": o.get("type", ""),
         "sensitivity": o.get("sensitivity")}
        for o in data.get("outputs", [])
    ]

    return ModuleSpec(
        module_name=data.get("module_name", name),
        display_name=data.get("display_name", name),
        description=data.get("description", ""),
        category=data.get("category", ""),
        status=data.get("status", "planned"),
        maturity=data.get("maturity", "planned"),
        module_path=data.get("module_path", path),
        api_base=be.get("api_base", f"/api/modules/{name}"),
        primary_endpoint=be.get("primary_endpoint", ""),
        health_endpoint=be.get("health_endpoint", ""),
        has_ui=ui.get("has_ui", False),
        ui_route=ui.get("ui_route", ""),
        ui_owned_by=ui.get("ui_owned_by", "network_agent_unified_ui"),
        has_own_retired_frontend=ui.get("has_own_retired_frontend", False),
        requires_llm=rt.get("requires_llm", False),
        llm_allowed=rt.get("llm_allowed", False),
        deterministic=rt.get("deterministic", True),
        can_generate_deployable=rt.get("can_generate_deployable", False),
        deployable_output_field=rt.get("deployable_output_field", ""),
        risk_level=risk.get("risk_level", "low"),
        can_affect_network=risk.get("can_affect_network", False),
        requires_manual_review=risk.get("requires_manual_review", False),
        high_risk_output_possible=risk.get("high_risk_output_possible", False),
        inputs=inputs, outputs=outputs,
        artifact_input_policy=art.get("input_policy", "none"),
        artifact_output_policy=art.get("output_policy", "none"),
        artifact_report_policy=art.get("report_policy", "none"),
        memory_write_run_summary=mem.get("write_run_summary", False),
        memory_write_full_input=mem.get("write_full_input", False),
        memory_write_full_output=mem.get("write_full_output", False),
        memory_allowed_types=mem.get("allowed_memory_types", []),
        trace_enabled=trace.get("enabled", True),
        trace_full_input=trace.get("record_full_input", False),
        trace_full_output=trace.get("record_full_output", False),
        trace_record_counts=trace.get("record_counts", True),
        trace_policy=trace.get("record_policy", "sanitized_metadata_only"),
        no_external_repo_dependency=sec.get("no_external_repo_dependency", True),
        no_module_private_llm=sec.get("no_module_private_llm", True),
        no_retired_frontend=sec.get("no_retired_frontend", True),
        no_retired_graphagent=sec.get("no_retired_graphagent", True),
        no_api_key_storage=sec.get("no_api_key_storage", True),
    )


def _merge_module_spec(base: ModuleSpec, override: ModuleSpec):
    """Merge override into base (override wins when set)."""
    for field_name in base.__dataclass_fields__:
        override_val = getattr(override, field_name)
        default_val = base.__dataclass_fields__[field_name].default
        # Only override if non-default
        if override_val != default_val and override_val is not None:
            setattr(base, field_name, override_val)


# ═══════════════════════════════════
# SKILL LOADING
# ═══════════════════════════════════

def load_skill_registry(reload: bool = False) -> list:
    global _cache
    if not reload and _cache["skills"] is not None:
        return _cache["skills"]

    projected = _project_runtime_skills()
    if projected:
        _cache["skills"] = projected
        return projected

    skills = {}

    # 1. Read registry.json
    reg = _read_json(SKILLS_DIR / "registry.json")
    for entry in reg.get("skills", []):
        name = entry.get("skill_name", "")
        if not name:
            continue
        skills[name] = _parse_skill_json(entry)

    # 2. Override with skill.yaml
    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        syaml = skill_dir / "skill.yaml"
        if not syaml.is_file():
            continue
        data = _read_yaml(syaml)
        name = data.get("skill_name", skill_dir.name)
        spec = _parse_skill_yaml(data, name, str(skill_dir))
        if name in skills:
            _merge_skill_spec(skills[name], spec)
        else:
            skills[name] = spec

    result = list(skills.values())
    _cache["skills"] = result
    return result


def _parse_skill_json(entry: dict) -> SkillSpec:
    return SkillSpec(
        skill_name=entry.get("skill_name", ""),
        display_name=entry.get("display_name", ""),
        description=entry.get("description", ""),
        status=entry.get("status", "planned"),
        skill_type=entry.get("skill_type", "python_adapter"),
        module=entry.get("module", ""),
        module_api=entry.get("module_api", ""),
        adapter_path=entry.get("adapter_path", ""),
    )


def _parse_skill_yaml(data: dict, name: str, path: str) -> SkillSpec:
    return SkillSpec(
        skill_name=data.get("skill_name", name),
        display_name=data.get("display_name", name),
        description=data.get("description", ""),
        category=data.get("category", ""),
        status=data.get("status", "planned"),
        skill_type=data.get("skill_type", "python_adapter"),
        module=data.get("module", ""),
        module_api=data.get("module_api", ""),
        adapter_path=data.get("adapter_path", f"{path}/adapter.py"),
        entrypoint_type=data.get("entrypoint", {}).get("type", "python"),
        entrypoint_function=data.get("entrypoint", {}).get("function", ""),
        capabilities=data.get("capabilities", []),
        calls_module=data.get("execution", {}).get("calls_module", True),
        calls_llm=data.get("execution", {}).get("calls_llm", False),
        calls_http_self=data.get("execution", {}).get("calls_http_self", False),
        red_lines=data.get("red_lines", []),
        trace_record_skill_call=data.get("trace", {}).get("record_skill_call", True),
        trace_record_module_call=data.get("trace", {}).get("record_module_call", True),
        trace_full_input=data.get("trace", {}).get("record_full_input", False),
        trace_full_output=data.get("trace", {}).get("record_full_output", False),
        memory_write_run_summary=data.get("memory", {}).get("write_run_summary", True),
        memory_full_input=data.get("memory", {}).get("write_full_input", False),
        memory_full_output=data.get("memory", {}).get("write_full_output", False),
        test_contracts=data.get("tests", {}).get("required_contract_tests", []),
        artifact=data.get("artifact", {}),
        compose=data.get("compose", {}),
    )


def _merge_skill_spec(base: SkillSpec, override: SkillSpec):
    for field_name in base.__dataclass_fields__:
        override_val = getattr(override, field_name)
        default_val = base.__dataclass_fields__[field_name].default
        if override_val != default_val and override_val is not None:
            setattr(base, field_name, override_val)


# ═══════════════════════════════════
# CAPABILITY LOADING
# ═══════════════════════════════════

def load_capabilities(reload: bool = False) -> list:
    global _cache
    if not reload and _cache["capabilities"] is not None:
        return _cache["capabilities"]

    projected = _project_runtime_capabilities()
    if projected:
        _cache["capabilities"] = projected
        return projected

    modules = load_module_registry()
    skills = load_skill_registry()
    caps = _generate_capabilities(modules, skills)
    _cache["capabilities"] = caps
    return caps


def _generate_capabilities(modules: list, skills: list) -> list:
    """Generate capabilities from module + skill registries."""
    mod_by_name = {m.module_name: m for m in modules}
    skill_by_name = {s.skill_name: s for s in skills}
    result = []

    for skill in skills:
        mod = mod_by_name.get(skill.module)
        if not mod:
            continue

        for cap_entry in skill.capabilities:
            cap_id = cap_entry.get("capability_id", "")
            intent = cap_entry.get("intent", "")
            risk = cap_entry.get("risk_level", mod.risk_level)

            result.append(CapabilitySpec(
                capability_id=cap_id,
                intent=intent or cap_id.replace(".", "_"),
                module=mod.module_name,
                skill=skill.skill_name,
                status="enabled" if (mod.is_enabled() and skill.is_enabled()) else "planned",
                description=cap_entry.get("description", skill.description),
                category=skill.category or mod.category,
                risk_level=risk,
                can_generate_deployable=mod.can_generate_deployable,
                requires_verification=mod.requires_manual_review,
                requires_manual_review_if_any=mod.requires_manual_review,
                llm_allowed=mod.llm_allowed,
                memory_full_input=mod.memory_write_full_input,
                memory_full_output=mod.memory_write_full_output,
                trace_full_input=mod.trace_full_input,
                trace_full_output=mod.trace_full_output,
                artifact_full_input_allowed=(mod.artifact_input_policy == "sensitive_artifact_only"),
                artifact_sensitivity="sensitive" if mod.can_generate_deployable else "internal",
                ui_module_route=mod.ui_route,
                ui_action_label=mod.display_name,
                required_module=mod.module_name,
                required_skill=skill.skill_name,
                input_schema={i["name"]: {"type": i["type"]} for i in mod.inputs},
                output_schema={o["name"]: {"type": o["type"]} for o in mod.outputs},
                policies={
                    "llm_allowed": mod.llm_allowed,
                    "memory_full_input": mod.memory_write_full_input,
                    "trace_full_input": mod.trace_full_input,
                },
            ))

    return result


def _runtime_capability_registry():
    try:
        from agent.capabilities import get_default_capability_registry
        return get_default_capability_registry()
    except Exception:
        return None


def _project_runtime_modules() -> list:
    reg = _runtime_capability_registry()
    if reg is None:
        return []
    modules = []
    for cap in reg.list_all():
        m = cap.module
        safety = cap.safety
        modules.append(ModuleSpec(
            module_name=m.module_id,
            display_name=cap.name,
            description=m.description or cap.description,
            category=cap.capability_id,
            status=m.status,
            maturity="beta_ready" if m.status == "enabled" else "planned",
            module_path=f"agent/modules/{m.module_id}",
            api_base=_module_api_base(m.module_id),
            primary_endpoint=_module_primary_endpoint(m.module_id, m.operations),
            health_endpoint=f"/api/modules/{m.module_id}/health",
            has_ui=m.status == "enabled",
            ui_route=_module_ui_route(m.module_id, cap.capability_id),
            requires_llm=False,
            llm_allowed=False,
            deterministic=True,
            can_generate_deployable=safety.produces_deployable_config,
            deployable_output_field="deployable_config" if safety.produces_deployable_config else "",
            risk_level=_highest_tool_risk(cap.tools),
            can_affect_network=safety.real_device_access or safety.allows_config_push,
            requires_manual_review=safety.requires_human_review,
            high_risk_output_possible=safety.produces_deployable_config,
            outputs=[
                {"name": o.output_id, "type": o.output_type, "sensitivity": o.sensitivity}
                for o in cap.outputs
            ],
            artifact_output_policy="sensitive_artifact_allowed" if cap.outputs else "none",
            trace_enabled=True,
            trace_policy="sanitized_metadata_only",
        ))
    return modules


def _project_runtime_skills() -> list:
    reg = _runtime_capability_registry()
    if reg is None:
        return []
    skills = []
    for cap in reg.list_all():
        for sk in cap.skills:
            skills.append(SkillSpec(
                skill_name=sk.skill_id,
                display_name=cap.name,
                description=sk.prompt_summary or cap.description,
                category=cap.capability_id,
                status=sk.status,
                skill_type=_skill_type(sk.skill_id),
                module=cap.module.module_id,
                module_api=_module_primary_endpoint(cap.module.module_id, cap.module.operations),
                adapter_path=_skill_adapter_path(sk.skill_id),
                entrypoint_type="python" if _skill_adapter_path(sk.skill_id) else "runtime_capability",
                entrypoint_function=_skill_entrypoint(sk.skill_id),
                capabilities=[{
                    "capability_id": cap.capability_id,
                    "intent": sk.skill_id,
                    "function": _skill_entrypoint(sk.skill_id),
                    "description": cap.description,
                    "risk_level": _highest_tool_risk(cap.tools),
                }],
                calls_module=True,
                calls_llm=False,
                calls_http_self=False,
                adapter_required=bool(_skill_adapter_path(sk.skill_id)),
                requires_adapter=bool(_skill_adapter_path(sk.skill_id)),
                red_lines=_skill_red_lines(sk.safety_rules),
                trace_record_skill_call=True,
                trace_record_module_call=True,
                trace_full_input=False,
                trace_full_output=False,
                memory_write_run_summary=True,
                memory_full_input=False,
                memory_full_output=False,
            ))
    return skills


def _project_runtime_capabilities() -> list:
    reg = _runtime_capability_registry()
    if reg is None:
        return []
    caps = []
    for cap in reg.list_all():
        sk = cap.skills[0] if cap.skills else None
        risk = _highest_tool_risk(cap.tools)
        caps.append(CapabilitySpec(
            capability_id=cap.capability_id,
            intent=_capability_intent(cap.capability_id, sk.skill_id if sk else cap.capability_id),
            module=cap.module.module_id,
            skill=sk.skill_id if sk else "",
            status=cap.status,
            description=cap.description,
            category=cap.capability_id,
            risk_level=risk,
            can_generate_deployable=cap.safety.produces_deployable_config,
            requires_verification=cap.safety.requires_human_review,
            requires_manual_review_if_any=cap.safety.requires_human_review,
            llm_allowed=False,
            memory_full_input=False,
            memory_full_output=False,
            trace_full_input=False,
            trace_full_output=False,
            artifact_full_input_allowed=False,
            artifact_sensitivity=_highest_output_sensitivity(cap.outputs),
            ui_module_route=f"/capabilities/{cap.capability_id}",
            ui_action_label=cap.name,
            required_module=cap.module.module_id,
            required_skill=sk.skill_id if sk else "",
            input_schema={
                t.tool_id: t.input_schema
                for t in cap.tools
                if t.status == "enabled"
            },
            output_schema={
                o.output_id: {"type": o.output_type, "sensitivity": o.sensitivity}
                for o in cap.outputs
            },
            policies={
                "llm_allowed": False,
                "real_device_access": cap.safety.real_device_access,
                "allows_config_push": cap.safety.allows_config_push,
                "may_fabricate_sources": cap.safety.may_fabricate_sources,
            },
        ))
    return caps


def _highest_tool_risk(tools: list) -> str:
    rank = {"low": 0, "medium": 1, "high": 2, "forbidden": 3}
    highest = "low"
    for tool in tools or []:
        risk = getattr(tool, "risk_level", "low")
        if rank.get(risk, 0) > rank.get(highest, 0):
            highest = risk
    return highest


def _highest_output_sensitivity(outputs: list) -> str:
    rank = {"public": 0, "internal": 1, "sensitive": 2, "secret": 3}
    highest = "internal"
    for output in outputs or []:
        sensitivity = getattr(output, "sensitivity", "internal")
        if rank.get(sensitivity, 1) > rank.get(highest, 1):
            highest = sensitivity
    return highest


def _capability_intent(capability_id: str, fallback: str) -> str:
    return {
        "config_translation": "translate_config",
        "knowledge": "knowledge_query",
        "artifact": "artifact_management",
        "review": "context_qa",
        "topology": "topology_draw",
        "inspection": "inspection_analyze",
        "cmdb": "cmdb_query",
    }.get(capability_id, fallback)


def _module_api_base(module_id: str) -> str:
    return {
        "config_translation": "/api/modules/config-translation",
        "knowledge": "/api/modules/knowledge",
    }.get(module_id, f"/api/modules/{module_id}")


def _module_primary_endpoint(module_id: str, operations: list) -> str:
    return {
        "config_translation": "/api/modules/config-translation/translate",
        "knowledge": "/api/modules/knowledge/query",
    }.get(module_id, operations[0] if operations else "runtime")


def _module_ui_route(module_id: str, capability_id: str) -> str:
    return {
        "config_translation": "/modules/translate",
        "knowledge": "/modules/knowledge",
    }.get(module_id, f"/capabilities/{capability_id}")


def _skill_red_lines(safety_rules: list) -> list:
    out = ["do_not_call_llm", "do_not_hide_manual_review"]
    for rule in safety_rules or []:
        if rule not in out:
            out.append(rule)
    return out


def _skill_adapter_path(skill_id: str) -> str:
    return {
        "config_translation": "skills/config_translation/adapter.py",
    }.get(skill_id, "")


def _skill_entrypoint(skill_id: str) -> str:
    return {
        "config_translation": "translate",
    }.get(skill_id, "")


def _skill_type(skill_id: str) -> str:
    return "python_adapter" if _skill_adapter_path(skill_id) else "prompt_skill"


# ═══════════════════════════════════
# CONVENIENCE ACCESSORS
# ═══════════════════════════════════

def get_module(name: str) -> Optional[ModuleSpec]:
    for m in load_module_registry():
        if m.module_name == name:
            return m
    return None


def get_skill(name: str) -> Optional[SkillSpec]:
    for s in load_skill_registry():
        if s.skill_name == name:
            return s
    return None


def get_capability(capability_id: str) -> Optional[CapabilitySpec]:
    capability_id = _COMPAT_CAPABILITY_ALIASES.get(capability_id, capability_id)
    for c in load_capabilities():
        if c.capability_id == capability_id:
            return c
    return None


def get_enabled_modules() -> list:
    return [m for m in load_module_registry() if m.is_enabled()]


def get_planned_modules() -> list:
    return [m for m in load_module_registry() if m.is_planned()]


def get_enabled_skills() -> list:
    return [s for s in load_skill_registry() if s.is_enabled()]


def get_planned_skills() -> list:
    return [s for s in load_skill_registry() if s.is_planned()]


def get_enabled_capabilities() -> list:
    return [c for c in load_capabilities() if c.is_enabled()]


def reload_all():
    """Force reload all registries."""
    global _cache
    _cache = {"modules": None, "skills": None, "capabilities": None}
    return {
        "modules": load_module_registry(reload=True),
        "skills": load_skill_registry(reload=True),
        "capabilities": load_capabilities(reload=True),
    }


def get_registry_status() -> dict:
    """Get full registry status summary."""
    mods = load_module_registry()
    skills = load_skill_registry()
    caps = load_capabilities()

    return {
        "module_count": len(mods),
        "skill_count": len(skills),
        "capability_count": len(caps),
        "enabled_modules": [m.module_name for m in mods if m.is_enabled()],
        "enabled_skills": [s.skill_name for s in skills if s.is_enabled()],
        "enabled_capabilities": [c.capability_id for c in caps if c.is_enabled()],
        "planned_modules": [m.module_name for m in mods if m.is_planned()],
        "planned_skills": [s.skill_name for s in skills if s.is_planned()],
        "modules": [m.as_dict() for m in mods],
        "skills": [s.as_dict() for s in skills],
        "capabilities": [c.as_dict() for c in caps],
    }
