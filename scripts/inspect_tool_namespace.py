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

    try:
        from agent.runtime.tool_category_router import route_tool_scene
        _inspect_tool_chain_routing(route_tool_scene, set(canonical_ids), errors)
    except Exception as exc:
        errors.append(f"tool_chain_routing_inspection_failed: {exc!r}")

    try:
        from agent.runtime.tool_planner import plan_tools, validate_tool_plan
        _inspect_tool_planner(plan_tools, validate_tool_plan, set(canonical_ids), errors)
    except Exception as exc:
        errors.append(f"tool_planner_inspection_failed: {exc!r}")

    by_category = Counter(entry.category for entry in TOOL_NAMESPACE.values())
    print(f"canonical_count {len(canonical_ids)}")
    print(f"execution_count {len(execution_ids)}")
    print(f"legacy_alias_count {len(alias_ids)}")
    print(f"runtime_count {len(runtime_ids)}")
    print(f"model_visible_count {len(visible_ids)}")
    print("planner_mode deterministic/hybrid")
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


def _inspect_tool_chain_routing(route_tool_scene, canonical_ids: set[str], errors: list[str]) -> None:
    samples = {
        "host": route_tool_scene("本机 OS 的 IP 是多少"),
        "network_report": route_tool_scene("帮我分析上传的华三配置，并整理成报告保存"),
        "web_network": route_tool_scene("根据官方文档看看这个 Cisco OSPF 配置有没有问题"),
    }
    for name, scene in samples.items():
        candidates = scene.get("candidate_tools") or []
        non_canonical = [tid for tid in candidates if tid not in canonical_ids]
        if non_canonical:
            errors.append(f"{name}: non-canonical candidate_tools {non_canonical}")
        candidate_set = set(candidates)
        for step in scene.get("tool_chain") or []:
            preferred = set(step.get("preferred_tools") or [])
            if not preferred <= candidate_set:
                errors.append(f"{name}: preferred tools outside candidates {sorted(preferred - candidate_set)}")

    network_report_categories = set(samples["network_report"].get("categories") or [])
    if not {"workspace", "network", "report_data"} <= network_report_categories:
        errors.append(f"network_report: missing chained categories {sorted(network_report_categories)}")
    host_candidates = set(samples["host"].get("candidate_tools") or [])
    if "network.config.parse" in host_candidates:
        errors.append("host: unexpectedly includes network.config.parse")
    web_network_categories = set(samples["web_network"].get("categories") or [])
    if not {"web", "network"} <= web_network_categories:
        errors.append(f"web_network: missing web/network categories {sorted(web_network_categories)}")
    network_candidates = set(samples["web_network"].get("candidate_tools") or [])
    if "host.shell.exec" in network_candidates:
        errors.append("web_network: unexpectedly includes host.shell.exec")


def _inspect_tool_planner(plan_tools, validate_tool_plan, canonical_ids: set[str], errors: list[str]) -> None:
    from agent.runtime.tool_category_router import route_tool_scene

    def planned(text: str, safe_context: dict | None = None) -> dict:
        rule_scene = route_tool_scene(text)
        return plan_tools(
            user_input=text,
            safe_context=safe_context or {},
            rule_scene=rule_scene,
            available_catalog={"tools": sorted(canonical_ids)},
            model_config={"enabled": False},
        )

    samples = {
        "network_report": planned("帮我分析上传的华三配置，并整理成报告保存", {"uploaded_files": ["h3c.cfg"]}),
        "host": planned("本机 OS 的 IP 是多少"),
        "web_network": planned("根据官方文档看看这个 Cisco OSPF 配置有没有问题"),
    }
    for name, plan in samples.items():
        valid, messages = validate_tool_plan(plan, canonical_ids, user_input=name)
        if not valid:
            errors.append(f"{name}: planner invalid {messages}")
        candidates = set(plan.get("candidate_tools") or [])
        if not candidates <= canonical_ids:
            errors.append(f"{name}: planner non-canonical {sorted(candidates - canonical_ids)}")

    nr = samples["network_report"]
    if not {"workspace", "network", "report_data"} <= set(nr.get("categories") or []):
        errors.append("planner network_report missing workspace/network/report_data")
    if len(nr.get("tool_plan") or []) < 4:
        errors.append("planner network_report has too few steps")

    legacy = {"candidate_tools": ["file.read"], "tool_plan": [{"step": 1, "tool_candidates": ["file.read"]}]}
    if validate_tool_plan(legacy, canonical_ids, user_input="读文件")[0]:
        errors.append("planner validator accepted legacy tool id")
    invented = {"candidate_tools": ["network.device.login"], "tool_plan": [{"step": 1, "tool_candidates": ["network.device.login"]}]}
    if validate_tool_plan(invented, canonical_ids, user_input="登录设备")[0]:
        errors.append("planner validator accepted invented tool id")


if __name__ == "__main__":
    sys.exit(main())
