"""Deterministic network-state extraction for assurance.

The inspection artifact remains the evidence source.  This module only turns
well-known command output into typed facts; unknown output is left untouched
for human/LLM review and is never promoted to a fact.
"""

from __future__ import annotations

import re
from typing import Any


STRUCTURED_SCHEMA_VERSION = 2

_PROMPT_COMMAND = re.compile(r"^\s*<[^>]+>\s*(dis(?:play)?\s+.+?)\s*$", re.IGNORECASE)
_BARE_COMMAND = re.compile(r"^\s*(dis(?:play)?\s+\S.*?)\s*$", re.IGNORECASE)


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip()).strip("_").lower()


def split_command_output(text: str) -> list[tuple[str, str]]:
    """Split a terminal transcript into ``(command, output)`` sections."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    sections: list[tuple[str, list[str]]] = []
    current_command = ""
    current_lines: list[str] = []
    for index, line in enumerate(normalized.splitlines()):
        match = _PROMPT_COMMAND.match(line)
        if match is None and not current_command:
            match = _BARE_COMMAND.match(line)
        if match:
            if current_command:
                sections.append((current_command, current_lines))
            current_command = " ".join(match.group(1).lower().split())
            current_lines = []
        elif current_command:
            current_lines.append(line)
    if current_command:
        sections.append((current_command, current_lines))
    return [(command, "\n".join(lines).strip()) for command, lines in sections]


def _fact(key: str, value: Any, *, category: str, resource_type: str,
          resource_id: str, policy: str = "must_equal", severity: str = "warning",
          unit: str = "", warning: float | None = None,
          critical: float | None = None, direction: str = "max",
          command: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": key, "value": value, "category": category,
        "resource_type": resource_type, "resource_id": resource_id,
        "policy": policy, "severity": severity, "command": command,
    }
    if unit:
        result["unit"] = unit
    if warning is not None:
        result["warning"] = warning
    if critical is not None:
        result["critical"] = critical
    if policy == "threshold":
        result["direction"] = direction
    return result


def _parse_version(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    match = re.search(r"Comware Software,\s*Version\s+([^\n]+)", text, re.I)
    if match:
        facts.append(_fact("system.software.version", match.group(1).strip(), category="identity",
                           resource_type="device", resource_id="system", severity="critical", command=command))
    return facts


def _parse_serial(command: str, text: str) -> list[dict[str, Any]]:
    match = re.search(r"(?:DEVICE_SERIAL_NUMBER|SN)\s*:\s*([^\s]+)", text, re.I)
    return [_fact("system.serial", match.group(1), category="identity", resource_type="device",
                  resource_id="system", severity="critical", command=command)] if match else []


def _parse_cpu(command: str, text: str) -> list[dict[str, Any]]:
    labels = ((r"(\d+)%\s+in last 5 seconds", "5s"),
              (r"(\d+)%\s+in last 1 minute", "1m"),
              (r"(\d+)%\s+in last 5 minutes", "5m"))
    facts = []
    for pattern, window in labels:
        match = re.search(pattern, text, re.I)
        if match:
            facts.append(_fact(f"health.cpu.{window}.percent", int(match.group(1)), category="health",
                               resource_type="cpu", resource_id="system", policy="threshold",
                               severity="warning", unit="percent", warning=80, critical=95, command=command))
    return facts


def _parse_memory(command: str, text: str) -> list[dict[str, Any]]:
    match = re.search(r"^Mem:\s+\d+\s+\d+\s+\d+.*?([\d.]+)%\s*$", text, re.I | re.M)
    if not match:
        return []
    return [_fact("health.memory.free_ratio.percent", float(match.group(1)), category="health",
                  resource_type="memory", resource_id="system", policy="threshold", severity="warning",
                  unit="percent", warning=20, critical=10, direction="min", command=command)]


def _parse_temperature(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    pattern = re.compile(r"^\s*(\S+)\s+(.+?)\s+(\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s*$", re.M)
    for slot, sensor, value, _lower, warning, alarm in pattern.findall(text):
        sensor_id = _slug(f"{slot}.{sensor}")
        facts.append(_fact(f"sensor.temperature.{sensor_id}.celsius", int(value), category="health",
                           resource_type="temperature_sensor", resource_id=sensor_id, policy="threshold",
                           unit="celsius", warning=float(warning), critical=float(alarm), command=command))
    return facts


def _parse_component(command: str, text: str, component: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for component_id, status in re.findall(r"^\s*(\d+)\s+(Normal|Absent|Fault|Failed|Warning)\s*$", text, re.I | re.M):
        facts.append(_fact(f"component.{component}.{component_id}.status", status.lower(), category="health",
                           resource_type=component, resource_id=component_id, severity="critical", command=command))
    return facts


def _parse_interfaces(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    pattern = re.compile(r"^\s*(\S+)\s+(up|down|\*down)\s+(up|down)\s+(\S+)", re.I | re.M)
    for name, physical, protocol, address in pattern.findall(text):
        interface_id = _slug(name)
        facts.extend([
            _fact(f"interface.{interface_id}.physical", physical.lower(), category="interface",
                  resource_type="interface", resource_id=name, severity="critical", command=command),
            _fact(f"interface.{interface_id}.protocol", protocol.lower(), category="interface",
                  resource_type="interface", resource_id=name, severity="critical", command=command),
        ])
        if address != "--":
            facts.append(_fact(f"interface.{interface_id}.address", address, category="interface",
                               resource_type="interface", resource_id=name, severity="critical", command=command))
    return facts


def _parse_routes(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    totals = re.search(r"Destinations\s*:\s*(\d+)\s+Routes\s*:\s*(\d+)", text, re.I)
    if totals:
        facts.append(_fact("routing.route_count", int(totals.group(2)), category="routing",
                           resource_type="routing_table", resource_id="ipv4", policy="baseline_delta",
                           unit="routes", warning=0.2, critical=0.5, command=command))
    route_pattern = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+/\d+)\s+(\S+)\s+\d+\s+\S+\s+(\S+)\s+(\S+)", re.M)
    for prefix, protocol, next_hop, interface in route_pattern.findall(text):
        rid = _slug(prefix)
        value = {"protocol": protocol.upper(), "next_hop": next_hop, "interface": interface}
        facts.append(_fact(f"route.{rid}", value, category="routing", resource_type="route",
                           resource_id=prefix, severity="critical", command=command))
    return facts


def _parse_route_statistics(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for protocol, routes, active, _added, _deleted in re.findall(
            r"^\s*([A-Z][A-Z-]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", text, re.M):
        if protocol == "TOTAL":
            continue
        facts.append(_fact(f"routing.protocol.{protocol.lower()}.active_routes", int(active), category="routing",
                           resource_type="routing_protocol", resource_id=protocol.lower(), policy="baseline_delta",
                           unit="routes", warning=0.2, critical=0.5, command=command))
    return facts


def _parse_bgp_peers(command: str, text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    local = re.search(r"BGP local router ID:\s*(\S+)", text, re.I)
    local_as = re.search(r"Local AS number:\s*(\d+)", text, re.I)
    if local:
        facts.append(_fact("protocol.bgp.router_id", local.group(1), category="protocol",
                           resource_type="bgp", resource_id="ipv4", severity="critical", command=command))
    if local_as:
        facts.append(_fact("protocol.bgp.local_as", int(local_as.group(1)), category="protocol",
                           resource_type="bgp", resource_id="ipv4", severity="critical", command=command))
    peer_pattern = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\S+\s+(\S+)\s*$", re.M)
    for peer, remote_as, state in peer_pattern.findall(text):
        pid = _slug(peer)
        facts.extend([
            _fact(f"protocol.bgp.peer.{pid}.remote_as", int(remote_as), category="protocol",
                  resource_type="bgp_peer", resource_id=peer, severity="critical", command=command),
            _fact(f"protocol.bgp.peer.{pid}.state", state.lower(), category="protocol",
                  resource_type="bgp_peer", resource_id=peer, severity="critical", command=command),
        ])
    return facts


def _parse_configured(command: str, text: str, protocol: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    if "not configured" in lowered:
        configured = False
    else:
        positive_markers = {
            "lldp": ("chassis id", "system name", "neighbor index"),
            "ospf": ("ospf process", "router id", "neighbor id"),
            "bfd": ("total session", "local discr", "remote discr"),
        }
        if not any(marker in lowered for marker in positive_markers.get(protocol, ())):
            return []
        configured = True
    return [_fact(f"protocol.{protocol}.configured", configured, category="protocol",
                  resource_type=protocol, resource_id=protocol, severity="warning", command=command)]


def parse_device_output(vendor: str, text: str) -> dict[str, Any]:
    """Return typed facts and extraction coverage for one device transcript."""
    if str(vendor or "").strip().lower() not in {"h3c", "hp", "comware"}:
        return {"schema_version": STRUCTURED_SCHEMA_VERSION, "parser": "unsupported", "facts": [], "coverage": {}, "quality": "unsupported"}
    facts_by_key: dict[str, dict[str, Any]] = {}
    commands_seen: list[str] = []
    commands_parsed: set[str] = set()
    for command, output in split_command_output(text):
        commands_seen.append(command)
        handlers: list = []
        if re.search(r"\bversion$", command): handlers = [_parse_version]
        elif "device man" in command or "license device-id" in command: handlers = [_parse_serial]
        elif re.search(r"cpu-usage$", command): handlers = [_parse_cpu]
        elif re.search(r"\bmemory$", command): handlers = [_parse_memory]
        elif "environment" in command: handlers = [_parse_temperature]
        elif re.search(r"\bfan$", command): handlers = [lambda c, o: _parse_component(c, o, "fan")]
        elif re.search(r"\bpower$", command): handlers = [lambda c, o: _parse_component(c, o, "power")]
        elif "ip int brief" in command: handlers = [_parse_interfaces]
        elif "routing-table statistics" in command: handlers = [_parse_route_statistics]
        elif re.search(r"ip routing-table$", command): handlers = [_parse_routes]
        elif "bgp peer" in command: handlers = [_parse_bgp_peers]
        elif "lldp nei" in command: handlers = [lambda c, o: _parse_configured(c, o, "lldp")]
        elif "ospf" in command: handlers = [lambda c, o: _parse_configured(c, o, "ospf")]
        elif "bfd session" in command: handlers = [lambda c, o: _parse_configured(c, o, "bfd")]
        extracted: list[dict[str, Any]] = []
        for handler in handlers:
            extracted.extend(handler(command, output))
        if extracted:
            commands_parsed.add(command)
        for fact in extracted:
            facts_by_key[fact["key"]] = fact
    categories = sorted({fact["category"] for fact in facts_by_key.values()})
    quality = "complete" if {"health", "interface", "routing", "protocol"}.issubset(categories) else "partial" if facts_by_key else "unparsed"
    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION, "parser": "h3c_comware", "facts": list(facts_by_key.values()),
        "coverage": {"commands_seen": len(commands_seen), "commands_parsed": len(commands_parsed),
                     "fact_count": len(facts_by_key), "categories": categories},
        "quality": quality,
    }
