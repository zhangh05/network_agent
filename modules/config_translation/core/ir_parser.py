# -*- coding: utf-8 -*-
"""Block → Typed IR v1 parser. Converts ConfigBlock objects to TypedIRBundle."""

from __future__ import annotations

import re

from modules.config_translation.core.parser.config_block_parser import ConfigBlock
from modules.config_translation.core.typed_ir import InterfaceIR, StaticRouteIR, VlanIR, LldpIR, TypedIRBundle, RoutingProcessIR

# Low-risk patterns
INTERFACE_HEADER = re.compile(
    r"^interface\s+(\S+)", re.IGNORECASE,
)
DESCRIPTION_RE = re.compile(r"^\s*(description|name)\s+(.+)", re.IGNORECASE)
SHUTDOWN_RE = re.compile(r"^\s*shutdown\s*$", re.IGNORECASE)
NO_SHUTDOWN_RE = re.compile(r"^\s*(no\s+shutdown|undo\s+shutdown|undo\s{2,}shutdown)\s*$", re.IGNORECASE)
LLDP_ENABLE_RE = re.compile(r"^\s*(lldp\s+enable|lldp\s+run)\s*$", re.IGNORECASE)
LLDP_UNDO_RE = re.compile(r"^\s*(undo\s+lldp\s+enable|no\s+lldp\s+run)\s*$", re.IGNORECASE)

# Static route
SIMPLE_STATIC_RE = re.compile(
    r"^\s*(ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)\s*$|"
    r"ip\s+route-static\s+(\S+)\s+(\S+)\s+(\S+)\s*$)",
    re.IGNORECASE,
)
VRF_TRACK_TAG_RE = re.compile(r"\b(vrf|track|tag|preference)\b", re.IGNORECASE)

# VLAN
SINGLE_VLAN_RE = re.compile(r"^\s*vlan\s+(\d+)\s*$", re.IGNORECASE)
VLAN_BATCH_RE = re.compile(r"^\s*vlan\s+batch\s+([\d\s]+)\s*$", re.IGNORECASE)
VLAN_NAME_RE = re.compile(r"^\s*name\s+(.+)", re.IGNORECASE)

# High-risk markers — anything matching these goes to review
HIGH_RISK_MARKER = re.compile(
    r"(security-policy|nat-policy|ipsec\s+policy|ike\s+|aaa\b|route-policy|route-map|"
    r"qos\b|traffic\s+classifer|traffic\s+behavior|traffic\s+policy|"
    r"snmp-server\s+community|snmp-agent\s+community|"
    r"password|cipher|key\b|secret|community|"
    r"neighbor\s+\S+\s+remote-as|peer\s+\S+\s+as-number|"
    r"network\s+\S+\s+\S+\s+area|"
    r"access-list\s+\d+\s+permit|access-list\s+\d+\s+deny|"
    r"rule\s+\d+\s+permit|rule\s+\d+\s+deny|"
    r"switchport\s+mode|port\s+link-type|port\s+trunk|port\s+default|switchport\s+access|"
    r"switchport\s+trunk|port\s+access)",
    re.IGNORECASE,
)


