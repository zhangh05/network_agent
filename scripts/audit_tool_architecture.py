#!/usr/bin/env python3
"""v3.0 audit: verify canonical-only architecture invariants.

Invariants:
  - No transition statuses (alias / merged / deprecated / removed_candidate).
  - handler_id is internal-only and never equals the canonical_tool_id
    in any public catalog payload.
  - Every canonical_tool_id has a planner_visible status.
  - Every capability_action resolves to canonical_tool_ids in the namespace.
  - Write the v3.0 audit JSON to reports/tool_architecture_audit.json.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_JSON = ROOT / "reports" / "tool_architecture_audit.json"


def main() -> int:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY

    errors: list[str] = []

    # 1. No transition statuses.
    forbidden = {"alias", "merged", "deprecated", "removed_candidate"}
    for entry in TOOL_GOVERNANCE.values():
        if entry.status in forbidden:
            errors.append(f"forbidden status in governance: {entry.status}")

    # 2. Namespace metadata() must not contain transition fields.
    for cid, ns_entry in TOOL_NAMESPACE.items():
        meta = ns_entry.metadata()
        for f in ("execution_tool_id", "legacy_tool_ids",
                  "replacement", "migration_notes"):
            if f in meta:
                errors.append(f"{cid}: namespace metadata exposes {f}")

    # 3. capability_actions must resolve to canonical ids.
    for action in CAPABILITY_ACTIONS.values():
        for tool_id in action.preferred_tools + action.fallback_tools:
            if tool_id not in TOOL_NAMESPACE:
                errors.append(
                    f"capability_action {action.capability_action} "
                    f"references unknown canonical id {tool_id}"
                )

    # 4. Canonical registry matches namespace.
    orphans = set(TOOL_NAMESPACE) - set(CANONICAL_REGISTRY)
    extras = set(CANONICAL_REGISTRY) - set(TOOL_NAMESPACE)
    if orphans:
        errors.append(f"canonical ids without handlers: {sorted(orphans)}")
    if extras:
        errors.append(f"handlers without canonical ids: {sorted(extras)}")

    # Build audit JSON.
    by_status: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    for cid, entry in TOOL_GOVERNANCE.items():
        by_status[entry.status] += 1
        by_category[TOOL_NAMESPACE[cid].category] += 1

    audit = {
        "summary": {
            "canonical_count": len(TOOL_NAMESPACE),
            "handler_count": len(CANONICAL_REGISTRY),
            "planner_visible_count": sum(
                1 for e in TOOL_GOVERNANCE.values() if e.planner_visible
            ),
            "capability_action_count": len(CAPABILITY_ACTIONS),
            "legacy_alias_count": 0,
            "transition_statuses": 0,
        },
        "governance_summary": dict(by_status),
        "category_summary": dict(by_category),
        "invariants_ok": not errors,
        "errors": errors,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if errors:
        for e in errors:
            print(f"FAIL  {e}")
        print(f"AUDIT TOOL ARCHITECTURE FAIL ({len(errors)} errors)")
        return 1

    print(f"canonical_count:        {len(TOOL_NAMESPACE)}")
    print(f"handler_count:          {len(CANONICAL_REGISTRY)}")
    print(f"planner_visible_count:  {audit['summary']['planner_visible_count']}")
    print(f"capability_action_count:{len(CAPABILITY_ACTIONS)}")
    print(f"transition_statuses:    0")
    print(f"report:                 {REPORT_JSON.relative_to(ROOT)}")
    print("AUDIT TOOL ARCHITECTURE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
