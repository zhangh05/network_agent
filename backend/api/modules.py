# backend/api/modules.py
"""Module API — data from registry loader."""

from flask import jsonify
from registry.loader import load_module_registry, get_module, get_registry_status


def handle_modules():
    mods = load_module_registry()
    return jsonify({
        "modules": [
            {
                "module_name": m.module_name,
                "display_name": m.display_name,
                "status": m.status,
                "maturity": m.maturity,
                "category": m.category,
                "ui_route": m.ui_route,
                "api_base": m.api_base,
                "enabled": m.is_enabled(),
                "planned": m.is_planned(),
                "risk_level": m.risk_level,
            }
            for m in mods
        ]
    })


def handle_module_status(module_name):
    m = get_module(module_name)
    if not m:
        return jsonify({"ok": False, "error": "MODULE_NOT_FOUND", "message": f"module {module_name} not found", "status": 404}), 404
    return jsonify({"ok": True, "data": m.as_dict()})


def handle_registry_status():
    return jsonify(get_registry_status())


def handle_capabilities():
    """GET /api/capabilities — The single source of truth is
    agent.capabilities.CapabilityRegistry. Returns a frontend-compatible
    projection of the 7 capabilities (4 enabled, 3 planned).

    Planned capabilities are listed but NEVER callable.
    """
    from agent.capabilities.builtin import get_default_capability_registry

    reg = get_default_capability_registry()
    manifests = reg.list_all()

    def _project(m) -> dict:
        """Project CapabilityManifest → frontend-expected wire shape."""
        has_skills = bool(m.skills)
        first_skill = m.skills[0] if has_skills else None
        return {
            "capability_id": m.capability_id,
            "enabled": m.status == "enabled",
            "status": m.status,
            "description": m.description,
            "category": _cap_category(m.capability_id),
            "intent": m.capability_id.replace("_", "."),
            "module": m.module.module_id if m.module else "",
            "skill": first_skill.skill_id if first_skill else "",
            "risk_level": m.tools[0].risk_level if m.tools else "low",
            "can_generate_deployable": m.safety.produces_deployable_config if m.safety else False,
            "requires_verification": m.safety.requires_human_review if m.safety else False,
            "requires_human_review": m.safety.requires_human_review if m.safety else False,
        }

    projected = [_project(m) for m in manifests]
    return jsonify({
        "capabilities": projected,
        "enabled": [m.capability_id for m in manifests if m.status == "enabled"],
    })


def _cap_category(capability_id: str) -> str:
    _map = {
        "config_translation": "translation",
        "knowledge": "knowledge",
        "artifact": "artifact",
        "review": "review",
        "topology": "topology",
        "inspection": "inspection",
        "cmdb": "cmdb",
    }
    return _map.get(capability_id, capability_id)
