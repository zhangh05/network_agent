# registry/loader.py
"""Registry loader — reads module/skill registries and projects the catalog.

v3.9.4 hard cut: business capabilities live in
``agent.capabilities.catalog``.  This loader may project that catalog into
legacy-shaped ``ModuleSpec`` / ``SkillSpec`` / ``CapabilitySpec`` records for
the registry API, but it must not import or depend on a CapabilityRegistry.
"""

import json
import logging
import os
import yaml
from pathlib import Path
from typing import Optional

from registry.schemas import ModuleSpec, SkillSpec, CapabilitySpec

ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "modules"
SKILLS_DIR = ROOT / "skills"
logger = logging.getLogger(__name__)

# Cache
_cache = {"modules": None, "skills": None, "capabilities": None}


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
        memory_allowed_types=mem.get("allowed_memory_types", []),
        trace_enabled=trace.get("enabled", True),
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

    # SKILLS_DIR is optional — project root may not have a skills/ folder.
    # If absent, fall back to an empty skill set rather than leaking the
    # absolute path through diagnostics.
    if not SKILLS_DIR.is_dir():
        _cache["skills"] = []
        return _cache["skills"]

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
        trace_record_capability_call=data.get("trace", {}).get("record_capability_call", True),
        trace_record_module_call=data.get("trace", {}).get("record_module_call", True),
        memory_write_run_summary=data.get("memory", {}).get("write_run_summary", True),
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
                },
            ))

    return result


def _business_capabilities() -> list[dict]:
    try:
        from agent.capabilities import catalog
        return catalog.list_all()
    except Exception:
        return []


def _project_runtime_modules() -> list:
    caps = _business_capabilities()
    if not caps:
        return []
    by_module: dict[str, list[dict]] = {}
    for cap in caps:
        for module_id in cap.get("module_ids") or ():
            by_module.setdefault(str(module_id), []).append(cap)

    modules = []
    for module_id, module_caps in sorted(by_module.items()):
        enabled = any(c.get("status") == "enabled" for c in module_caps)
        first = module_caps[0]
        risk = _highest_catalog_risk(module_caps)
        modules.append(ModuleSpec(
            module_name=module_id,
            display_name=_title_from_id(module_id),
            description=first.get("description", ""),
            category=first.get("capability_id", ""),
            status="enabled" if enabled else "planned",
            maturity="beta_ready" if enabled else "planned",
            module_path=_runtime_module_path(module_id),
            api_base=f"/api/modules/{module_id}",
            primary_endpoint="runtime",
            health_endpoint=f"/api/modules/{module_id}/health",
            has_ui=enabled,
            ui_route=f"/capabilities/{first.get('capability_id', module_id)}",
            requires_llm=module_id == "runtime",
            llm_allowed=module_id == "runtime",
            deterministic=module_id != "runtime",
            can_generate_deployable=_catalog_requires_review(module_caps),
            deployable_output_field="deployable_config" if _catalog_requires_review(module_caps) else "",
            risk_level=risk,
            can_affect_network=module_id in {"cmdb", "device", "runtime"},
            requires_manual_review=_catalog_requires_review(module_caps),
            high_risk_output_possible=risk in {"high", "critical", "forbidden"},
            outputs=[],
            artifact_output_policy="sensitive_artifact_allowed" if _catalog_requires_review(module_caps) else "none",
            trace_enabled=True,
            trace_policy="sanitized_metadata_only",
            no_module_private_llm=module_id != "runtime",
        ))
    return modules


def _project_runtime_skills() -> list:
    """Project business capabilities as skill specs for registry views."""
    skills = []
    for cap in _business_capabilities():
        cap_id = str(cap.get("capability_id") or "")
        if not cap_id:
            continue
        module_ids = list(cap.get("module_ids") or [])
        tool_ids = list(cap.get("recommended_tool_ids") or [])
        skills.append(SkillSpec(
            skill_name=cap_id,
            display_name=str(cap.get("display_name") or _title_from_id(cap_id)),
            description=str(cap.get("description") or ""),
            category=cap_id,
            status=str(cap.get("status") or "planned"),
            skill_type="prompt_skill",
            module=module_ids[0] if module_ids else "",
            module_api="runtime",
            adapter_path="",
            entrypoint_type="business_capability",
            entrypoint_function="",
            capabilities=[{
                "capability_id": cap_id,
                "intent": cap_id,
                "recommended_tool_ids": tool_ids,
                "description": cap.get("description", ""),
                "risk_level": _highest_tool_id_risk(tool_ids),
            }],
            calls_module=True,
            calls_llm=False,
            calls_http_self=False,
            adapter_required=False,
            requires_adapter=False,
            red_lines=_skill_red_lines(list(cap.get("safety_notes") or [])),
            trace_record_capability_call=True,
            trace_record_module_call=True,
            memory_write_run_summary=True,
        ))
    return skills


