# -*- coding: utf-8 -*-
"""Typed IR v1 — structured intermediate representation for low-risk network config.

Only covers low-risk modules: interface, vlan, static-route, lldp.
High-risk blocks (NAT/IPsec/QoS/route-policy/security-policy/BGP/OSPF network/ACL rule)
are routed to review_blocks, never rendered as deployable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InterfaceIR:
    """Typed representation of a single interface block with context."""
    name: str
    description: str = ""
    ip_address: str = ""  # e.g. "10.0.0.1 255.255.255.0"
    shutdown_state: str = ""  # "shutdown", "no_shutdown", "undo_shutdown", ""
    # Layer-2 mode
    mode: str | None = None  # "access", "trunk", "routed", None
    access_vlan: str | None = None
    trunk_allowed_vlans: list[str] | None = None
    native_vlan: str | None = None
    pvid_vlan: str | None = None
    # LLDP interface-level
    lldp_transmit: bool | None = None
    lldp_receive: bool | None = None
    lldp_enabled: bool | None = None  # Global-style enable
    # Aggregation
    aggregate_group: str | None = None
    aggregate_mode: str | None = None
    # Context metadata
    context_complete: bool = False
    context_warnings: list[str] = field(default_factory=list)
    # Source tracking
    raw_lines: list[str] = field(default_factory=list)
    source_start: int = 0
    source_end: int = 0
    risk_tags: list[str] = field(default_factory=list)


@dataclass
class VlanIR:
    """Typed representation of a VLAN definition."""
    vlan_ids: list[int] = field(default_factory=list)
    name: str = ""
    description: str = ""
    raw_lines: list[str] = field(default_factory=list)
    source_start: int = 0
    source_end: int = 0
    risk_tags: list[str] = field(default_factory=list)


@dataclass
class StaticRouteIR:
    """Typed representation of a simple static route."""
    destination: str = ""
    mask: str = ""
    next_hop: str = ""
    raw_lines: list[str] = field(default_factory=list)
    source_start: int = 0
    source_end: int = 0
    risk_tags: list[str] = field(default_factory=list)


@dataclass
class LldpIR:
    """Typed representation of LLDP configuration."""
    enabled: bool | None = None
    scope: str = "global"  # "global" or "interface"
    raw_lines: list[str] = field(default_factory=list)
    source_start: int = 0
    source_end: int = 0


@dataclass
class RoutingProcessIR:
    """Typed representation of an OSPF/BGP/ISIS routing process."""
    protocol: str = ""  # "ospf", "bgp", "isis", "unknown"
    process_id: str | None = None
    asn: str | None = None
    router_id: str | None = None
    areas: list[str] = field(default_factory=list)
    networks: list[dict] = field(default_factory=list)
    passive_interfaces: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    risky_lines: list[str] = field(default_factory=list)
    context_required_lines: list[str] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)
    source_start: int = 0
    source_end: int = 0
    risk_tags: list[str] = field(default_factory=list)
    context_complete: bool = False
    context_warnings: list[str] = field(default_factory=list)


@dataclass
class TypedIRBundle:
    """Complete typed IR bundle from a parsed config."""
    interfaces: list[InterfaceIR] = field(default_factory=list)
    vlans: list[VlanIR] = field(default_factory=list)
    static_routes: list[StaticRouteIR] = field(default_factory=list)
    lldp: list[LldpIR] = field(default_factory=list)
    routing_processes: list[RoutingProcessIR] = field(default_factory=list)
    unsupported_blocks: list = field(default_factory=list)
    review_blocks: list = field(default_factory=list)
