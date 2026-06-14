#!/usr/bin/env python3
"""v3.0 inspect: report architecture overview and check invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import (
        TOOL_GOVERNANCE, governance_summary,
    )
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY

    summary = governance_summary()
    failures: list[str] = []
    if summary.get("alias", 0) > 0:
        failures.append(f"unexpected alias count: {summary['alias']}")
    if summary.get("merged", 0) > 0:
        failures.append(f"unexpected merged count: {summary['merged']}")
    if summary.get("deprecated", 0) > 0:
        failures.append(f"unexpected deprecated count: {summary['deprecated']}")
    if summary.get("removed_candidate", 0) > 0:
        failures.append(
            f"unexpected removed_candidate count: {summary['removed_candidate']}"
        )

    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print("INSPECT TOOL ARCHITECTURE FAIL")
        return 1

    print(f"canonical_count:        {len(TOOL_NAMESPACE)}")
    print(f"registry_count:         {len(CANONICAL_REGISTRY)}")
    print(f"governance_summary:     {summary}")
    print(f"capability_action_count:{len(CAPABILITY_ACTIONS)}")
    print("INSPECT TOOL ARCHITECTURE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
