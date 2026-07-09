"""v3.9.4: Single-source business capability catalog.

A "business capability" is a thin description of a thing the agent can
do, plus a list of recommended tool ids. It is NOT a tool registration
mechanism, NOT a visibility gate, NOT a permission/approval layer —
those concerns live in canonical_registry / manifest_registry / sandbox.

Three rules:
  1. recommended_tool_ids MUST be a subset of TOOL_NAMESPACE (the
     canonical tool ids, see ``core.tools.tool_namespace``). Removed
     names like device.list / git.status are invalid.
  2. This module exposes only data + a few lookup helpers. It does not
     register tools, filter tools, or influence dispatch.
  3. Frontend (skills / capabilities API) and the skill.manage tool
     read this catalog directly. There is no second source of truth.
"""

from __future__ import annotations

from typing import Any, Iterable

from core.tools.tool_namespace import TOOL_NAMESPACE


# Field schema for each entry:
#   capability_id       str   unique id
#   display_name        str   human-readable name
#   description         str   one-sentence description
#   module_ids          tuple  backend module name(s) (e.g. "cmdb", "pcap")
#   recommended_tool_ids tuple  canonical tool ids from the 29-tool set
#   prompt_hints        tuple  short hints for the LLM when invoking
#   safety_notes        tuple  short safety warnings for the LLM
#   status              str   "enabled" or "planned"
_CAPABILITIES: tuple[dict, ...] = (
    {
        "capability_id": "workspace_read",
        "display_name": "Workspace Read",
        "description": "Read or inspect workspace files and artifacts.",
        "module_ids": ("workspace",),
        "recommended_tool_ids": ("workspace.file", "workspace.artifact"),
        "prompt_hints": ("Read workspace files before parsing domain content.",),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "knowledge_qa",
        "display_name": "Knowledge QA",
        "description": "Search and read indexed knowledge.",
        "module_ids": ("knowledge",),
        "recommended_tool_ids": ("knowledge.manage",),
        "prompt_hints": (),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "memory_lookup",
        "display_name": "Memory Lookup",
        "description": "Search or inspect memory and profile facts.",
        "module_ids": ("memory",),
        "recommended_tool_ids": ("memory.manage",),
        "prompt_hints": (),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "config_translation",
        "display_name": "Config Translation",
        "description": "Parse, translate, compare and summarize network configuration text.",
        "module_ids": ("config_analysis", "workspace"),
        "recommended_tool_ids": ("workspace.file", "config.manage"),
        "prompt_hints": (
            "Translated config is analysis output, not deployable configuration.",
        ),
        "safety_notes": (
            "Do not claim translated configuration is production-ready.",
        ),
        "status": "enabled",
    },
    {
        "capability_id": "pcap_analysis",
        "display_name": "PCAP Analysis",
        "description": "Parse and inspect packet capture files.",
        "module_ids": ("pcap", "workspace"),
        "recommended_tool_ids": ("workspace.file", "pcap.manage"),
        "prompt_hints": (),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "report_drafting",
        "display_name": "Report Drafting",
        "description": "Render reports and save report artifacts.",
        "module_ids": ("workspace",),
        "recommended_tool_ids": ("report.manage", "workspace.artifact"),
        "prompt_hints": (),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "runtime_diagnostics",
        "display_name": "Runtime Diagnostics",
        "description": "Inspect runtime health and diagnostics.",
        "module_ids": ("runtime",),
        "recommended_tool_ids": ("system.manage",),
        "prompt_hints": (),
        "safety_notes": (),
        "status": "enabled",
    },
    {
        "capability_id": "agent_delegation",
        "display_name": "Agent Delegation",
        "description": "Spawn sub-agents, list roles, run teams, fetch results.",
        "module_ids": ("runtime",),
        "recommended_tool_ids": (
            "agent.manage",
            "spawn_review_agent",
            "spawn_fix_agent",
            "spawn_test_agent",
            "spawn_doc_agent",
            "spawn_network_diag_agent",
            "spawn_config_translate_agent",
            "spawn_security_agent",
        ),
        "prompt_hints": (
            "Use named spawn tools to start subagents; use agent.manage(action=get) to fetch results.",
        ),
        "safety_notes": (
            "Sub-agents inherit workspace/session boundaries.",
            "Do not spawn a sub-agent for a simple single-step lookup.",
        ),
        "status": "enabled",
    },
    {
        "capability_id": "cmdb",
        "display_name": "CMDB Device Assets",
        "description": "List, get, add, update, delete, export network device assets with region/location.",
        "module_ids": ("cmdb",),
        "recommended_tool_ids": ("device.manage",),
        "prompt_hints": (
            "When the user mentions an area or site, call device.manage(action=list) with a JSON region/location filter.",
            "For live access, pass the returned asset_id to exec.run target=ssh/telnet instead of asking for or exposing passwords.",
        ),
        "safety_notes": (
            "Do not declare CMDB entries that were not returned by tools.",
            "Add/delete operations need user confirmation.",
        ),
        "status": "enabled",
    },
    {
        "capability_id": "network_device",
        "display_name": "Network Device SSH/Telnet",
        "description": "SSH/Telnet to a network device and run commands. "
                       "Look up device info via CMDB first, then connect.",
        "module_ids": ("cmdb",),
        "recommended_tool_ids": ("device.manage", "exec.run"),
        "prompt_hints": (),
        "safety_notes": (
            "Live-device reads and connection attempts are medium risk; only destructive commands require approval.",
            "Dangerous commands (reload/erase/format) are auto-blocked.",
        ),
        "status": "enabled",
    },
    {
        "capability_id": "browser",
        "display_name": "Browser Automation",
        "description": "Drive a Playwright browser: navigate, extract, "
                       "screenshot, click.",
        "module_ids": ("browser",),
        "recommended_tool_ids": ("browser.manage",),
        "prompt_hints": (
            "Browser provides real-time web page content. Prefer it over "
            "web.manage when interactive browsing is needed.",
        ),
        "safety_notes": (
            "Browser content comes from external sites; do not access "
            "internal/login-walled URLs without permission."
        ),
        "status": "enabled",
    },
    {
        "capability_id": "inspection",
        "display_name": "CMDB-Driven Device Inspection",
        "description": "Health / interface / routing inspection and config backup "
                       "across many devices, driven by CMDB scope.",
        "module_ids": ("inspection", "cmdb"),
        "recommended_tool_ids": ("inspection.manage", "device.manage", "exec.run"),
        "prompt_hints": (
            "When the user asks to inspect / health-check / batch-check / "
            "backup configuration across devices, prefer inspection.manage "
            "with action=run. The backend picks the right profile per device "
            "from CMDB vendor/type -- callers do NOT need to choose. Pass "
            "profile_id=\"auto\" (or omit it) for default behaviour. The five "
            "fixed profiles are: basic_health, interface_health, "
            "routing_health, config_backup, full_basic -- copy the id "
            "exactly with the underscores if you want to override.",
            "Send a CMDB scope (region/location/type/vendor/tags/asset_ids/limit). "
            "An empty scope inspects every device in the workspace -- that "
            "may be too many devices; prefer a region or vendor filter when "
            "the CMDB has many assets.",
        ),
        "safety_notes": (
            "Inspection commands are read-only -- the runner enforces a "
            "fixed per-vendor map and rejects unknown commands.",
            "Do not pass raw shell strings into the LLM execution path; "
            "only inspection.manage may dispatch device commands.",
            "Device passwords never appear in tool input or output.",
        ),
        "status": "enabled",
    },
)


