# backend/api/skills.py
"""Skills API — now backed by CapabilityRegistry (v3.3)."""

from flask import jsonify


def handle_skills():
    from agent.capabilities.builtin import get_default_capability_registry
    cap_reg = get_default_capability_registry()
    return jsonify({
        "skills": [
            {
                "skill_name": m.capability_id,
                "display_name": m.name,
                "status": m.status,
                "module": m.module.module_id,
                "capabilities": [t.tool_id for t in m.tools],
                "enabled": m.status == "enabled",
                "planned": m.status == "planned",
            }
            for m in cap_reg.list_all()
        ]
    })
