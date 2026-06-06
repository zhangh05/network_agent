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
        return jsonify({"error": f"module {module_name} not found"}), 404
    return jsonify(m.as_dict())


def handle_registry_status():
    return jsonify(get_registry_status())


def handle_capabilities():
    from registry.loader import load_capabilities
    caps = load_capabilities()
    return jsonify({
        "capabilities": [c.as_dict() for c in caps],
        "enabled": [c.capability_id for c in caps if c.is_enabled()],
    })
