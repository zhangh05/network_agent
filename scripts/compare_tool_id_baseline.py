#!/usr/bin/env python3
"""Compare current tool ids with the frozen v2.1.1 baseline."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOOL_BASELINE = Path("/tmp/tool_ids_baseline.txt")
GENERAL_BASELINE = Path("/tmp/general_ids_baseline.txt")
EXPECTED_RUNTIME_COUNT = 88


def _read_baseline(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"missing baseline file: {path}")
    ids: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("count "):
            continue
        ids.append(line)
    return ids


def _print_list(title: str, values: list[str]) -> None:
    print(f"{title}: {values if values else []}")


def main() -> int:
    from agent.runtime.services import default_runtime_services
    from tool_runtime.builtins import BUILTIN_TOOLS
    from tool_runtime.general_tools import ALL_GENERAL_TOOLS

    runtime_baseline = _read_baseline(TOOL_BASELINE)
    general_baseline = _read_baseline(GENERAL_BASELINE)

    svc = default_runtime_services()
    reg = svc.tool_service.registry
    current_tools = sorted(t.tool_id for t in reg.list_all())
    visible_tools = sorted(t.tool_id for t in reg.list_model_visible())
    general_tools = [spec.tool_id for spec, _ in ALL_GENERAL_TOOLS]
    builtin_tools = [spec.tool_id for spec, _ in BUILTIN_TOOLS]

    runtime_counts = Counter(current_tools)
    general_counts = Counter(general_tools)
    duplicate_runtime = sorted(tid for tid, count in runtime_counts.items() if count > 1)
    duplicate_general = sorted(tid for tid, count in general_counts.items() if count > 1)

    baseline_set = set(runtime_baseline)
    current_set = set(current_tools)
    general_baseline_set = set(general_baseline)
    general_set = set(general_tools)
    builtin_set = set(builtin_tools)

    added = sorted(current_set - baseline_set)
    removed = sorted(baseline_set - current_set)
    general_added = sorted(general_set - general_baseline_set)
    general_removed = sorted(general_baseline_set - general_set)

    print(f"baseline_count: {len(runtime_baseline)}")
    print(f"current_count: {len(current_tools)}")
    print(f"visible_count: {len(visible_tools)}")
    _print_list("added_tool_ids", added)
    _print_list("removed_tool_ids", removed)
    _print_list("duplicated_tool_ids", duplicate_runtime)
    print(f"general_baseline_count: {len(general_baseline)}")
    print(f"general_tool_count: {len(general_tools)}")
    _print_list("general_added_tool_ids", general_added)
    _print_list("general_removed_tool_ids", general_removed)
    _print_list("general_duplicated_tool_ids", duplicate_general)
    print(f"builtin_tool_count: {len(builtin_tools)}")
    _print_list("builtin_tool_ids", sorted(builtin_set))
    _print_list("overlap_builtin_general", sorted(builtin_set & general_set))
    _print_list("runtime_minus_general", sorted(current_set - general_set))
    _print_list("general_minus_runtime", sorted(general_set - current_set))

    failures: list[str] = []
    if len(current_tools) != EXPECTED_RUNTIME_COUNT:
        failures.append(f"runtime count drifted: {len(current_tools)} != {EXPECTED_RUNTIME_COUNT}")
    if len(visible_tools) != EXPECTED_RUNTIME_COUNT:
        failures.append(f"visible count drifted: {len(visible_tools)} != {EXPECTED_RUNTIME_COUNT}")
    if added:
        failures.append(f"added tool ids: {added}")
    if removed:
        failures.append(f"removed tool ids: {removed}")
    if duplicate_runtime:
        failures.append(f"duplicate runtime tool ids: {duplicate_runtime}")
    if general_added or general_removed:
        failures.append("general tool id set drifted from baseline")
    if duplicate_general:
        failures.append(f"duplicate general tool ids: {duplicate_general}")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