def _parse_interface_block(block: ConfigBlock) -> InterfaceIR:
    m = INTERFACE_HEADER.match(block.header)
    name = m.group(1) if m else block.header

    ir = InterfaceIR(name=name, raw_lines=list(block.lines),
                     source_start=block.start_line, source_end=block.end_line)

    # Interface sub-command regex
    ACCESS_MODE_RE = re.compile(r"^\s*(switchport\s+mode\s+access|port\s+link-type\s+access)\s*$", re.IGNORECASE)
    TRUNK_MODE_RE = re.compile(r"^\s*(switchport\s+mode\s+trunk|port\s+link-type\s+trunk)\s*$", re.IGNORECASE)
    SW_ACCESS_VLAN_RE = re.compile(r"^\s*switchport\s+access\s+vlan\s+(\d+)\s*$", re.IGNORECASE)
    PORT_DEFAULT_VLAN_RE = re.compile(r"^\s*port\s+default\s+vlan\s+(\d+)\s*$", re.IGNORECASE)
    PORT_ACCESS_VLAN_RE = re.compile(r"^\s*port\s+access\s+vlan\s+(\d+)\s*$", re.IGNORECASE)
    TRUNK_ALLOWED_RE = re.compile(r"^\s*(switchport\s+trunk\s+allowed\s+vlan\s+([\d,\s]+)|port\s+trunk\s+(permit|allow-pass)\s+vlan\s+([\d\s]+))\s*$", re.IGNORECASE)
    NATIVE_VLAN_RE = re.compile(r"^\s*switchport\s+trunk\s+native\s+vlan\s+(\d+)\s*$", re.IGNORECASE)
    PVID_RE = re.compile(r"^\s*port\s+trunk\s+pvid\s+vlan\s+(\d+)\s*$", re.IGNORECASE)
    NO_SWITCHPORT_RE = re.compile(r"^\s*(no\s+switchport|undo\s+portswitch)\s*$", re.IGNORECASE)
    LLDP_TX_RE = re.compile(r"^\s*lldp\s+transmit\s*$", re.IGNORECASE)
    LLDP_RX_RE = re.compile(r"^\s*lldp\s+receive\s*$", re.IGNORECASE)
    LLDP_NO_TX_RE = re.compile(r"^\s*no\s+lldp\s+transmit\s*$", re.IGNORECASE)
    LLDP_NO_RX_RE = re.compile(r"^\s*no\s+lldp\s+receive\s*$", re.IGNORECASE)
    AGGREGATE_RE = re.compile(r"^\s*(channel-group\s+(\d+).*|eth-trunk\s+(\d+).*|port\s+link-aggregation\s+group\s+(\d+).*|link-aggregation\s+mode\s+(\S+))\s*$", re.IGNORECASE)

    IP_ADDRESS_RE = re.compile(r"^\s*ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)(?:\s+secondary)?\s*$", re.IGNORECASE)

    for line in block.body_lines:
        stripped = line.strip()
        # description
        dm = DESCRIPTION_RE.match(line)
        if dm:
            ir.description = dm.group(2).strip()
            continue
        # shutdown
        if NO_SHUTDOWN_RE.match(stripped):
            ir.shutdown_state = "undo_shutdown" if "undo" in stripped else "no_shutdown"
            continue
        if SHUTDOWN_RE.match(stripped):
            ir.shutdown_state = "shutdown"
            continue
        # access mode
        if ACCESS_MODE_RE.match(stripped):
            ir.mode = "access"
            continue
        # trunk mode
        if TRUNK_MODE_RE.match(stripped):
            ir.mode = "trunk"
            continue
        # routed
        if NO_SWITCHPORT_RE.match(stripped):
            ir.mode = "routed"
            continue
        # access vlan
        sm = SW_ACCESS_VLAN_RE.match(stripped)
        if sm:
            ir.access_vlan = sm.group(1)
            continue
        pm = PORT_DEFAULT_VLAN_RE.match(stripped)
        if pm:
            ir.access_vlan = pm.group(1)
            continue
        av = PORT_ACCESS_VLAN_RE.match(stripped)
        if av:
            ir.access_vlan = av.group(1)
            continue
        # trunk allowed
        tm = TRUNK_ALLOWED_RE.match(stripped)
        if tm:
            vlan_str = tm.group(2) or tm.group(4) or ""
            ir.trunk_allowed_vlans = [v.strip() for v in re.split(r"[\s,]+", vlan_str) if v.strip()]
            continue
        # native/pvid
        nm = NATIVE_VLAN_RE.match(stripped)
        if nm:
            ir.native_vlan = nm.group(1)
            continue
        pv = PVID_RE.match(stripped)
        if pv:
            ir.pvid_vlan = pv.group(1)
            continue
        # lldp interface-level
        if LLDP_TX_RE.match(stripped):
            ir.lldp_transmit = True
            continue
        if LLDP_RX_RE.match(stripped):
            ir.lldp_receive = True
            continue
        if LLDP_NO_TX_RE.match(stripped):
            ir.lldp_transmit = False
            continue
        if LLDP_NO_RX_RE.match(stripped):
            ir.lldp_receive = False
            continue
        # lldp global-style
        if LLDP_ENABLE_RE.match(stripped):
            ir.lldp_enabled = True
            continue
        if LLDP_UNDO_RE.match(stripped):
            ir.lldp_enabled = False
            continue
        # aggregate
        ag = AGGREGATE_RE.match(stripped)
        if ag:
            ir.aggregate_group = ag.group(2) or ag.group(3) or ag.group(4) or ""
            ir.aggregate_mode = ag.group(5) or ""
            ir.risk_tags.append("aggregate_member")
            continue
        # ip address (L3 interface)
        ipm = IP_ADDRESS_RE.match(stripped)
        if ipm:
            ir.ip_address = f"{ipm.group(1)} {ipm.group(2)}"
            continue
        # High-risk sub-line
        if HIGH_RISK_MARKER.search(stripped):
            ir.risk_tags.append("high_risk_subline")

    # Determine context completeness
    if ir.mode == "access" and ir.access_vlan:
        ir.context_complete = True
    elif ir.mode == "access" and not ir.access_vlan:
        ir.context_warnings.append("access mode set but no vlan specified")
    elif ir.mode == "trunk":
        if ir.trunk_allowed_vlans:
            ir.context_warnings.append("trunk: allowed-vlan present, native/pvid semantics require verification")
        else:
            ir.context_warnings.append("trunk mode set but no allowed vlan specified")
    elif ir.mode is None and (ir.access_vlan or ir.trunk_allowed_vlans):
        ir.context_warnings.append("vlan set but mode not specified")

    return ir


