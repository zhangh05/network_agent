#!/usr/bin/env python3
"""Legacy storage migration CLI.

Usage:
  python scripts/storage_legacy_migrate.py --workspace default --dry-run
  python scripts/storage_legacy_migrate.py --workspace default --apply
  python scripts/storage_legacy_migrate.py --all --dry-run
  python scripts/storage_legacy_migrate.py --all --apply
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(description="Legacy storage migration")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--workspace", type=str, help="Migrate a single workspace")
    group.add_argument("--all", action="store_true", help="Migrate all workspaces")
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run", default=True,
        help="Preview only (default)",
    )
    parser.add_argument(
        "--apply", action="store_false", dest="dry_run",
        help="Apply migration",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Write report to file (default: stdout)",
    )
    args = parser.parse_args()

    from storage.legacy_migration import (
        migrate_workspace_legacy_paths,
        migrate_all_workspaces,
    )

    if args.all:
        results = migrate_all_workspaces(dry_run=args.dry_run)
    else:
        results = [migrate_workspace_legacy_paths(args.workspace, dry_run=args.dry_run)]

    output = json.dumps(
        {"results": results, "dry_run": args.dry_run},
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Report written to {args.output}")
    else:
        print(output)

    # Save per-workspace report only in apply mode.
    # dry-run must not modify workspace files.
    if not args.dry_run:
        ws = r["workspace_id"]
        from storage.paths import workspace_root
        idx_dir = workspace_root(ws) / "index"
        idx_dir.mkdir(parents=True, exist_ok=True)
        report_path = idx_dir / "legacy_migration_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
