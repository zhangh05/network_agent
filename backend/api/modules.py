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
    agent.capabilities.catalog. Returns a frontend-compatible projection
    of the business capabilities.

    v3.9.4: planned capabilities are listed for UI only; they have
    no tool refs and are NEVER callable. No legacy tool names are
    returned.
    """
    from agent.capabilities import catalog as _catalog

    def _project(cap: dict) -> dict:
        # v3.9.4: risk_level is the maximum of any recommended tool's
        # manifest risk level. Tools with no recommendation = low.
        risk = "low"
        try:
            from tool_runtime.manifest_registry import get_manifest
            for tid in cap["recommended_tool_ids"]:
                m = get_manifest(tid)
                if m is not None and m.risk_level == "high":
                    risk = "high"
                    break
                if m is not None and m.risk_level == "medium" and risk == "low":
                    risk = "medium"
        except Exception:
            pass
        return {
            "capability_id": cap["capability_id"],
            "enabled": cap["status"] == "enabled",
            "status": cap["status"],
            "description": cap["description"],
            "category": _cap_category(cap["capability_id"]),
            "intent": cap["capability_id"].replace("_", "."),
            "module": cap["module_ids"][0] if cap["module_ids"] else "",
            "tool_ids": list(cap["recommended_tool_ids"]),
            "risk_level": risk,
            "can_generate_deployable": any(
                "deployable" in n.lower() for n in cap["safety_notes"]
            ),
            "requires_verification": any(
                "approval" in n.lower() or "verify" in n.lower()
                for n in cap["safety_notes"]
            ),
            "requires_human_review": any(
                "approval" in n.lower() or "verify" in n.lower()
                for n in cap["safety_notes"]
            ),
        }

    return jsonify({
        "capabilities": [_project(c) for c in _catalog.list_all()],
        "enabled": [c["capability_id"] for c in _catalog.list_enabled()],
    })


def _cap_category(capability_id: str) -> str:
    _map = {
        "config_translation": "translation",
        "knowledge": "knowledge",
        "artifact_management": "artifact",
        "review_flow": "review",
        "topology": "topology",
        "inspection": "inspection",
        "cmdb": "cmdb",
        "network_device": "network",
        "pcap_analysis": "network",
        "coding": "coding",
        "browser": "browser",
    }
    return _map.get(capability_id, capability_id)
