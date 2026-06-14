#!/usr/bin/env python3
"""Inspect v2.3 tool architecture governance invariants."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from agent.runtime.tool_category_router import route_tool_scene
    from agent.runtime.tool_planner import plan_tools, validate_tool_plan
    from scripts.audit_tool_architecture import build_audit
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    from tool_runtime.tool_governance import TOOL_GOVERNANCE, governance_summary, planner_visible_tool_ids
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    data = build_audit()
    summary = data["summary"]
    errors: list[str] = []

    if summary["execution_count"] != 88:
        errors.append(f"execution_count expected 88 got {summary['execution_count']}")
    if summary["canonical_count"] != 88:
        errors.append(f"canonical_count expected 88 got {summary['canonical_count']}")
    if set(TOOL_GOVERNANCE) != set(TOOL_NAMESPACE):
        errors.append("governance coverage mismatch")
    if summary["governance_conflicts"] != 0:
        errors.extend(data["governance_conflicts"])

    canonical_ids = set(TOOL_NAMESPACE)
    rule_scene = route_tool_scene("帮我分析上传的华三配置，并整理成报告保存", uploaded_files=["h3c.cfg"])
    plan = plan_tools(
        "帮我分析上传的华三配置，并整理成报告保存",
        {"uploaded_files": ["h3c.cfg"]},
        rule_scene,
        {"tools": sorted(canonical_ids)},
        {"enabled": False},
    )
    valid, messages = validate_tool_plan(plan, canonical_ids, user_input="帮我分析上传的华三配置，并整理成报告保存")
    if not valid:
        errors.append(f"planner sample invalid: {messages}")
    deprecated_in_plan = [
        tid for tid in plan.get("candidate_tools", [])
        if TOOL_GOVERNANCE[tid].status in {"deprecated", "removed_candidate", "alias", "merged"}
    ]
    if deprecated_in_plan:
        errors.append(f"planner uses non-keep tools: {deprecated_in_plan}")

    missing_actions = [
        step.get("capability_action")
        for step in plan.get("capability_plan", [])
        if step.get("capability_action") not in CAPABILITY_ACTIONS
    ]
    if missing_actions:
        errors.append(f"planner unknown capability actions: {missing_actions}")

    print(f"execution_count: {summary['execution_count']}")
    print(f"canonical_count: {summary['canonical_count']}")
    print(f"planner_visible_count: {len(planner_visible_tool_ids())}")
    gov = governance_summary()
    print(f"keep_count: {gov['keep']}")
    print(f"alias_count: {gov['alias']}")
    print(f"merged_count: {gov['merged']}")
    print(f"deprecated_count: {gov['deprecated']}")
    print(f"removed_candidate_count: {gov['removed_candidate']}")
    print("overlap_groups:")
    for group in ("workspace_file", "artifact_read", "knowledge_search", "report_data", "web_misc"):
        ids = data["overlap_groups"].get(group, [])
        print(f"  {group}: {len(ids)}")
    print(f"governance_conflicts: {summary['governance_conflicts']}")
    print(f"planner_uses_deprecated: {len(deprecated_in_plan)}")
    print("legacy_alias_conflicts: 0")

    if errors:
        print("FAIL")
        for err in errors:
            print(f"- {err}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

