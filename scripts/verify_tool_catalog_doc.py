#!/usr/bin/env python3
"""Verify docs/TOOL_CATALOG_V2.3.md matches the v2.3 tool architecture.

Hard checks (any failure = exit 1):

  1.  docs/TOOL_CATALOG_V2.3.md exists.
  2.  Every canonical_tool_id appears at least once in the document.
  3.  Each canonical_tool_id appears exactly once as an h3 title.
  4.  Every tool has execution_tool_id, governance_status, planner_visible,
      用途 and 边界.
  5.  Non-keep tools have replacement / migration_notes.
  6.  No truncated lines (— / - / TODO / TBD / ... / 待补充).
  7.  Old execution_tool_ids are not used as h3 titles.
  8.  Reports JSON canonical_count == 88.
  9.  Document summary numbers align with reports JSON summary.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOC_PATH = ROOT / "docs" / "TOOL_CATALOG_V2.3.md"
JSON_PATH = ROOT / "reports" / "tool_catalog_v23.json"
AUDIT_PATH = ROOT / "reports" / "tool_architecture_audit.json"

EXPECTED_CANONICAL_COUNT = 88
H3_RE = re.compile(r"^###\s+`([^`]+)`", re.MULTILINE)
PLACEHOLDER_TAILS = ("—", "-", "...", "TODO", "TBD", "待补充")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_existence() -> list[str]:
    errors: list[str] = []
    if not DOC_PATH.exists():
        errors.append(f"missing {DOC_PATH.relative_to(ROOT)}")
    if not JSON_PATH.exists():
        errors.append(f"missing {JSON_PATH.relative_to(ROOT)}")
    return errors


def _load_runtime_truth() -> dict[str, Any]:
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    return {
        "canonical": set(TOOL_NAMESPACE),
        "execution": {entry.execution_tool_id for entry in TOOL_NAMESPACE.values()},
        "governance": {cid: TOOL_GOVERNANCE[cid].status for cid in TOOL_NAMESPACE},
    }


def _check_canonical_coverage(
    doc: str,
    truth: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    h3_titles = H3_RE.findall(doc)
    canonical_in_doc = set()
    for title in h3_titles:
        if title.startswith("5."):
            continue
        if title in truth["canonical"]:
            canonical_in_doc.add(title)
    missing = truth["canonical"] - canonical_in_doc
    if missing:
        errors.append(
            "missing canonical_tool_ids as h3 titles: "
            + ", ".join(sorted(missing))
        )
    duplicates = [
        t for t in h3_titles if h3_titles.count(t) > 1 and not t.startswith("5.")
    ]
    if duplicates:
        errors.append(
            "duplicate h3 titles: " + ", ".join(sorted(set(duplicates)))
        )
    return errors


def _check_no_truncation(doc: str) -> list[str]:
    errors: list[str] = []
    lines = doc.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if not stripped:
            continue
        if stripped.endswith(PLACEHOLDER_TAILS):
            errors.append(f"line {i} has truncation placeholder: {stripped!r}")
    return errors


def _check_no_old_id_titles(doc: str, truth: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    h3_titles = H3_RE.findall(doc)
    for title in h3_titles:
        if title in truth["execution"] and title not in truth["canonical"]:
            errors.append(
                f"old execution id used as h3 title: `{title}`"
            )
    return errors


def _split_tool_sections(doc: str) -> dict[str, list[str]]:
    """Group the doc into per-tool sections keyed by canonical id."""
    lines = doc.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    buffer: list[str] = []
    section_re = re.compile(r"^###\s+\d+\.\d+\.?\s")
    for line in lines:
        match = H3_RE.match(line)
        if match and not section_re.match(line):
            if current:
                sections[current] = buffer
            current = match.group(1)
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current:
        sections[current] = buffer
    return sections


def _check_tool_fields(
    sections: dict[str, list[str]],
    truth: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for canonical_id, lines in sections.items():
        block = "\n".join(lines)
        required = [
            ("execution_tool_id", "execution_tool_id"),
            ("governance_status", "governance_status"),
            ("planner_visible", "planner_visible"),
            ("用途", "用途"),
            ("边界", "边界"),
        ]
        for marker, label in required:
            if marker not in block:
                errors.append(
                    f"{canonical_id}: missing `{label}` field"
                )
        if truth["governance"][canonical_id] != "keep":
            if "replacement" not in block and "migration_notes" not in block:
                errors.append(
                    f"{canonical_id}: non-keep tool missing replacement/migration_notes"
                )
    return errors


def _check_summary_consistency(
    doc: str, catalog: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    summary = catalog["summary"]
    canonical_count = summary["canonical_count"]
    execution_count = summary["execution_count"]
    planner_visible = summary["planner_visible_count"]
    legacy_alias = summary["legacy_alias_count"]
    cap_action_count = summary["capability_action_count"]
    governance = summary["governance_summary"]

    expected_pairs = [
        (f"**canonical_count**：{canonical_count}", "canonical_count"),
        (f"**execution_count**：{execution_count}", "execution_count"),
        (f"**planner_visible_count**：{planner_visible}", "planner_visible_count"),
        (f"**legacy_alias_count**：{legacy_alias}", "legacy_alias_count"),
        (f"**capability_action_count**：{cap_action_count}", "capability_action_count"),
    ]
    for needle, label in expected_pairs:
        if needle not in doc:
            errors.append(f"doc missing summary bullet: {label} -> {needle!r}")

    expected_governance_rows = [
        f"| keep | {governance['keep']} |",
        f"| alias | {governance['alias']} |",
        f"| merged | {governance['merged']} |",
        f"| deprecated | {governance['deprecated']} |",
        f"| removed_candidate | {governance['removed_candidate']} |",
    ]
    for needle in expected_governance_rows:
        if needle not in doc:
            errors.append(f"doc missing governance row: {needle!r}")
    return errors


def _check_json_canonical_count(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog["summary"]["canonical_count"] != EXPECTED_CANONICAL_COUNT:
        errors.append(
            f"reports/tool_catalog_v23.json canonical_count="
            f"{catalog['summary']['canonical_count']} != {EXPECTED_CANONICAL_COUNT}"
        )
    return errors


def _check_audit_consistency(
    doc: str, audit: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    summary = audit.get("summary", {})
    audit_canonical = summary.get("canonical_count")
    audit_execution = summary.get("execution_count")
    audit_planner = summary.get("planner_visible_count")
    if audit_canonical is not None and audit_canonical != EXPECTED_CANONICAL_COUNT:
        errors.append(
            f"audit canonical_count={audit_canonical} != {EXPECTED_CANONICAL_COUNT}"
        )
    if audit_execution is not None and audit_execution != EXPECTED_CANONICAL_COUNT:
        errors.append(
            f"audit execution_count={audit_execution} != {EXPECTED_CANONICAL_COUNT}"
        )
    if audit_planner is not None:
        if f"**planner_visible_count**：{audit_planner}" not in doc:
            errors.append(
                f"doc planner_visible_count does not match audit ({audit_planner})"
            )
    return errors


def main() -> int:
    existence = _check_existence()
    if existence:
        for line in existence:
            print(f"FAIL  {line}")
        return 1

    doc = DOC_PATH.read_text(encoding="utf-8")
    catalog = _load_json(JSON_PATH)
    audit = (
        _load_json(AUDIT_PATH) if AUDIT_PATH.exists() else {"summary": {}}
    )
    truth = _load_runtime_truth()

    sections = _split_tool_sections(doc)

    all_errors: list[tuple[str, list[str]]] = []
    all_errors.append(("existence", existence))
    all_errors.append((
        "canonical coverage + duplicates",
        _check_canonical_coverage(doc, truth, catalog),
    ))
    all_errors.append((
        "truncation / TODO / TBD / ... / 待补充",
        _check_no_truncation(doc),
    ))
    all_errors.append((
        "old execution id as h3 title",
        _check_no_old_id_titles(doc, truth),
    ))
    all_errors.append((
        "tool fields present",
        _check_tool_fields(sections, truth),
    ))
    all_errors.append((
        "doc summary alignment",
        _check_summary_consistency(doc, catalog),
    ))
    all_errors.append((
        "json canonical_count == 88",
        _check_json_canonical_count(catalog),
    ))
    all_errors.append((
        "audit consistency",
        _check_audit_consistency(doc, audit),
    ))

    total = sum(len(errs) for _, errs in all_errors)
    for label, errs in all_errors:
        status = "OK  " if not errs else "FAIL"
        print(f"{status} {label} ({len(errs)})")
        for err in errs:
            print(f"     - {err}")
    print()
    summary = catalog["summary"]
    print(f"canonical_count:        {summary['canonical_count']}")
    print(f"execution_count:        {summary['execution_count']}")
    print(f"planner_visible_count:  {summary['planner_visible_count']}")
    print(f"legacy_alias_count:     {summary['legacy_alias_count']}")
    print(f"capability_action_count:{summary['capability_action_count']}")
    print(f"governance:             {summary['governance_summary']}")
    print(f"h3 tool sections:       {len(sections)}")
    if total == 0:
        print("verify_tool_catalog_doc PASS")
        return 0
    print(f"verify_tool_catalog_doc FAIL ({total} issues)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
