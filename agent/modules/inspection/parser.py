"""agent.modules.inspection.parser

Lightweight rule-based parsing for the supported checks. We do
NOT pull in ``pdparse`` or a heavy regex library — every parser is
a handful of compiled patterns plus a few hand-written lines.

Return shape is a ``dict`` of metrics + a list of :class:`Finding`
objects. Parsers must NEVER raise; on malformed input they return
a single ``info`` finding so the LLM and the user both see that
manual review is required.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .models import Finding


_RE_PCT_IN_FIRST = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_RE_PCT_RANGE = re.compile(r"(\d{1,3})\s*%\s*[-~]\s*(\d{1,3})\s*%")

# Cisco "show processes cpu": CPU utilization for five seconds: 12%/3%; one minute: 8%; five minutes: 9%
_RE_CISCO_CPU = re.compile(
    r"(?:CPU utilization|utilization for five seconds)[^:\n]*:\s*(?:(\d+)%[^,\n]*[,/]?\s*)?(\d+)%[^,\n]*(?:one minute|1 min)[^:\n]*:\s*(\d+)%[^,\n]*(?:five minutes|5 min)[^:\n]*:\s*(\d+)%",
    re.I,
)
_RE_HUAWEI_CPU = re.compile(
    r"(?:CPU utilization|cpu usage)[^:\n]*?:\s*(?:[^\n]*?\s)?(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)

# Memory: capture the first "<int>%" we find on a memory-bearing line.
# We accept:
#   - "Memory Using Percentage Is: 89%"
#   - "Processor Pool Total: ... Used: 320.50 MB (15%)"
#   - "Used memory: 1.6G (16%)"
_RE_MEMORY_PCT = re.compile(
    r"(?:memory|mem)[^\n]*?(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
# Cisco: "Processor Pool Total: 2048.00 MB Used: 320.50 MB (15%)"
_RE_CISCO_MEM = re.compile(
    r"Used:[\s\d\.]+\s*MB\s*\((\d{1,3})\s*%\)",
    re.I,
)
_RE_HUAWEI_MEM = re.compile(
    r"Memory\s+(?:[Uu]tilization|Using)[^\n]*?(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)


def _finding(severity: str, title: str, detail: str,
             asset_id: str = "", check_id: str = "",
             evidence: str = "") -> Finding:
    return Finding(
        finding_id=f"fdg_{uuid.uuid4().hex[:10]}",
        severity=severity,
        title=title,
        detail=detail,
        evidence=evidence[:1500],
        asset_id=asset_id,
        check_id=check_id,
    )


# ── cpu ───────────────────────────────────────────────────────────────────

def parse_cpu(parser_key: str, output: str, *,
              asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    """Return ``(metric, findings)``.

    Metric shape::

        {"value_pct": float, "samples": {"5s":..., "1m":..., "5m":...}}

    Cisco carries 5s/1m/5m figures; Huawei/H3C carry one. We
    threshold at 80/90 pct (warning/critical) per the task contract.
    """
    out: dict[str, Any] = {}
    findings: list[Finding] = []
    text = output or ""

    m = _RE_CISCO_CPU.search(text)
    if m:
        # groups: full5s, idle5s (skip), 1m, 5m
        try:
            one = float(m.group(3))
            five = float(m.group(4))
            value = max(one, five)
            out = {"value_pct": value, "samples": {"1m": one, "5m": five}}
        except (ValueError, TypeError):
            pass

    if "value_pct" not in out:
        m2 = _RE_PCT_RANGE.search(text) or _RE_HUAWEI_CPU.search(text)
        if m2:
            try:
                value = float(m2.group(1))
                out = {"value_pct": value, "samples": {}}
            except (ValueError, TypeError):
                pass

    if "value_pct" not in out:
        findings.append(_finding(
            "info", "未结构化解析 CPU 输出",
            "命令输出未能解析 CPU 百分比，请人工查看原始输出。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return out, findings

    val = out["value_pct"]
    if val >= 90:
        findings.append(_finding(
            "critical", f"CPU 利用率 {val:.0f}% ≥ 90%",
            f"持续 CPU 利用率 {val:.0f}%，达到 critical 阈值 90%。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    elif val >= 80:
        findings.append(_finding(
            "warning", f"CPU 利用率 {val:.0f}% ≥ 80%",
            f"持续 CPU 利用率 {val:.0f}%，达到 warning 阈值 80%。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    return out, findings


# ── memory ─────────────────────────────────────────────────────────────────

def parse_memory(parser_key: str, output: str, *,
                 asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    out: dict[str, Any] = {}
    findings: list[Finding] = []
    text = output or ""

    m = (_RE_CISCO_MEM.search(text)
         or _RE_HUAWEI_MEM.search(text)
         or _RE_MEMORY_PCT.search(text))
    if m:
        try:
            val = float(m.group(1))
            out = {"value_pct": val}
        except (ValueError, TypeError):
            pass

    if "value_pct" not in out:
        findings.append(_finding(
            "info", "未结构化解析内存输出",
            "命令输出未能解析内存百分比，请人工查看原始输出。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return out, findings

    val = out["value_pct"]
    if val >= 90:
        findings.append(_finding(
            "critical", f"内存利用率 {val:.0f}% ≥ 90%",
            "持续内存利用率超过 90%，存在 OOM 风险。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    elif val >= 80:
        findings.append(_finding(
            "warning", f"内存利用率 {val:.0f}% ≥ 80%",
            "持续内存利用率超过 80%。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    return out, findings


# ── interfaces ────────────────────────────────────────────────────────────

_RE_IFACE_BRIEF_LINE = re.compile(
    r"^\s*(?P<name>[\w\-/\.\:]+)\s+(?P<status>\S+)\s+(?P<protocol>\S+)",
    re.M | re.I,
)


def _iface_is_down_line(text: str) -> int:
    """Count interface-brief lines whose status/protocol column is
    down/admindown. Loose by design — the canonical brief table is
    vendor-specific, but every vendor ends a row with status+protocol
    tokens; we tolerate any name pattern."""
    count = 0
    for m in _RE_IFACE_BRIEF_LINE.finditer(text):
        status = m.group("status").lower()
        protocol = m.group("protocol").lower()
        if status in {"down", "administratively down", "admindown", "down*"} \
                or protocol in {"down", "admindown"}:
            count += 1
    return count
_RE_IFACE_CRC = re.compile(r"\b(crc\s*errors?|crc\s*error|CRC\s*Errors?):\s*(\d+)\b", re.I)
_RE_IFACE_DROP = re.compile(r"\b(?:output\s*drops?|drops?|packet\s*drops?):\s*(\d+)\b", re.I)


def parse_interface_brief(parser_key: str, output: str, *,
                           asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = output or ""

    down_count = _iface_is_down_line(text)
    total_count = up_count = 0
    for m in _RE_IFACE_BRIEF_LINE.finditer(text):
        total_count += 1
        status = m.group("status").lower()
        protocol = m.group("protocol").lower()
        if status in {"up", "up*"} and protocol in {"up", "up*"}:
            up_count += 1

    metric = {"total": total_count, "up": up_count, "down": down_count}

    if total_count == 0:
        findings.append(_finding(
            "info", "未结构化解析接口摘要",
            "接口摘要输出没有识别到接口行，请人工查看原始输出。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return metric, findings

    if down_count > 0:
        findings.append(_finding(
            "critical" if down_count > max(1, total_count // 10) else "warning",
            f"{down_count} 个接口处于 down 状态",
            f"接口摘要共 {total_count} 条目，其中 {down_count} down / {up_count} up。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    return metric, findings


def parse_interface_error(parser_key: str, output: str, *,
                          asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = output or ""

    crc_total = sum(int(m.group(2) or 0) for m in _RE_IFACE_CRC.finditer(text))
    drop_total = sum(int(m.group(1) or 0) for m in _RE_IFACE_DROP.finditer(text))
    metric = {"crc_errors": crc_total, "drops": drop_total}

    if crc_total == 0 and drop_total == 0:
        findings.append(_finding(
            "info", "未识别接口错包 / 丢包统计",
            "输出中未找到非零 CRC / drop 计数；若该厂商不支持此命令，"
            "请考虑在工具列表里调低该检查的优先级。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return metric, findings

    if crc_total > 0 or drop_total > 0:
        findings.append(_finding(
            "warning",
            f"接口错包 / 丢包非零（crc={crc_total}, drop={drop_total}）",
            "至少一个接口有 CRC 错误或丢包计数 > 0。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1500],
        ))
    return metric, findings


# ── routing ────────────────────────────────────────────────────────────────


def parse_ospf_peer(parser_key: str, output: str, *,
                    asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = output or ""

    # Count FULL neighbors vs non-FULL neighbors (rough)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    peer_lines = [ln for ln in lines if re.search(r"\b\d+\.\d+\.\d+\.\d+\b", ln)]
    total = len(peer_lines)

    full = sum(1 for ln in peer_lines if re.search(r"\bFULL\b", ln, re.I))
    down = total - full

    metric = {"neighbors_total": total, "neighbors_full": full, "neighbors_not_full": down}

    if total == 0:
        findings.append(_finding(
            "info", "未识别 OSPF 邻居",
            "没有解析到 OSPF peer 行，请人工检查输出。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return metric, findings

    if down > 0:
        findings.append(_finding(
            "warning",
            f"{down} 个 OSPF 邻居未达 FULL",
            f"OSPF 邻居共 {total} 个，其中 FULL {full} 个、非 FULL {down} 个。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1500],
        ))
    return metric, findings


def parse_bgp_summary(parser_key: str, output: str, *,
                     asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = output or ""

    # show ip bgp summary / display bgp peer ipv4 unicast 输出含邻居行
    lines = [ln for ln in text.splitlines() if re.search(r"\b\d+\.\d+\.\d+\.\d+\b", ln)]
    total = len(lines)

    down_lines = [ln for ln in lines if re.search(r"\bIdle\b|\bActive\b|\bConnect\b", ln, re.I)]
    down = len(down_lines)

    metric = {"neighbors_total": total, "down": down}

    if total == 0:
        findings.append(_finding(
            "info", "未识别 BGP 邻居",
            "BGP summary 没有解析到邻居行，请人工检查输出。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
        return metric, findings

    if down > 0:
        findings.append(_finding(
            "warning",
            f"{down} 个 BGP 邻居未达 Established",
            f"BGP 邻居共 {total}，其中未建立（Idle/Active/Connect）{down} 条。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1500],
        ))
    return metric, findings


def parse_route_summary(parser_key: str, output: str, *,
                       asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = output or ""

    route_total = 0
    for ln in text.splitlines():
        # 接受 "Total routes..." / "routes: 123" 等
        m = re.search(r"(?:[Tt]otal\s+routes|Routes\s*:?)\s*[:=]?\s*(\d+)", ln)
        if m:
            try:
                route_total = int(m.group(1))
                break
            except ValueError:
                continue

    metric = {"route_total": route_total}

    if route_total == 0:
        findings.append(_finding(
            "info", "未识别路由表总数",
            "未匹配到 'Total routes' / 'Routes:' 等行；请人工查看。",
            asset_id=asset_id, check_id=check_id,
            evidence=text[:1000],
        ))
    return metric, findings


# ── config backup (artifact + diff) ────────────────────────────────────────

def parse_current_config(parser_key: str, output: str, *,
                          asset_id: str = "", check_id: str = "",
                          previous_output: str = "") -> tuple[dict, list]:
    """For config_backup we return:

      - ``config_size_lines`` (int)
      - ``diff_lines`` (int) — only if ``previous_output`` non-empty
      - findings, if any
    """
    findings: list[Finding] = []
    text = output or ""
    prev = previous_output or ""

    new_lines = text.splitlines()
    metric: dict[str, Any] = {"config_size_lines": len(new_lines)}

    if prev:
        # Cheap symmetric diff (no external dep)
        prev_lines = prev.splitlines()
        added = sorted(set(new_lines) - set(prev_lines))
        removed = sorted(set(prev_lines) - set(new_lines))
        diff_lines = max(len(added), len(removed))
        metric.update({
            "diff_lines": diff_lines,
            "added_lines": len(added),
            "removed_lines": len(removed),
        })
        if added or removed:
            findings.append(_finding(
                "warning",
                f"配置变更：新增 {len(added)} 行 / 删除 {len(removed)} 行",
                "本次配置与上次保存的版本存在差异。",
                asset_id=asset_id, check_id=check_id,
                evidence="\n".join(([f"+ {l}" for l in added[:10]] +
                                     [f"- {l}" for l in removed[:10]]))[:1500],
            ))
    else:
        findings.append(_finding(
            "info", "首次保存配置",
            "没有上一次配置快照，本次新增为首次基线。",
            asset_id=asset_id, check_id=check_id,
            evidence="",
        ))
    return metric, findings


# ── version (basic profile) ───────────────────────────────────────────────

def parse_version(parser_key: str, output: str, *,
                  asset_id: str = "", check_id: str = "") -> tuple[dict, list]:
    findings: list[Finding] = []
    text = (output or "").strip()
    if not text:
        return {}, [_finding("warning", "设备版本输出为空", "show/display version 输出为空。",
                              asset_id=asset_id, check_id=check_id)]
    # extract something that looks like a version line (e.g. "Version 7.1.064")
    m = re.search(r"[Vv]ersion[\s:]*([\w\.\-]+)", text)
    metric: dict[str, Any] = {}
    if m:
        metric["version_string"] = m.group(1)
    metric["raw_size"] = len(text)
    return metric, findings


# ── dispatcher ────────────────────────────────────────────────────────────

PARSERS = {
    "version": parse_version,
    "cpu": parse_cpu,
    "memory": parse_memory,
    "interface_brief": parse_interface_brief,
    "interface_error": parse_interface_error,
    "ospf_peer": parse_ospf_peer,
    "bgp_summary": parse_bgp_summary,
    "route_summary": parse_route_summary,
    "current_config": parse_current_config,
}


def run_parser(parser_key: str, output: str, *,
               asset_id: str = "", check_id: str = "",
               **kwargs) -> tuple[dict, list]:
    """Dispatch by parser_key. Unknown parser ⇒ empty metric + 1 info finding."""
    fn = PARSERS.get(parser_key)
    if fn is None:
        return {}, [_finding(
            "info", f"无解析器: {parser_key}",
            f"parser_key={parser_key!r} 没有实现解析逻辑；将以原始输出形式展示。",
            asset_id=asset_id, check_id=check_id,
        )]
    try:
        return fn(parser_key, output, asset_id=asset_id, check_id=check_id, **kwargs)
    except Exception as exc:  # parser never raises
        # v3.9.14: log full stack — user-facing finding stays terse.
        import logging as _parser_log
        _parser_log.getLogger(__name__).warning(
            "[inspection.parser] %s crashed for check %s on asset %s",
            parser_key, check_id, asset_id,
            exc_info=True,
        )
        return {}, [_finding(
            "warning", "解析器异常",
            f"parser={parser_key}: {str(exc)[:200]}",
            asset_id=asset_id, check_id=check_id,
        )]  # parser_never_raises; return degraded result
