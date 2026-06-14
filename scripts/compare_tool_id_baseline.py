#!/usr/bin/env python3
"""Compare current tool ids with the frozen baseline stored in baselines/.

v2.1.3: Baseline files are now in baselines/ (repo-tracked), not /tmp.
Supports --write-current-baseline to regenerate.
Supports --runtime-baseline / --general-baseline overrides.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_RUNTIME_BASELINE = ROOT / "baselines" / "tool_ids_v2.1.1-full-closure.txt"
DEFAULT_GENERAL_BASELINE = ROOT / "baselines" / "general_tool_ids_v2.1.1-full-closure.txt"
EXPECTED_RUNTIME_COUNT = 88
EXPECTED_GENERAL_COUNT = 81


def _read_baseline(path: Path) -> list[str]:
    """Read a baseline file, skipping comments and empty lines."""
    if not path.exists():
        raise SystemExit(f"missing baseline file: {path}")
    ids: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("count "):
            continue
        ids.append(line)
    return ids


def _write_baseline(path: Path, ids: list[str], comment: str = "") -> None:
    """Write a baseline file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if comment:
            f.write(f"# {comment}\n")
        for tid in sorted(ids):
            f.write(tid + "\n")


def _print_list(title: str, values: list[str]) -> None:
    print(f"{title}: {values if values else []}")


def _validate_before_write(runtime_tools: list[str], visible_tools: list[str],
                           general_tools: list[str], builtin_tools: list[str]) -> bool:
    """Validate invariants before writing baseline."""
    ok = True
    if len(runtime_tools) != EXPECTED_RUNTIME_COUNT:
        print(f"ERROR: runtime count {len(runtime_tools)} != {EXPECTED_RUNTIME_COUNT}")
        ok = False
    if len(visible_tools) != EXPECTED_RUNTIME_COUNT:
        print(f"ERROR: visible count {len(visible_tools)} != {EXPECTED_RUNTIME_COUNT}")
        ok = False
    if len(general_tools) != EXPECTED_GENERAL_COUNT:
        print(f"ERROR: general count {len(general_tools)} != {EXPECTED_GENERAL_COUNT}")
        ok = False

    runtime_dups = sorted(t for t, c in Counter(runtime_tools).items() if c > 1)
    general_dups = sorted(t for t, c in Counter(general_tools).items() if c > 1)
    if runtime_dups:
        print(f"ERROR: runtime duplicates: {runtime_dups}")
        ok = False
    if general_dups:
        print(f"ERROR: general duplicates: {general_dups}")
        ok = False

    builtin_set = set(builtin_tools)
    general_set = set(general_tools)
    overlap = builtin_set & general_set
    if overlap:
        print(f"ERROR: builtin/general overlap: {sorted(overlap)}")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare current tool ids with baseline")
    parser.add_argument("--runtime-baseline", type=Path,
                        default=DEFAULT_RUNTIME_BASELINE,
                        help="Path to runtime tool_id baseline")
    parser.add_argument("--general-baseline", type=Path,
                        default=DEFAULT_GENERAL_BASELINE,
                        help="Path to general tool_id baseline")
    parser.add_argument("--write-current-baseline", action="store_true",
                        help="Write current tool ids as new baseline files")
    args = parser.parse_args()

    from agent.runtime.services import default_runtime_services
    from tool_runtime.builtins import BUILTIN_TOOLS
    from tool_runtime.general_tools import ALL_GENERAL_TOOLS

    svc = default_runtime_services()
    reg = svc.tool_service.registry
    current_tools = sorted(t.tool_id for t in reg.list_all())
    visible_tools = sorted(t.tool_id for t in reg.list_model_visible())
    general_tools = sorted(spec.tool_id for spec, _ in ALL_GENERAL_TOOLS)
    builtin_tools = sorted(spec.tool_id for spec, _ in BUILTIN_TOOLS)

    # ── Write baseline mode ──
    if args.write_current_baseline:
        ok = _validate_before_write(current_tools, visible_tools, general_tools, builtin_tools)
        if not ok:
            print("FAIL: invariants not met — baseline not written")
            return 1
        _write_baseline(args.runtime_baseline, current_tools,
                        f"Network Agent runtime tool_id baseline ({len(current_tools)} tools)")
        _write_baseline(args.general_baseline, general_tools,
                        f"Network Agent general tool_id baseline ({len(general_tools)} tools)")
        print(f"Baseline written: {args.runtime_baseline} ({len(current_tools)} tools)")
        print(f"Baseline written: {args.general_baseline} ({len(general_tools)} tools)")
        return 0

    # ── Compare mode ──
    runtime_baseline = _read_baseline(args.runtime_baseline)
    general_baseline = _read_baseline(args.general_baseline)

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
