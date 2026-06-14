#!/usr/bin/env python3
"""Generate v2.3 tool architecture audit artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REPORT_DIR = ROOT / "reports"
AUDIT_JSON = REPORT_DIR / "tool_architecture_audit.json"
AUDIT_MD = REPORT_DIR / "TOOL_ARCHITECTURE_AUDIT.md"


def main() -> int:
    data = build_audit()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUDIT_MD.write_text(render_markdown(data), encoding="utf-8")
    print(f"wrote {AUDIT_MD.relative_to(ROOT)}")
    print(f"wrote {AUDIT_JSON.relative_to(ROOT)}")
    print(f"execution_count: {data['summary']['execution_count']}")
    print(f"canonical_count: {data['summary']['canonical_count']}")
    print(f"planner_visible_count: {data['summary']['planner_visible_count']}")
    print("PASS")
    return 0


def build_audit() -> dict[str, Any]:
    from agent.runtime.services import default_runtime_services
    from tool_runtime.capability_actions import canonical_capability_coverage
    from tool_runtime.tool_governance import (
        TOOL_GOVERNANCE,
        governance_summary,
        is_planner_visible,
    )
    from tool_runtime.tool_namespace import TOOL_NAMESPACE, get_namespace_entry

    services = default_runtime_services()
    agent_registry = services.tool_service.registry
    runtime_registry = getattr(agent_registry, "_tool_client", None)
    runtime_registry = getattr(runtime_registry, "_registry", None)
    specs = sorted(agent_registry.list_all(), key=lambda s: s.tool_id)
    by_execution = {spec.tool_id: spec for spec in specs}
    docs_text = _read_docs_text()
    tests_text = _read_tests_text()
    capability_coverage = canonical_capability_coverage()
    tools: list[dict[str, Any]] = []
    handler_to_tools: dict[str, list[str]] = defaultdict(list)
    schema_to_tools: dict[str, list[str]] = defaultdict(list)
    grouped: dict[str, list[str]] = defaultdict(list)

    for canonical_id, namespace in sorted(TOOL_NAMESPACE.items()):
        spec = by_execution.get(namespace.execution_tool_id)
        handler = runtime_registry.get_handler(namespace.execution_tool_id) if runtime_registry else None
        handler_module = getattr(handler, "__module__", "") if handler else ""
        handler_name = getattr(handler, "__name__", "") if handler else ""
        schema_hash = _schema_hash(getattr(spec, "input_schema", {}) if spec else {})
        governance = TOOL_GOVERNANCE[canonical_id]
        handler_key = f"{handler_module}:{handler_name}"
        if handler_key != ":":
            handler_to_tools[handler_key].append(canonical_id)
        schema_to_tools[schema_hash].append(canonical_id)
        grouped[governance.overlap_group].append(canonical_id)
        used_by_planner = is_planner_visible(canonical_id) and canonical_id in set(capability_coverage["covered"])
        item = {
            "canonical_tool_id": canonical_id,
            "execution_tool_id": namespace.execution_tool_id,
            "legacy_tool_ids": list(namespace.legacy_tool_ids),
            "category": namespace.category,
            "group": namespace.group,
            "action": namespace.action,
            "handler_module": handler_module,
            "handler_name": handler_name,
            "permission_action": getattr(spec, "permission_action", "") if spec else "",
            "risk_level": getattr(spec, "risk_level", "") if spec else "",
            "requires_approval": bool(getattr(spec, "requires_approval", False)) if spec else False,
            "callable_by_llm": bool(getattr(spec, "callable_by_llm", False)) if spec else False,
            "input_schema_hash": schema_hash,
            "output_shape_hint": _output_shape_hint(namespace.category, namespace.group),
            "used_by_planner": used_by_planner,
            "used_by_tests": canonical_id in tests_text or namespace.execution_tool_id in tests_text,
            "used_by_docs": canonical_id in docs_text or namespace.execution_tool_id in docs_text,
            "overlap_group": governance.overlap_group,
            "recommendation": governance.status if governance.status != "removed_candidate" else "remove",
            "reason": governance.reason,
            "replacement": governance.replacement,
            "governance_status": governance.status,
        }
        # Verify namespace entry remains accessible; keeps audit honest.
        get_namespace_entry(canonical_id)
        tools.append(item)

    duplicate_handlers = {
        key: ids for key, ids in sorted(handler_to_tools.items())
        if len(ids) > 1
    }
    duplicate_schemas = {
        key: ids for key, ids in sorted(schema_to_tools.items())
        if len(ids) > 1
    }
    overlap_groups = {key: ids for key, ids in sorted(grouped.items())}
    governance_conflicts = _governance_conflicts(tools)
    summary = {
        "execution_count": len(specs),
        "canonical_count": len(TOOL_NAMESPACE),
        "legacy_alias_count": sum(len(entry.legacy_tool_ids) for entry in TOOL_NAMESPACE.values()),
        "planner_visible_count": sum(1 for item in tools if item["used_by_planner"]),
        "governance_summary": governance_summary(),
        "governance_conflicts": len(governance_conflicts),
        "duplicate_handler_groups": len(duplicate_handlers),
        "duplicate_schema_groups": len(duplicate_schemas),
        "overlap_group_count": len(overlap_groups),
        "conservative_reduction": sum(1 for item in tools if item["governance_status"] in {"alias", "merged"}),
        "aggressive_reduction": sum(1 for item in tools if item["governance_status"] in {"alias", "merged", "deprecated", "removed_candidate"}),
    }
    return {
        "summary": summary,
        "governance_conflicts": governance_conflicts,
        "duplicate_handlers": duplicate_handlers,
        "duplicate_input_schemas": duplicate_schemas,
        "overlap_groups": overlap_groups,
        "tools": tools,
    }


def _schema_hash(schema: dict[str, Any]) -> str:
    blob = json.dumps(schema or {}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _output_shape_hint(category: str, group: str) -> str:
    if category == "workspace":
        return "workspace metadata/content/artifact result"
    if category == "network":
        return "offline parsed network config facts"
    if category == "knowledge":
        return "safe excerpts, source metadata, or index status"
    if category == "host":
        return "approved local host command result"
    if category == "report_data":
        return "rendered text/data/report artifact metadata"
    return f"{category}.{group} result"


def _read_docs_text() -> str:
    parts: list[str] = []
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        if path.exists():
            parts.append(path.read_text(errors="ignore"))
    return "\n".join(parts)


def _read_tests_text() -> str:
    parts: list[str] = []
    for path in sorted((ROOT / "harness").glob("test_*.py")):
        parts.append(path.read_text(errors="ignore"))
    return "\n".join(parts)


def _governance_conflicts(tools: list[dict[str, Any]]) -> list[str]:
    canonical_ids = {item["canonical_tool_id"] for item in tools}
    conflicts: list[str] = []
    for item in tools:
        replacement = item.get("replacement")
        if replacement and replacement not in canonical_ids:
            conflicts.append(f"{item['canonical_tool_id']}: replacement missing: {replacement}")
        if item["governance_status"] in {"alias", "merged"} and not replacement:
            conflicts.append(f"{item['canonical_tool_id']}: {item['governance_status']} without replacement")
    return conflicts


def render_markdown(data: dict[str, Any]) -> str:
    summary = data["summary"]
    lines = [
        "# Tool Architecture Audit",
        "",
        "Generated by `scripts/audit_tool_architecture.py`.",
        "",
        "## Summary",
        "",
        f"- execution_count: {summary['execution_count']}",
        f"- canonical_count: {summary['canonical_count']}",
        f"- planner_visible_count: {summary['planner_visible_count']}",
        f"- legacy_alias_count: {summary['legacy_alias_count']}",
        f"- governance_conflicts: {summary['governance_conflicts']}",
        f"- conservative_reduction: {summary['conservative_reduction']}",
        f"- aggressive_reduction: {summary['aggressive_reduction']}",
        "",
        "## Governance Summary",
        "",
    ]
    for status, count in sorted(summary["governance_summary"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Overlap Groups", ""])
    for group, ids in sorted(data["overlap_groups"].items()):
        if group in {"workspace_file", "artifact_read", "knowledge_search", "report_data", "web_misc"}:
            lines.append(f"### {group}")
            for canonical_id in ids:
                item = next(t for t in data["tools"] if t["canonical_tool_id"] == canonical_id)
                replacement = f" -> {item['replacement']}" if item.get("replacement") else ""
                lines.append(f"- `{canonical_id}`: {item['governance_status']}{replacement}")
            lines.append("")
    lines.extend(["## Tool Detail", ""])
    for item in data["tools"]:
        replacement = f" replacement=`{item['replacement']}`" if item.get("replacement") else ""
        lines.append(
            f"- `{item['canonical_tool_id']}` exec=`{item['execution_tool_id']}` "
            f"status={item['governance_status']}{replacement} group={item['overlap_group']}"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
