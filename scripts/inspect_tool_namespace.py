#!/usr/bin/env python3
"""v3.0 inspect: report canonical namespace, governance, capability actions."""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))


def main() -> int:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import (
        TOOL_GOVERNANCE, governance_summary,
    )
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY

    print(f"canonical_count:        {len(TOOL_NAMESPACE)}")
    print(f"registry_count:         {len(CANONICAL_REGISTRY)}")
    print(f"governance_count:       {len(TOOL_GOVERNANCE)}")
    print(f"capability_action_count:{len(CAPABILITY_ACTIONS)}")
    print(f"governance_summary:     {governance_summary()}")

    by_status: dict[str, list[str]] = {}
    for cid, entry in TOOL_GOVERNANCE.items():
        by_status.setdefault(entry.status, []).append(cid)
    for status in sorted(by_status):
        print(f"  {status}: {len(by_status[status])} tools")

    orphans = set(TOOL_NAMESPACE) - set(CANONICAL_REGISTRY)
    if orphans:
        print(f"WARNING: {len(orphans)} canonical ids have no handler: "
              f"{', '.join(sorted(orphans))}")
        return 1
    print("INSPECT TOOL NAMESPACE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
