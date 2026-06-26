"""Cached, canonical projection of the public tool catalog."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

CATALOG_VERSION = "tool_catalog.v2"


@lru_cache(maxsize=1)
def build_catalog_snapshot() -> dict:
    from tool_runtime.capability_actions import capability_actions_for
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY, list_canonical_ids
    from tool_runtime.tool_governance import governance_summary, planner_visible_tool_ids
    from tool_runtime.tool_namespace import TOOL_NAMESPACE, category_tree_from_specs, metadata_for_tool

    tools = []
    # v3.10 Phase 5: enrich with Capability Manifest fields
    try:
        from tool_runtime.manifest_registry import get_manifest as _gm
    except Exception:
        _gm = None

    for canonical_id in list_canonical_ids():
        cr_entry = CANONICAL_REGISTRY[canonical_id]
        meta = metadata_for_tool(canonical_id)
        manifest = _gm(canonical_id) if _gm else None

        item = {
            "tool_id": canonical_id,
            "canonical_tool_id": canonical_id,
            "display_name": meta["display_name"],
            "category": meta["category"],
            "group": meta["group"],
            "action": meta["action"],
            "description": cr_entry.description,
            "risk_level": cr_entry.risk_level,
            "requires_approval": bool(cr_entry.requires_approval),
            "input_schema": cr_entry.input_schema,
            "permission_action": cr_entry.permission_action,
            "callable_by_llm": True,
            "enabled": True,
            "governance_status": meta["governance_status"],
            "planner_visible": bool(meta["planner_visible"]),
            "capability_actions": capability_actions_for(canonical_id),
            # v3.10 Phase 5: Capability Manifest fields
            "destructive": manifest.destructive if manifest else False,
            "idempotency": manifest.idempotency if manifest else "unknown",
            "side_effects": manifest.side_effects if manifest else "none",
            "output_sensitivity": manifest.output_sensitivity if manifest else "internal",
            "timeout_seconds": manifest.timeout_seconds if manifest else 30,
            "action_class": manifest.action_class if manifest else "read",
            "approval_reason": manifest.approval_reason_template if manifest else "",
            "rollback_strategy": manifest.rollback_strategy if manifest else "none",
        }
        tools.append(item)
    tools.sort(key=lambda item: item["canonical_tool_id"])

    class _Spec:
        def __init__(self, item):
            canonical_id = item["canonical_tool_id"]
            registry_entry = CANONICAL_REGISTRY[canonical_id]
            self.tool_id = canonical_id
            self.metadata = {
                "canonical_tool_id": canonical_id,
                "category": item["category"],
                "group": item["group"],
                "action": item["action"],
                "display_name": item["display_name"],
                "short_label": canonical_id,
                "usage_hint": "",
                "not_for": "",
                "handler_id": registry_entry.handler_id,
                "governance_status": item["governance_status"],
                "governance_reason": "",
                "planner_visible": item["planner_visible"],
            }
            self.risk_level = item["risk_level"]
            self.requires_approval = item["requires_approval"]
            self.permission_action = item["permission_action"]
            self.enabled = item["enabled"]
            self.callable_by_llm = item["callable_by_llm"]
            self.description = item["description"]

    categories = category_tree_from_specs([_Spec(item) for item in tools])
    fingerprint_input = [
        {
            "id": item["canonical_tool_id"],
            "governance": item["governance_status"],
            "visible": item["planner_visible"],
            "risk": item["risk_level"],
        }
        for item in tools
    ]
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True).encode("utf-8"),
    ).hexdigest()[:16]
    return {
        "tools": tools,
        "categories": categories,
        "count": len(tools),
        "planner_visible_count": len(planner_visible_tool_ids()),
        "governance_summary": governance_summary(),
        "catalog_version": CATALOG_VERSION,
        "catalog_fingerprint": fingerprint,
        "cache_policy": "process_static",
        "note": (
            "Read-only catalog. canonical_tool_id is the only public "
            "tool ID; handler_id is internal-only."
        ),
    }


def reset_catalog_snapshot_cache() -> None:
    build_catalog_snapshot.cache_clear()