def _parse_vlan_block(block: ConfigBlock) -> VlanIR | None:
    vlan_ids = []
    name = ""
    desc = ""

    # Parse header
    sm = SINGLE_VLAN_RE.match(block.header)
    if sm:
        vlan_ids.append(int(sm.group(1)))
    else:
        bm = VLAN_BATCH_RE.match(block.header)
        if bm:
            for token in bm.group(1).split():
                try:
                    vlan_ids.append(int(token))
                except ValueError:
                    pass

    # Parse body
    for line in block.body_lines:
        stripped = line.strip()
        nm = VLAN_NAME_RE.match(stripped)
        if nm:
            name = nm.group(1)
            continue
        dm = DESCRIPTION_RE.match(line)
        if dm:
            desc = dm.group(2).strip()

    if not vlan_ids:
        return None

    return VlanIR(vlan_ids=vlan_ids, name=name, description=desc,
                  raw_lines=list(block.lines),
                  source_start=block.start_line, source_end=block.end_line)


# ── Routing block parsing ──

OSPF_RE = re.compile(r"^(router\s+ospf\s+(\d+)|ospf\s+(\d+))", re.IGNORECASE)
BGP_RE = re.compile(r"^(router\s+bgp\s+(\d+)|bgp\s+(\d+))", re.IGNORECASE)
ISIS_RE = re.compile(r"^(router\s+isis\s+(\S+)|isis\s+(\d+))", re.IGNORECASE)
ROUTER_ID_RE = re.compile(r"^\s*router-id\s+(\S+)", re.IGNORECASE)
AREA_RE = re.compile(r"^\s*area\s+(\S+)", re.IGNORECASE)
NETWORK_OSPF_RE = re.compile(r"^\s*network\s+(\S+)\s+(\S+)\s+area\s+(\S+)", re.IGNORECASE)
NETWORK_BGP_RE = re.compile(r"^\s*network\s+(\S+)\s+mask\s+(\S+)", re.IGNORECASE)
PASSIVE_RE = re.compile(r"^\s*(passive-interface|silent-interface)\s+(\S+)", re.IGNORECASE)
NEIGHBOR_PEER_RE = re.compile(r"^\s*(neighbor\s+\S+|peer\s+\S+)", re.IGNORECASE)
RISKY_ROUTING_RE = re.compile(
    r"(route-policy|route-map|prefix-list|filter-policy|community|"
    r"local-preference|password|cipher|key|secret|"
    r"authentication|message-digest|key-chain|"
    r"redistribute|import-route|default-information|default-route-advertise|"
    r"address-family|ipv4-family|vrf)",
    re.IGNORECASE,
)

def _parse_routing_block(block: ConfigBlock, vendor: str) -> RoutingProcessIR | None:
    header = block.header.strip()
    rp = RoutingProcessIR(raw_lines=list(block.lines),
                          source_start=block.start_line, source_end=block.end_line)
    om = OSPF_RE.match(header)
    if om: rp.protocol = "ospf"; rp.process_id = om.group(2) or om.group(3)
    else:
        bm = BGP_RE.match(header)
        if bm: rp.protocol = "bgp"; rp.asn = bm.group(2) or bm.group(3)
        else:
            im = ISIS_RE.match(header)
            if im: rp.protocol = "isis"; rp.process_id = im.group(2) or im.group(3)
    if not rp.protocol: return None

    for line in block.body_lines:
        s = line.strip()
        if ROUTER_ID_RE.match(s):
            rp.router_id = ROUTER_ID_RE.match(s).group(1)
            rp.context_required_lines.append(s)
        elif AREA_RE.match(s):
            rp.areas.append(AREA_RE.match(s).group(1))
            if RISKY_ROUTING_RE.search(s):
                rp.risky_lines.append(s)
                if "authentication" in s.lower() or "message-digest" in s.lower():
                    rp.risk_tags.append("ospf_auth")
        elif (nw := NETWORK_OSPF_RE.match(s)):
            rp.networks.append({"raw": s, "prefix_or_address": nw.group(1),
                                "mask_or_wildcard": nw.group(2), "area": nw.group(3), "source_line": line})
            rp.context_required_lines.append(s)
        elif (nb := NETWORK_BGP_RE.match(s)):
            rp.networks.append({"raw": s, "prefix_or_address": nb.group(1),
                                "mask_or_wildcard": nb.group(2), "area": "", "source_line": line})
            rp.context_required_lines.append(s)
        elif (pa := PASSIVE_RE.match(s)):
            rp.passive_interfaces.append(pa.group(2))
            rp.context_required_lines.append(s)
        elif NEIGHBOR_PEER_RE.match(s):
            if any(x in s.lower() for x in ("password","cipher","secret")): rp.risk_tags.append("bgp_password")
            rp.risky_lines.append(s)
        elif RISKY_ROUTING_RE.search(s):
            if any(x in s.lower() for x in ("password","cipher","secret","key")): rp.risk_tags.append("secret_routing")
            if "authentication" in s.lower() or "message-digest" in s.lower(): rp.risk_tags.append("ospf_auth")
            if "redistribute" in s.lower() or "import-route" in s.lower(): rp.risk_tags.append("route_import")
            rp.risky_lines.append(s)
    rp.context_complete = bool(rp.process_id or rp.asn)
    return rp