def _project_runtime_capabilities() -> list:
    """Project business capability catalog as CapabilitySpec records."""
    caps = []
    for cap in _business_capabilities():
        cap_id = str(cap.get("capability_id") or "")
        if not cap_id:
            continue
        tool_ids = list(cap.get("recommended_tool_ids") or [])
        module_ids = list(cap.get("module_ids") or [])
        risk = _highest_tool_id_risk(tool_ids)
        caps.append(CapabilitySpec(
            capability_id=cap_id,
            intent=cap_id,
            module=module_ids[0] if module_ids else "",
            skill=cap_id,
            status=str(cap.get("status") or "planned"),
            description=str(cap.get("description") or ""),
            category=cap_id,
            risk_level=risk,
            can_generate_deployable=_notes_require_review(cap.get("safety_notes") or ()),
            requires_verification=_notes_require_review(cap.get("safety_notes") or ()),
            requires_manual_review_if_any=_notes_require_review(cap.get("safety_notes") or ()),
            llm_allowed=False,
            artifact_full_input_allowed=False,
            artifact_sensitivity="internal",
            ui_module_route=f"/capabilities/{cap_id}",
            ui_action_label=str(cap.get("display_name") or _title_from_id(cap_id)),
            required_module=module_ids[0] if module_ids else "",
            required_skill=cap_id,
            input_schema={"recommended_tool_ids": tool_ids},
            output_schema={},
            policies={
                "llm_allowed": False,
                "recommended_tool_ids": tool_ids,
                "prompt_hints": list(cap.get("prompt_hints") or []),
                "safety_notes": list(cap.get("safety_notes") or []),
            },
        ))
    return caps


def _highest_tool_id_risk(tool_ids: list[str]) -> str:
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3, "forbidden": 4}
    highest = "low"
    try:
        from core.tools.manifest_registry import get_manifest
    except Exception:
        get_manifest = None
    for tool_id in tool_ids or []:
        manifest = get_manifest(tool_id) if get_manifest else None
        risk = getattr(manifest, "risk_level", "low") if manifest else "low"
        if rank.get(risk, 0) > rank.get(highest, 0):
            highest = risk
    return highest


def _highest_catalog_risk(caps: list[dict]) -> str:
    tool_ids: list[str] = []
    for cap in caps:
        tool_ids.extend(list(cap.get("recommended_tool_ids") or []))
    return _highest_tool_id_risk(tool_ids)


def _notes_require_review(notes) -> bool:
    text = " ".join(str(n).lower() for n in notes or ())
    return any(word in text for word in ("approval", "verify", "review", "复核", "确认"))


def _catalog_requires_review(caps: list[dict]) -> bool:
    return any(_notes_require_review(c.get("safety_notes") or ()) for c in caps)


def _title_from_id(value: str) -> str:
    return str(value or "").replace("_", " ").replace(".", " ").title()


def _runtime_module_path(module_id: str) -> str:
    """Resolve logical capability modules to their actual code owners."""
    return {
        "memory": "workspace",
        "runtime": "core/runtime_engine",
        "workspace": "workspace",
    }.get(module_id, f"agent/modules/{module_id}")


def _skill_red_lines(safety_rules: list) -> list:
    out = ["do_not_call_llm", "do_not_hide_manual_review"]
    for rule in safety_rules or []:
        if rule not in out:
            out.append(rule)
    return out


def _skill_adapter_path(skill_id: str) -> str:
    return {
        "config_translation": "modules/config_translation/backend/service.py",
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
    """Force reload all registries and derived catalog snapshots."""
    global _cache
    _cache = {"modules": None, "skills": None, "capabilities": None}
    try:
        from core.tools.catalog_snapshot import reset_catalog_snapshot_cache
        reset_catalog_snapshot_cache()
    except Exception:
        logger.debug("registry reload: catalog snapshot reset skipped", exc_info=True)
        pass
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
