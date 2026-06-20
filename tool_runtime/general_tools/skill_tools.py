"""Skill tool handlers — capability-first implementation.

All handlers delegate to agent.runtime.skill_runtime.
Skills are CapabilityPackage manifests, not filesystem prompt files.
"""
from tool_runtime.general_tools.shared import *

from agent.runtime.skill_runtime.registry import (
    list_skill_manifests,
    get_skill_manifest,
    search_skill_manifests,
)
from agent.runtime.skill_runtime.loader import load_skill
from agent.runtime.skill_runtime.session import skill_session_record


def handle_skill_list(inv: ToolInvocation) -> dict:
    """List skills as capability manifests."""
    try:
        manifests = list_skill_manifests()
        results = [
            {
                "skill_id": m.skill_id,
                "display_name": m.display_name,
                "description": m.description,
                "status": m.status,
                "capability_ids": list(m.capability_ids),
                "module_ids": list(m.module_ids),
                "tool_ids": list(m.tool_ids),
                "source": m.source,
            }
            for m in manifests
        ]
        return _ok(inv, "", {"results": results, "count": len(results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_skill_request_load(inv: ToolInvocation) -> dict:
    """Request loading a skill — delegates to handle_skill_load."""
    return handle_skill_load(inv)


def handle_skill_load(inv: ToolInvocation) -> dict:
    """Load a skill by ID and return its capability contract.

    Returns capability_ids, module_ids, tool_ids, prompt_hints, safety_notes.
    Does NOT return skill_prompt or SKILL.md content.
    """
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    result = load_skill(skill_name)
    if not result.ok:
        return _error_inv(inv, result.message)

    record = skill_session_record(result)
    return _ok(inv, "", {
        "skill_id": result.skill_id,
        "status": result.status,
        "capability_ids": list(result.capability_ids),
        "module_ids": list(result.module_ids),
        "tool_ids": list(result.tool_ids),
        "prompt_hints": list(result.prompt_hints),
        "safety_notes": list(result.safety_notes),
        "message": result.message,
        "skill_record": record,
    })


def handle_skill_find(inv: ToolInvocation) -> dict:
    """Search for skills by keyword in capability manifests."""
    args = inv.arguments or {}
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10))

    if not query:
        return _error_inv(inv, "query is required")

    try:
        matches = search_skill_manifests(query, limit=limit)
        results = [
            {
                "skill_id": m.skill_id,
                "display_name": m.display_name,
                "description": m.description,
                "status": m.status,
                "capability_ids": list(m.capability_ids),
                "module_ids": list(m.module_ids),
                "tool_ids": list(m.tool_ids),
                "source": m.source,
            }
            for m in matches
        ]
        return _ok(inv, "", {"results": results, "count": len(results), "query": query})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_skill_create(inv: ToolInvocation) -> dict:
    """Skill creation is disabled. Define a CapabilityPackage instead."""
    return {
        "ok": False,
        "tool_id": inv.tool_id,
        "status": "blocked",
        "summary": "Skill creation is disabled; define CapabilityPackage instead.",
        "errors": ["skill_create_disabled"],
    }


def handle_skill_install(inv: ToolInvocation) -> dict:
    """Skill installation is disabled. External skills require reviewed CapabilityPackage."""
    return {
        "ok": False,
        "tool_id": inv.tool_id,
        "status": "blocked",
        "summary": "Skill installation is disabled; external skills require reviewed CapabilityPackage registration.",
        "errors": ["skill_install_disabled"],
    }


def handle_skill_inspect(inv: ToolInvocation) -> dict:
    """Return skill manifest details (not SKILL.md content)."""
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    manifest = get_skill_manifest(skill_name)
    if manifest is None:
        return _error_inv(inv, f"skill '{skill_name}' not found")

    return _ok(inv, "", {
        "skill_id": manifest.skill_id,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "status": manifest.status,
        "capability_ids": list(manifest.capability_ids),
        "module_ids": list(manifest.module_ids),
        "tool_ids": list(manifest.tool_ids),
        "prompt_hints": list(manifest.prompt_hints),
        "safety_notes": list(manifest.safety_notes),
        "output_kinds": list(manifest.output_kinds),
        "source": manifest.source,
    })


__all__ = [
    "handle_skill_list",
    "handle_skill_request_load",
    "handle_skill_load",
    "handle_skill_find",
    "handle_skill_create",
    "handle_skill_install",
    "handle_skill_inspect",
]
