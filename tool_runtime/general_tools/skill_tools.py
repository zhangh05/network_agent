"""Skill tool handlers — CapabilityPackage lookup.

Skills ARE CapabilityPackages. These handlers provide the skill.load /
skill.search / skill.list / skill.find / skill.inspect tool surface.
All logic reads CAPABILITY_PACKAGES directly from capability_routing/manifests.py.
"""

from agent.runtime.capability_routing.manifests import CAPABILITY_PACKAGES


# ── internal helpers (was agent/runtime/skill_runtime/) ──

def _pkg_as_dict(pkg) -> dict:
    """CapabilityPackage → dict (replaces SkillManifest mirror)."""
    return {
        "skill_id": pkg.capability_id,
        "display_name": pkg.display_name,
        "description": pkg.description,
        "status": "active",
        "capability_ids": (pkg.capability_id,),
        "module_ids": tuple(pkg.module_ids),
        "tool_ids": tuple(pkg.tool_ids),
        "prompt_hints": tuple(pkg.prompt_hints),
        "safety_notes": tuple(pkg.safety_notes),
        "output_kinds": tuple(pkg.output_kinds),
        "source": "capability_package",
    }


def _search_packages(query: str, limit: int = 10) -> list[dict]:
    """Keyword search in CAPABILITY_PACKAGES."""
    q = (query or "").lower().strip()
    if not q:
        return []
    matches = []
    for pkg in CAPABILITY_PACKAGES:
        haystack = " ".join([
            pkg.capability_id, pkg.display_name, pkg.description,
            " ".join(pkg.intent_keywords),
            " ".join(pkg.module_ids), " ".join(pkg.tool_ids),
        ]).lower()
        if q in haystack:
            matches.append(_pkg_as_dict(pkg))
    return matches[:max(1, min(limit, 20))]


# ── tool handlers ──

def handle_skill_list(inv: ToolInvocation) -> dict:
    """List all capability packages as 'skills'."""
    try:
        results = [_pkg_as_dict(p) for p in CAPABILITY_PACKAGES]
        return _ok(inv, "", {"results": results, "count": len(results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_skill_request_load(inv: ToolInvocation) -> dict:
    return handle_skill_load(inv)


def handle_skill_load(inv: ToolInvocation) -> dict:
    """Load a skill (CapabilityPackage lookup) by capability_id.

    Returns tool_ids, module_ids, prompt_hints — the LLM uses these
    to call tool.catalog.load or the actual business tools directly.
    """
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    # Direct lookup in CAPABILITY_PACKAGES by capability_id
    for pkg in CAPABILITY_PACKAGES:
        if pkg.capability_id == skill_name:
            return _ok(inv, "", {
                "skill_id": pkg.capability_id,
                "status": "active",
                "capability_ids": [pkg.capability_id],
                "module_ids": list(pkg.module_ids),
                "tool_ids": list(pkg.tool_ids),
                "prompt_hints": list(pkg.prompt_hints),
                "safety_notes": list(pkg.safety_notes),
                "message": "skill loaded as capability package",
                "skill_record": {
                    "skill_id": pkg.capability_id,
                    "status": "active",
                    "capability_ids": [pkg.capability_id],
                    "module_ids": list(pkg.module_ids),
                    "tool_ids": list(pkg.tool_ids),
                    "prompt_hints": list(pkg.prompt_hints),
                    "safety_notes": list(pkg.safety_notes),
                },
            })

    # Fuzzy match: try substring in capability_id or display_name
    lower = skill_name.lower()
    for pkg in CAPABILITY_PACKAGES:
        if lower in pkg.capability_id.lower() or lower in pkg.display_name.lower():
            return _ok(inv, "", {
                "skill_id": pkg.capability_id,
                "status": "active",
                "capability_ids": [pkg.capability_id],
                "module_ids": list(pkg.module_ids),
                "tool_ids": list(pkg.tool_ids),
                "prompt_hints": list(pkg.prompt_hints),
                "safety_notes": list(pkg.safety_notes),
                "message": "skill loaded as capability package (fuzzy match)",
                "skill_record": {
                    "skill_id": pkg.capability_id,
                    "status": "active",
                    "capability_ids": [pkg.capability_id],
                    "module_ids": list(pkg.module_ids),
                    "tool_ids": list(pkg.tool_ids),
                },
            })

    return _error_inv(inv, f"skill '{skill_name}' not found. Available: {[p.capability_id for p in CAPABILITY_PACKAGES]}")


def handle_skill_find(inv: ToolInvocation) -> dict:
    """Search skills (CapabilityPackages) by keyword."""
    args = inv.arguments or {}
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10))
    if not query:
        return _error_inv(inv, "query is required")
    try:
        results = _search_packages(query, limit=limit)
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
    return {
        "ok": False,
        "tool_id": inv.tool_id,
        "status": "blocked",
        "summary": "Skill installation is disabled; define CapabilityPackage instead.",
        "errors": ["skill_install_disabled"],
    }


def handle_skill_inspect(inv: ToolInvocation) -> dict:
    """Return skill (CapabilityPackage) details."""
    args = inv.arguments or {}
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    for pkg in CAPABILITY_PACKAGES:
        if pkg.capability_id == skill_name:
            return _ok(inv, "", _pkg_as_dict(pkg))

    return _error_inv(inv, f"skill '{skill_name}' not found")


__all__ = [
    "handle_skill_list",
    "handle_skill_request_load",
    "handle_skill_load",
    "handle_skill_find",
    "handle_skill_create",
    "handle_skill_install",
    "handle_skill_inspect",
]
