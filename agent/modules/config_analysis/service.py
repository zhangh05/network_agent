# agent/modules/config_analysis/service.py
"""Unified config analysis module service.

Directory-level entrypoint for all config-related operations.
Provides heuristic parsing for common network configuration formats.
"""

from __future__ import annotations

import re
from typing import Any


VALID_ACTIONS = {
    "parse",
    "translate",
    "extract_interfaces",
    "extract_routes",
    "diff",
    "summarize",
}


def run_config_analysis(
    action: str,
    *,
    workspace_id: str = "",
    filepath: str = "",
    file_id: str = "",
    source_config: str = "",
    target_vendor: str = "",
    source_vendor: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Unified config analysis dispatcher."""

    # Resolve source_config from file_id/filepath if not provided directly.
    if not source_config and file_id:
        try:
            from storage.file_store import read_file_content
            source_config = read_file_content(workspace_id, file_id)
        except Exception as exc:
            return _source_config_error("invalid_file_id", str(exc))
    if not source_config and filepath:
        try:
            source_config = _read_workspace_text_file(workspace_id, filepath)
        except Exception as exc:
            return _source_config_error("invalid_filepath", str(exc))
    action = (action or "").strip()

    if action not in VALID_ACTIONS:
        return {
            "ok": False, "tool_id": "config.manage", "status": "failed",
            "summary": f"unsupported config action: {action}",
            "errors": ["unsupported_action"],
        }

    if action == "translate":
        from agent.modules.config_translation.service import translate_config
        return translate_config(
            source_config=source_config,
            source_vendor=source_vendor,
            target_vendor=target_vendor,
            workspace_id=workspace_id,
            session_id=str(kwargs.get("session_id", "")),
            run_id=str(kwargs.get("run_id", "")),
            source_file_id=file_id,
        )

    if action == "parse":
        missing = _missing_source_config(source_config)
        if missing:
            return missing
        result = parse_config(source_config, vendor=source_vendor)
        return {
            "ok": True, "tool_id": "config.manage", "status": "succeeded",
            "summary": f"解析完成：{result.get('line_count', 0)} 行，"
                       f"{len(result.get('interfaces', []))} 个接口，"
                       f"{len(result.get('routes', []))} 条路由。",
            **result,
        }

    if action == "extract_interfaces":
        missing = _missing_source_config(source_config)
        if missing:
            return missing
        parsed = parse_config(source_config, vendor=source_vendor)
        interfaces = parsed.get("interfaces", [])
        return {
            "ok": True, "tool_id": "config.manage", "status": "succeeded",
            "summary": f"提取到 {len(interfaces)} 个接口。",
            "interfaces": interfaces,
        }

    if action == "extract_routes":
        missing = _missing_source_config(source_config)
        if missing:
            return missing
        parsed = parse_config(source_config, vendor=source_vendor)
        routes = parsed.get("routes", [])
        return {
            "ok": True, "tool_id": "config.manage", "status": "succeeded",
            "summary": f"提取到 {len(routes)} 条路由。",
            "routes": routes,
        }

    if action == "diff":
        before = kwargs.get("before", "")
        after = kwargs.get("after", "")
        result = diff_configs(before, after)
        return {
            "ok": True, "tool_id": "config.manage", "status": "succeeded",
            "summary": f"差异：+{len(result.get('added', []))} -{len(result.get('removed', []))} ~{len(result.get('changed', []))}",
            **result,
        }

    if action == "summarize":
        missing = _missing_source_config(source_config)
        if missing:
            return missing
        parsed = parse_config(source_config, vendor=source_vendor)
        summary = summarize_config(parsed)
        return {
            "ok": True, "tool_id": "config.manage", "status": "succeeded",
            "summary": summary,
        }

    return {
        "ok": False, "tool_id": "config.manage", "status": "not_implemented",
        "summary": f"Action '{action}' is not implemented.",
        "errors": [f"{action}_not_implemented"],
    }


def _source_config_error(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool_id": "config.manage",
        "status": "failed",
        "summary": message[:200],
        "errors": [code],
    }


def _missing_source_config(source_config: str) -> dict[str, Any] | None:
    if source_config and source_config.strip():
        return None
    return {
        "ok": False,
        "tool_id": "config.manage",
        "status": "failed",
        "summary": "需要提供源配置文本、file_id 或 workspace 内 filepath。",
        "errors": ["missing_source_config"],
    }


def _read_workspace_text_file(workspace_id: str, filepath: str) -> str:
    from storage.paths import workspace_root
    from workspace.ids import validate_workspace_id

    ws_id = validate_workspace_id(workspace_id)
    root = workspace_root(ws_id).resolve()
    candidate = (root / filepath).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("filepath must stay inside the workspace")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"file not found: {filepath}")
    data = candidate.read_bytes()
    if len(data) > 512_000:
        raise ValueError("source_config_too_large")
    return data.decode("utf-8", errors="replace")


# ── Heuristic config parsing ────────────────────────────────────────

_INTERFACE_PATTERNS = [
    re.compile(r"^interface\s+(\S+)", re.IGNORECASE),
]

_ROUTE_PATTERNS = [
    re.compile(r"^ip\s+route-static\s+(.*)", re.IGNORECASE),
    re.compile(r"^ip\s+route\s+(.*)", re.IGNORECASE),
    re.compile(r"^ipv6\s+route\s+(.*)", re.IGNORECASE),
    re.compile(r"^route-static\s+(.*)", re.IGNORECASE),
]

_VLAN_PATTERNS = [
    re.compile(r"^vlan\s+(\d[\d,\s-]*)", re.IGNORECASE),
    re.compile(r"^vlan\s+batch\s+(.*)", re.IGNORECASE),
]

_VENDOR_HINTS = {
    "huawei": ["sysname", "undo", "aaa", "interface GigabitEthernet", "interface Vlanif", "ip route-static"],
    "h3c": ["sysname", "undo", "interface Ten-GigabitEthernet", "interface Vlan-interface"],
    "cisco": ["hostname", "interface GigabitEthernet", "ip route ", "router ospf", "router bgp"],
    "juniper": ["set interfaces", "set routing-options", "set protocols"],
}


def parse_config(text: str, vendor: str = "") -> dict[str, Any]:
    """Heuristic parse of a network config text block."""
    text = text or ""
    lines = text.split("\n")
    vendor = (vendor or "").lower().strip() or _guess_vendor(text)

    interfaces: list[dict] = []
    routes: list[dict] = []
    vlans: list[str] = []
    warnings: list[str] = []
    current_iface: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!") or stripped == "#":
            if current_iface:
                interfaces.append(current_iface)
                current_iface = None
            continue

        # Interface detection
        for pat in _INTERFACE_PATTERNS:
            m = pat.match(stripped)
            if m:
                if current_iface:
                    interfaces.append(current_iface)
                current_iface = {"name": m.group(1), "lines": [stripped], "ip": None, "description": ""}
                break
        else:
            if current_iface:
                current_iface["lines"].append(stripped)
                ip_match = re.match(r"ip\s+address\s+(\S+)\s+(\S+)", stripped, re.IGNORECASE)
                if ip_match:
                    current_iface["ip"] = f"{ip_match.group(1)}/{ip_match.group(2)}"
                desc_match = re.match(r"description\s+(.*)", stripped, re.IGNORECASE)
                if desc_match:
                    current_iface["description"] = desc_match.group(1).strip()

        # Route detection
        for pat in _ROUTE_PATTERNS:
            m = pat.match(stripped)
            if m:
                routes.append({"raw": stripped, "detail": m.group(1).strip()})
                break

        # VLAN detection
        for pat in _VLAN_PATTERNS:
            m = pat.match(stripped)
            if m:
                vlans.append(m.group(1).strip())
                break

    if current_iface:
        interfaces.append(current_iface)

    return {
        "vendor": vendor,
        "line_count": len(lines),
        "interfaces": interfaces,
        "routes": routes,
        "vlans": vlans,
        "warnings": warnings,
    }


def extract_interfaces(text: str, vendor: str = "") -> list[dict]:
    """Extract interface list from config text."""
    return parse_config(text, vendor=vendor).get("interfaces", [])


def extract_routes(text: str, vendor: str = "") -> list[dict]:
    """Extract route list from config text."""
    return parse_config(text, vendor=vendor).get("routes", [])


def diff_configs(before: str, after: str) -> dict[str, Any]:
    """Simple line-based config diff."""
    before_lines = set((before or "").strip().split("\n"))
    after_lines = set((after or "").strip().split("\n"))
    added = sorted(after_lines - before_lines)
    removed = sorted(before_lines - after_lines)
    return {
        "added": [l for l in added if l.strip()],
        "removed": [l for l in removed if l.strip()],
        "changed": [],
    }


def summarize_config(parsed: dict) -> str:
    """Generate a concise summary of a parsed config."""
    parts = [f"厂商: {parsed.get('vendor', 'unknown')}"]
    parts.append(f"总行数: {parsed.get('line_count', 0)}")
    ifaces = parsed.get("interfaces", [])
    if ifaces:
        parts.append(f"接口数: {len(ifaces)}")
        named = [i["name"] for i in ifaces[:5]]
        parts.append(f"接口示例: {', '.join(named)}")
    routes = parsed.get("routes", [])
    if routes:
        parts.append(f"路由条目: {len(routes)}")
    vlans = parsed.get("vlans", [])
    if vlans:
        parts.append(f"VLAN: {', '.join(vlans[:5])}")
    return "; ".join(parts)


def _guess_vendor(text: str) -> str:
    """Guess vendor from config text heuristics."""
    lower = text.lower()
    scores: dict[str, int] = {}
    for vendor, hints in _VENDOR_HINTS.items():
        scores[vendor] = sum(1 for h in hints if h.lower() in lower)
    if not scores:
        return "unknown"
    best = max(scores, key=lambda v: scores[v])
    return best if scores[best] > 0 else "unknown"
