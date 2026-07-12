# backend/api/skills.py
"""Skills API — backed by the business capability catalog (v3.9.4).

Single source of truth: `agent.capabilities.catalog`. The returned
``capabilities`` list contains canonical tool ids only (the current
set). Removed tool names are not emitted from this endpoint.
"""

from flask import jsonify

from agent.capabilities import catalog as _catalog


def handle_skills():
    return jsonify({
        "skills": [
            {
                "skill_name": cap["capability_id"],
                "display_name": cap["display_name"],
                "status": cap["status"],
                "module": cap["module_ids"][0]
                if cap["module_ids"] else None,
                "capabilities": list(cap["recommended_tool_ids"]),
                "enabled": cap["status"] == "enabled",
                "planned": cap["status"] == "planned",
            }
            for cap in _catalog.list_all()
        ]
    })
