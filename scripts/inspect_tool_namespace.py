#!/usr/bin/env python3
"""Inspect v2.2 canonical namespace without changing runtime registration."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from agent.runtime.services import default_runtime_services
    from tool_runtime.tool_namespace import (
        CANONICAL_TO_EXECUTION,
        LEGACY_TO_EXECUTION,
        TOOL_NAMESPACE,
        execution_tool_ids,
        legacy_aliases,
    )
    from tool_runtime.tool_namespace_data import NS_DATA

    errors: list[str] = []
    registry = default_runtime_services().tool_service.registry
    runtime_ids = sorted(spec.tool_id for spec in registry.list_all())
    visible_ids = sorted(spec.tool_id for spec in registry.list_model_visible())
    canonical_ids = sorted(TOOL_NAMESPACE)
    execution_ids = execution_tool_ids()
    alias_ids = legacy_aliases()

    if len(runtime_ids) != 88:
        errors.append(f"runtime_count expected 88 got {len(runtime_ids)}")
    if len(visible_ids) > 88:
        errors.append(f"model_visible_count expected <=88 got {len(visible_ids)}")
    if len(canonical_ids) != 88:
        errors.append(f"canonical_count expected 88 got {len(canonical_ids)}")
    if len(execution_ids) != 88:
        errors.append(f"execution_count expected 88 got {len(execution_ids)}")
    if execution_ids != runtime_ids:
        missing = sorted(set(runtime_ids) - set(execution_ids))
        extra = sorted(set(execution_ids) - set(runtime_ids))
        errors.append(f"execution/runtime mismatch missing={missing} extra={extra}")

    duplicate_canonical = [k for k, v in Counter(canonical_ids).items() if v > 1]
    duplicate_execution = [k for k, v in Counter(CANONICAL_TO_EXECUTION.values()).items() if v > 1]
    raw_aliases = [alias for row in NS_DATA for alias in row[2]]
    duplicate_alias = [k for k, v in Counter(raw_aliases).items() if v > 1]
    if duplicate_canonical:
        errors.append(f"duplicate canonical ids: {duplicate_canonical}")
    if duplicate_execution:
        errors.append(f"duplicate execution mapping: {duplicate_execution}")
    if duplicate_alias:
        errors.append(f"duplicate legacy aliases: {duplicate_alias}")

    for canonical, entry in sorted(TOOL_NAMESPACE.items()):
        if CANONICAL_TO_EXECUTION.get(canonical) != entry.execution_tool_id:
            errors.append(f"{canonical}: canonical execution mismatch")
        for field in ("category", "group", "action", "display_name", "usage_hint"):
            if not getattr(entry, field):
                errors.append(f"{canonical}: missing {field}")
        if canonical.startswith("host.") and (
            entry.execution_tool_id.startswith("parser.")
            or entry.execution_tool_id.startswith("config_translation.")
            or entry.category == "network"
        ):
            errors.append(f"{canonical}: host tool mapped to network/parser execution")
        if canonical.startswith("network.") and (
            entry.execution_tool_id in {"shell.exec", "powershell.exec", "python.exec"}
            or entry.category == "host"
        ):
            errors.append(f"{canonical}: network tool mapped to host execution")
        if canonical.startswith("workspace.artifact.") and not entry.execution_tool_id.startswith("artifact."):
            errors.append(f"{canonical}: artifact namespace mapped outside artifact execution")
        if canonical.startswith("workspace.file.") and not (
            entry.execution_tool_id.startswith("file.")
            or entry.execution_tool_id.startswith("workspace.")
            or entry.execution_tool_id == "pdf.extract_text"
        ):
            errors.append(f"{canonical}: file namespace mapped outside file/workspace execution")

    alias_targets = defaultdict(set)
    for alias, execution in LEGACY_TO_EXECUTION.items():
        alias_targets[alias].add(execution)
    conflicts = {alias: sorted(targets) for alias, targets in alias_targets.items() if len(targets) > 1}
    if conflicts:
        errors.append(f"legacy alias conflicts: {conflicts}")

    by_category = Counter(entry.category for entry in TOOL_NAMESPACE.values())
    print(f"canonical_count {len(canonical_ids)}")
    print(f"execution_count {len(execution_ids)}")
    print(f"legacy_alias_count {len(alias_ids)}")
    print(f"runtime_count {len(runtime_ids)}")
    print(f"model_visible_count {len(visible_ids)}")
    print("categories")
    for category, count in sorted(by_category.items()):
        print(f"  {category}: {count}")

    if errors:
        print("FAIL")
        for err in errors:
            print(f"- {err}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
