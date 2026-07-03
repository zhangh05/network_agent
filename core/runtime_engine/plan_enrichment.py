"""Deterministic plan enrichment for safe, read-only omissions.

The planner should emit complete tool arguments, but production LLMs still miss
obvious parameters. This module performs small, auditable enrichments that do
not change the selected tool or broaden permissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanEnrichment:
    node_id: str
    tool: str
    field: str
    value: Any
    reason: str


def enrich_dag_from_user_request(dag, user_input: str) -> list[PlanEnrichment]:
    """Mutate DAG args with safe inferred parameters and return audit events."""
    if dag is None:
        return []
    text = str(user_input or "")
    events: list[PlanEnrichment] = []
    for node in getattr(dag, "nodes", []) or []:
        if getattr(node, "tool", "") == "web.manage":
            events.extend(_enrich_weather_node(node, text))
    return events


def enrich_plan_nodes_from_user_request(nodes: list[Any], user_input: str) -> list[PlanEnrichment]:
    """Mutate planner nodes before DAG compilation for intent-level repairs.

    This is still deterministic and read/safe: it only corrects weather action
    selection and adds an inspection launcher when the user explicitly asked for
    CMDB inspection but the planner stopped at a CMDB lookup.
    """
    text = str(user_input or "")
    events: list[PlanEnrichment] = []
    if not nodes:
        return events

    for node in nodes:
        if getattr(node, "tool", "") == "web.manage":
            events.extend(_coerce_weather_action(node, text))

    has_inspection = any(getattr(node, "tool", "") == "inspection.manage" for node in nodes)
    device_lookup_ids = [
        str(getattr(node, "id", "") or "")
        for node in nodes
        if getattr(node, "tool", "") == "device.manage" and str(getattr(node, "id", "") or "")
    ]
    has_device_lookup = bool(device_lookup_ids)
    if _is_inspection_request(text) and not has_inspection:
        scope = _inspection_scope_from_text(text)
        node_id = _next_node_id(nodes)
        from .models import PlanNode
        nodes.append(PlanNode(
            id=node_id,
            tool="inspection.manage",
            args={"action": "run", "scope": scope},
            deps=device_lookup_ids,
        ))
        events.append(PlanEnrichment(
            node_id=node_id,
            tool="inspection.manage",
            field="node",
            value={"action": "run", "scope": scope},
            reason="inspection_request_requires_launcher",
        ))
    elif _is_inspection_request(text) and has_device_lookup and has_inspection:
        events.append(PlanEnrichment(
            node_id="",
            tool="inspection.manage",
            field="node",
            value="present",
            reason="inspection_launcher_already_present",
        ))
    return events


def _coerce_weather_action(node, text: str) -> list[PlanEnrichment]:
    args = getattr(node, "args", None)
    if not isinstance(args, dict):
        return []
    action = str(args.get("action") or "").lower()
    if action == "weather":
        return []
    if action != "search" or not _mentions_weather(text):
        return []
    args["action"] = "weather"
    location = infer_weather_location(text)
    days = infer_weather_days(text)
    if location:
        args["location"] = location
    if days:
        args["days"] = days
    return [
        PlanEnrichment(
            node_id=getattr(node, "id", ""),
            tool="web.manage",
            field="action",
            value="weather",
            reason="weather_request_should_use_structured_weather",
        )
    ]


def _enrich_weather_node(node, text: str) -> list[PlanEnrichment]:
    args = getattr(node, "args", None)
    if not isinstance(args, dict):
        return []
    if str(args.get("action") or "").lower() != "weather":
        return []

    events: list[PlanEnrichment] = []
    inferred_days = infer_weather_days(text)
    if inferred_days and int(args.get("days") or 1) < inferred_days:
        args["days"] = inferred_days
        events.append(PlanEnrichment(
            node_id=getattr(node, "id", ""),
            tool="web.manage",
            field="days",
            value=inferred_days,
            reason="weather_horizon_from_user_text",
        ))

    if not str(args.get("location") or "").strip():
        location = infer_weather_location(text)
        if location:
            args["location"] = location
            events.append(PlanEnrichment(
                node_id=getattr(node, "id", ""),
                tool="web.manage",
                field="location",
                value=location,
                reason="weather_location_from_user_text",
            ))
    return events


def _mentions_weather(text: str) -> bool:
    t = str(text or "").lower()
    return any(w in t for w in ("天气", "气温", "温度", "预报", "weather", "forecast"))


def _is_inspection_request(text: str) -> bool:
    t = str(text or "").lower()
    return ("巡检" in t or "inspection" in t) and ("cmdb" in t or "资产" in t or "区域" in t)


def _inspection_scope_from_text(text: str) -> dict[str, Any]:
    raw = str(text or "")
    m = re.search(r"CMDB\s*区域[「\"']?([^」\"'\\n]+)[」\"']?", raw, flags=re.I)
    if m:
        return {"region": _clean_scope_token(m.group(1))}
    m = re.search(r"CMDB\s*资产[「\"']?([^」\"'\\n]+)[」\"']?", raw, flags=re.I)
    if m:
        return {"search": _clean_scope_token(m.group(1)), "limit": 1}
    return {}


def _clean_scope_token(value: str) -> str:
    token = str(value or "").strip(" ，,。.!！？?：: \t")
    token = re.split(r"\s+", token)[0] if token else ""
    return token[:80]


def _next_node_id(nodes: list[Any]) -> str:
    used = {str(getattr(node, "id", "") or "") for node in nodes}
    i = len(nodes)
    while True:
        nid = f"n{i}"
        if nid not in used:
            return nid
        i += 1


def infer_weather_days(text: str) -> int | None:
    """Infer Open-Meteo forecast_days from Chinese/English date wording.

    The provider returns a horizon starting today. Therefore:
      - 明天 => 2 days, so tomorrow is included
      - 后天 => 3 days
      - 未来十天 / 10天 => 10 days
    """
    t = str(text or "").lower()
    if not t:
        return None
    if "后天" in t:
        return 3
    if "明天" in t or "tomorrow" in t:
        return 2
    if "一周" in t or "7天" in t or "七天" in t or "week" in t:
        return 7
    m = re.search(r"(?:未来|后续|接下来|future|next)?\s*(\d{1,2})\s*(?:天|day|days)", t)
    if m:
        return max(1, min(int(m.group(1)), 10))
    cn = {
        "十": 10, "九": 9, "八": 8, "七": 7, "六": 6,
        "五": 5, "四": 4, "三": 3, "两": 2, "二": 2, "一": 1,
    }
    m = re.search(r"(?:未来|后续|接下来)?\s*([一二两三四五六七八九十])\s*天", t)
    if m:
        return cn.get(m.group(1))
    if "未来" in t or "预报" in t or "forecast" in t:
        return 3
    return None


def infer_weather_location(text: str) -> str:
    """Best-effort city/location extraction for weather requests."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    patterns = [
        r"(?:查看|查询|查|看|帮我看|帮我查)?\s*(?:未来|后续|接下来)?\s*(?:\d{1,2}|[一二两三四五六七八九十])?\s*(?:天|日)?\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·\-\s]{1,30})\s*(?:天气|气温|温度|预报)",
        r"(?:weather|forecast)\s+(?:for\s+)?([A-Za-z][A-Za-z\-\s]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, raw, flags=re.IGNORECASE)
        if not m:
            continue
        loc = _clean_location(m.group(1))
        if loc:
            return loc
    return ""


def _clean_location(value: str) -> str:
    loc = str(value or "").strip(" ，,。.!！？?：:")
    noise = (
        "查看", "查询", "帮我", "帮我看", "帮我查", "未来", "后续", "接下来",
        "明天", "后天", "今天", "天气", "气温", "温度", "预报",
        "一天", "两天", "二天", "三天", "四天", "五天", "六天", "七天", "八天", "九天", "十天",
    )
    changed = True
    while changed:
        changed = False
        for token in noise:
            if loc.startswith(token):
                loc = loc[len(token):].strip()
                changed = True
    loc = re.sub(r"^\d{1,2}\s*(?:天|日)", "", loc).strip()
    return loc[:40]
