"""Deterministic quality evaluation for capability routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from .router import route_capabilities


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    user_input: str
    top1: str
    required: tuple[str, ...]
    allowed: tuple[str, ...]
    safe_context: dict[str, Any] = field(default_factory=dict)
    scene: dict[str, Any] = field(default_factory=dict)


DEFAULT_ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase("config_zh", "把这份华为配置翻译成 Cisco", "config_translation", ("config_translation",), ("config_translation",)),
    RoutingCase("config_en", "translate this H3C configuration to Cisco", "config_translation", ("config_translation",), ("config_translation",)),
    RoutingCase("pcap_zh", "分析抓包里的 TCP 重传", "pcap_analysis", ("pcap_analysis",), ("pcap_analysis",)),
    RoutingCase("pcap_en", "inspect this pcapng packet capture", "pcap_analysis", ("pcap_analysis",), ("pcap_analysis",)),
    RoutingCase("knowledge_zh", "查询知识库里的 OSPF 邻居说明", "knowledge_qa", ("knowledge_qa",), ("knowledge_qa",)),
    RoutingCase("knowledge_en", "search the docs for BGP route selection", "knowledge_qa", ("knowledge_qa",), ("knowledge_qa",)),
    RoutingCase("memory_zh", "记得我之前的设备偏好吗", "memory_lookup", ("memory_lookup",), ("memory_lookup",)),
    RoutingCase("memory_en", "search memory for my previous decision", "memory_lookup", ("memory_lookup",), ("memory_lookup",)),
    RoutingCase("report_zh", "整理并导出报告", "report_drafting", ("report_drafting",), ("report_drafting",)),
    RoutingCase("report_en", "render a markdown report", "report_drafting", ("report_drafting",), ("report_drafting",)),
    RoutingCase("runtime_zh", "运行环境健康自检", "runtime_diagnostics", ("runtime_diagnostics",), ("runtime_diagnostics",)),
    RoutingCase("runtime_en", "check runtime diagnostics", "runtime_diagnostics", ("runtime_diagnostics",), ("runtime_diagnostics",)),
    RoutingCase("workspace_zh", "读取工作区文件", "workspace_read", ("workspace_read",), ("workspace_read",)),
    RoutingCase("workspace_en", "preview the workspace artifact", "workspace_read", ("workspace_read",), ("workspace_read",)),
    RoutingCase(
        "ambiguous_artifact",
        "帮我看看这个有没有问题",
        "workspace_read",
        ("workspace_read",),
        ("workspace_read",),
        safe_context={"artifact_refs": [{"artifact_id": "art_1"}]},
    ),
    RoutingCase(
        "continuation_memory",
        "继续上次那个",
        "memory_lookup",
        ("memory_lookup",),
        ("memory_lookup",),
        scene={"needs_memory": True, "is_memory_task": True, "reason": "follow_up"},
    ),
    RoutingCase(
        "factual_scene",
        "这个协议为什么这样工作",
        "knowledge_qa",
        ("knowledge_qa",),
        ("knowledge_qa",),
        scene={"needs_knowledge": True, "is_factual_query": True},
    ),
    RoutingCase("safe_fallback", "你好", "workspace_read", ("workspace_read",), ("workspace_read",)),
)


def evaluate_router(cases: tuple[RoutingCase, ...] | list[RoutingCase]) -> dict:
    failures: list[dict] = []
    required_total = 0
    required_hits = 0
    top1_hits = 0
    unexpected_total = 0
    selected_total = 0

    for case in cases:
        scene = SimpleNamespace(**case.scene) if case.scene else None
        route = route_capabilities(
            case.user_input,
            scene=scene,
            safe_context=case.safe_context,
        )
        selected = list(route.capability_ids)
        selected_set = set(selected)
        required_set = set(case.required)
        allowed_set = set(case.allowed)
        required_total += len(required_set)
        required_hits += len(required_set & selected_set)
        selected_total += len(selected_set)
        unexpected = sorted(selected_set - allowed_set)
        unexpected_total += len(unexpected)
        top1_ok = bool(selected and selected[0] == case.top1)
        if top1_ok:
            top1_hits += 1
        missing = sorted(required_set - selected_set)
        if missing or unexpected or not top1_ok:
            failures.append({
                "case_id": case.case_id,
                "selected": selected,
                "expected_top1": case.top1,
                "missing": missing,
                "unexpected": unexpected,
                "route": route.to_dict(),
            })

    case_count = len(cases)
    return {
        "router_version": "capability_router.v2",
        "case_count": case_count,
        "top1_accuracy": top1_hits / case_count if case_count else 0.0,
        "required_capability_recall": required_hits / required_total if required_total else 0.0,
        "unexpected_capability_rate": unexpected_total / selected_total if selected_total else 0.0,
        "failure_count": len(failures),
        "failures": failures,
    }