# v3.9.4 contract check at import time: every recommended_tool_id MUST be
# a canonical id. This guarantees the catalog cannot accidentally
# re-introduce a removed tool name.
def _validate_catalog() -> None:
    canonical = set(TOOL_NAMESPACE)
    for cap in _CAPABILITIES:
        for tid in cap["recommended_tool_ids"]:
            if tid not in canonical:
                raise ValueError(
                    f"business capability {cap['capability_id']!r} references "
                    f"non-canonical tool id {tid!r}; expected one of {sorted(canonical)}"
                )


_validate_catalog()

# Public immutable catalog export for code that needs a data handle rather
# than helper functions. Keep helpers as the preferred read API.
CAPABILITY_CATALOG: tuple[dict, ...] = _CAPABILITIES


def list_all() -> list[dict]:
    """Return all business capabilities (enabled + planned)."""
    return list(CAPABILITY_CATALOG)


def list_enabled() -> list[dict]:
    """Return enabled business capabilities only."""
    return [c for c in CAPABILITY_CATALOG if c["status"] == "enabled"]


def list_planned() -> list[dict]:
    """Return planned (not yet enabled) business capabilities."""
    return [c for c in CAPABILITY_CATALOG if c["status"] == "planned"]


def get(capability_id: str) -> dict | None:
    for c in CAPABILITY_CATALOG:
        if c["capability_id"] == capability_id:
            return c
    return None


def to_skill_dict(cap: dict) -> dict:
    """Render a business capability as the skill.manage dict shape."""
    return {
        "skill_id": cap["capability_id"],
        "display_name": cap["display_name"],
        "description": cap["description"],
        "status": cap["status"],
        "capability_ids": (cap["capability_id"],),
        "module_ids": tuple(cap["module_ids"]),
        "tool_ids": tuple(cap["recommended_tool_ids"]),
        "prompt_hints": tuple(cap["prompt_hints"]),
        "safety_notes": tuple(cap["safety_notes"]),
        "source": "business_capability_catalog",
    }


def all_recommended_tool_ids() -> set[str]:
    """Set of every tool_id that any business capability recommends."""
    out: set[str] = set()
    for c in CAPABILITY_CATALOG:
        out.update(c["recommended_tool_ids"])
    return out


__all__ = [
    "CAPABILITY_CATALOG",
    "list_all",
    "list_enabled",
    "list_planned",
    "get",
    "to_skill_dict",
    "all_recommended_tool_ids",
]