def _parse_static_route(line: str, line_no: int) -> StaticRouteIR | None:
    stripped = line.strip()
    m = SIMPLE_STATIC_RE.match(stripped)
    if not m:
        return None
    # Simple route only — no VRF/track/tag/preference
    if VRF_TRACK_TAG_RE.search(stripped):
        return None

    groups = m.groups()
    if groups[1]:  # ip route ... pattern (group 2 = destination)
        return StaticRouteIR(
            destination=groups[1], mask=groups[2], next_hop=groups[3],
            raw_lines=[line], source_start=line_no, source_end=line_no,
        )
    elif groups[4]:  # ip route-static ... pattern (group 5 = destination)
        return StaticRouteIR(
            destination=groups[4], mask=groups[5], next_hop=groups[6],
            raw_lines=[line], source_start=line_no, source_end=line_no,
        )
    return None


def _parse_lldp_block(block: ConfigBlock) -> LldpIR | None:
    for line in block.all_lines:
        stripped = line.strip()
        if LLDP_ENABLE_RE.match(stripped):
            return LldpIR(enabled=True, source_start=block.start_line, source_end=block.end_line)
        if LLDP_UNDO_RE.match(stripped):
            return LldpIR(enabled=False, source_start=block.start_line, source_end=block.end_line)
    return None


def parse_typed_ir(blocks: list[ConfigBlock], from_vendor: str = "") -> TypedIRBundle:
    """Convert ConfigBlocks to TypedIRBundle.

    Low-risk blocks → typed IR.
    High-risk blocks → review_blocks.
    Unknown blocks → unsupported_blocks.
    """
    bundle = TypedIRBundle()

    for block in blocks:
        bt = block.block_type

        if bt == "interface":
            ir = _parse_interface_block(block)
            # If the interface has high-risk sub-lines, still render it but mark
            bundle.interfaces.append(ir)
            for child_line in block.body_lines:
                if HIGH_RISK_MARKER.search(child_line.strip()):
                    bundle.review_blocks.append(block)
                    break

        elif bt == "vlan":
            ir = _parse_vlan_block(block)
            if ir:
                bundle.vlans.append(ir)
            else:
                bundle.unsupported_blocks.append(block)

        elif bt == "routing_process":
            rp = _parse_routing_block(block, from_vendor)
            if rp:
                bundle.routing_processes.append(rp)

        elif bt == "firewall_policy":
            bundle.review_blocks.append(block)

        elif bt == "acl":
            # ACL header → review (rules are high-risk)
            bundle.review_blocks.append(block)

        elif bt == "global":
            # Check for standalone lines
            for line in block.all_lines:
                stripped = line.strip()
                # Try static route
                sr = _parse_static_route(stripped, block.start_line)
                if sr:
                    bundle.static_routes.append(sr)
                    continue
                # Try LLDP
                lr = _parse_lldp_block(ConfigBlock(
                    block_type="global", header=stripped,
                    lines=[line], start_line=block.start_line,
                    end_line=block.start_line,
                ))
                if lr:
                    bundle.lldp.append(lr)
                    continue
                # High risk?
                if HIGH_RISK_MARKER.search(stripped):
                    bundle.review_blocks.append(block)
                    break
            else:
                bundle.unsupported_blocks.append(block)

        elif bt == "unknown":
            for line in block.all_lines:
                stripped = line.strip()
                if HIGH_RISK_MARKER.search(stripped):
                    bundle.review_blocks.append(block)
                    break
                sr = _parse_static_route(stripped, block.start_line)
                if sr:
                    bundle.static_routes.append(sr)
                    break
            else:
                bundle.unsupported_blocks.append(block)

    return bundle
