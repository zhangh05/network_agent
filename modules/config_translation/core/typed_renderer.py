# -*- coding: utf-8 -*-
"""Typed Renderer v2 — renders TypedIRBundle → TranslationCandidate list.

v2 adds context-aware interface translation: access/trunk/native/pvid/aggregate/LLDP.
"""

from __future__ import annotations

import re

from modules.config_translation.core.typed_ir import TypedIRBundle, InterfaceIR, VlanIR, StaticRouteIR, LldpIR, RoutingProcessIR
from modules.config_translation.core.translation_model import TranslationCandidate, Provenance, Confidence, Origin


def _typed_candidate(source_line: str, candidate_line: str, from_vendor: str,
                     to_vendor: str, block_type: str, confidence: Confidence,
                     start: int = 0, end: int = 0, **extra_evidence) -> TranslationCandidate:
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=candidate_line,
        from_vendor=from_vendor, to_vendor=to_vendor,
        source_platform=from_vendor, target_platform=to_vendor,
        provenance=Provenance.TYPED_RENDERER,
        confidence=confidence,
        origin=Origin.RAW_FALLBACK,
        module=block_type,
        evidence={
            "typed_ir": True,
            "renderer": "typed_renderer_v2",
            "block_type": block_type,
            "source_line_start": start,
            "source_line_end": end,
            **extra_evidence,
        },
    )


def render_interface(ir: InterfaceIR, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    candidates: list[TranslationCandidate] = []
    ctx = {
        "interface_name": ir.name,
        "context_complete": ir.context_complete,
        "context_warnings": ir.context_warnings,
    }
    desc_raw, desc_line = "", ir.source_start
    shutdown_raw, shutdown_line = "", ir.source_start
    ip_raw, ip_line = "", ir.source_start
    access_raw, access_line = "", ir.source_start
    trunk_raw, trunk_line = "", ir.source_start
    access_vlan_raw, access_vlan_line = "", ir.source_start
    trunk_allowed_raw, trunk_allowed_line = "", ir.source_start
    native_raw, native_line = "", ir.source_start
    pvid_raw, pvid_line = "", ir.source_start

    for idx, rl in enumerate(ir.raw_lines[1:], 1):
        s = rl.strip().lower()
        ln = ir.source_start + idx
        if s.startswith(("description ", "name ")):
            desc_raw, desc_line = rl, ln
        elif s.startswith(("port link-type access", "switchport mode access")):
            access_raw, access_line = rl, ln
        elif s.startswith(("port link-type trunk", "switchport mode trunk")):
            trunk_raw, trunk_line = rl, ln
        elif s.startswith(("port default vlan", "switchport access vlan", "port access vlan")):
            access_vlan_raw, access_vlan_line = rl, ln
        elif "trunk" in s and ("allow" in s or "permit" in s):
            trunk_allowed_raw, trunk_allowed_line = rl, ln
        elif "trunk" in s and "native" in s:
            native_raw, native_line = rl, ln
        elif "trunk" in s and "pvid" in s:
            pvid_raw, pvid_line = rl, ln
        elif s in ("shutdown", "no shutdown", "undo shutdown"):
            shutdown_raw, shutdown_line = rl, ln
        elif s.startswith("ip address "):
            ip_raw, ip_line = rl, ln

    # ── Description ──
    if ir.description:
        candidates.append(_typed_candidate(
            desc_raw or f"description {ir.description}",
            f"description {ir.description}",
            from_vendor, to_vendor, "interface.description",
            Confidence.EXACT, start=desc_line, end=desc_line, **ctx,
        ))

    # ── Shutdown ──
    if ir.shutdown_state in ("shutdown", "no_shutdown", "undo_shutdown"):
        tgt = {"shutdown": "shutdown",
               "no_shutdown": "undo shutdown" if to_vendor in ("huawei","h3c") else "no shutdown",
               "undo_shutdown": "no shutdown" if to_vendor in ("cisco","ruijie") else "undo shutdown"
              }.get(ir.shutdown_state, "shutdown")
        candidates.append(_typed_candidate(
            shutdown_raw or ir.shutdown_state, tgt,
            from_vendor, to_vendor, "interface.shutdown", Confidence.EXACT,
            start=shutdown_line, end=shutdown_line, **ctx,
        ))

    # ── IP Address (passthrough — same syntax across vendors) ──
    if ir.ip_address:
        tgt = f"ip address {ir.ip_address}"
        candidates.append(_typed_candidate(
            ip_raw or tgt, tgt,
            from_vendor, to_vendor, "interface.ip_address", Confidence.EXACT,
            start=ip_line, end=ip_line, **ctx,
        ))

    # ── Access port (context_complete → exact) ──
    if ir.mode == "access" and ir.access_vlan and from_vendor != to_vendor:
        vlan_id = ir.access_vlan
        if to_vendor == "cisco" or to_vendor == "ruijie":
            candidates.append(_typed_candidate(
                access_raw or "switchport mode access", "switchport mode access",
                from_vendor, to_vendor, "interface.access", Confidence.EXACT,
                start=access_line, end=access_line, mode="access", **ctx,
            ))
            candidates.append(_typed_candidate(
                access_vlan_raw or f"switchport access vlan {vlan_id}",
                f"switchport access vlan {vlan_id}",
                from_vendor, to_vendor, "interface.access", Confidence.EXACT,
                start=access_vlan_line, end=access_vlan_line, mode="access", **ctx,
            ))
        else:
            # Huawei uses 'port default vlan', H3C uses 'port access vlan'
            candidates.append(_typed_candidate(
                access_raw or "port link-type access", "port link-type access",
                from_vendor, to_vendor, "interface.access", Confidence.EXACT,
                start=access_line, end=access_line, mode="access", **ctx,
            ))
            if to_vendor == "h3c":
                candidates.append(_typed_candidate(
                    access_vlan_raw or f"port access vlan {vlan_id}",
                    f"port access vlan {vlan_id}",
                    from_vendor, to_vendor, "interface.access", Confidence.EXACT,
                    start=access_vlan_line, end=access_vlan_line, mode="access", **ctx,
                ))
            else:
                candidates.append(_typed_candidate(
                    access_vlan_raw or f"port default vlan {vlan_id}",
                    f"port default vlan {vlan_id}",
                    from_vendor, to_vendor, "interface.access", Confidence.EXACT,
                    start=access_vlan_line, end=access_vlan_line, mode="access", **ctx,
                ))

    # ── Trunk mode → semantic_near only ──
    if ir.mode == "trunk" and from_vendor != to_vendor:
        if to_vendor == "cisco" or to_vendor == "ruijie":
            candidates.append(_typed_candidate(
                trunk_raw or "switchport mode trunk", "switchport mode trunk",
                from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
                start=trunk_line, end=trunk_line, semantic_near=True, mode="trunk", **ctx,
            ))
            if ir.trunk_allowed_vlans:
                vlans = ",".join(ir.trunk_allowed_vlans)
                candidates.append(_typed_candidate(
                    trunk_allowed_raw or f"switchport trunk allowed vlan {vlans}",
                    f"switchport trunk allowed vlan {vlans}",
                    from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
                    start=trunk_allowed_line, end=trunk_allowed_line,
                    semantic_near=True, mode="trunk", **ctx,
                ))
        else:
            candidates.append(_typed_candidate(
                trunk_raw or "port link-type trunk", "port link-type trunk",
                from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
                start=trunk_line, end=trunk_line, semantic_near=True, mode="trunk", **ctx,
            ))
            if ir.trunk_allowed_vlans:
                vlans = " ".join(ir.trunk_allowed_vlans)
                candidates.append(_typed_candidate(
                    trunk_allowed_raw or f"port trunk permit vlan {vlans}",
                    f"port trunk permit vlan {vlans}",
                    from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
                    start=trunk_allowed_line, end=trunk_allowed_line,
                    semantic_near=True, mode="trunk", **ctx,
                ))

    # ── Native/pvid → semantic_near only ──
    if ir.native_vlan and from_vendor != to_vendor:
        tgt = (f"port trunk pvid vlan {ir.native_vlan}" if to_vendor in ("huawei","h3c","ruijie")
               else f"switchport trunk native vlan {ir.native_vlan}")
        candidates.append(_typed_candidate(
            native_raw or f"native vlan {ir.native_vlan}", tgt,
            from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
            start=native_line, end=native_line, semantic_near=True, **ctx,
        ))
    if ir.pvid_vlan and from_vendor != to_vendor:
        tgt = (f"switchport trunk native vlan {ir.pvid_vlan}" if to_vendor=="cisco"
               else f"port trunk pvid vlan {ir.pvid_vlan}")
        candidates.append(_typed_candidate(
            pvid_raw or f"pvid vlan {ir.pvid_vlan}", tgt,
            from_vendor, to_vendor, "interface.trunk", Confidence.MEDIUM,
            start=pvid_line, end=pvid_line, semantic_near=True, **ctx,
        ))

    # ── LLDP interface-level → semantic_near ──
    if ir.lldp_transmit is not None or ir.lldp_receive is not None:
        tgt = ("lldp transmit" if to_vendor=="cisco" else
               "lldp enable" if to_vendor in ("huawei","h3c","ruijie") else "lldp enable")
        candidates.append(_typed_candidate(
            "lldp interface-level", tgt,
            from_vendor, to_vendor, "interface.lldp", Confidence.MEDIUM,
            start=ir.source_start, end=ir.source_start, semantic_near=True,
            lldp_context="interface-level", **ctx,
        ))

    # ── Aggregate member → manual_review ──
    if ir.aggregate_group:
        ag_line = ir.source_start + 1  # default to first body line
        ag_source = f"aggregate group {ir.aggregate_group}"  # fallback
        # Find the actual aggregate line for proper source tracking
        for idx, rl in enumerate(ir.raw_lines[1:], 1):
            s = rl.strip().lower()
            if 'channel-group' in s or 'eth-trunk' in s or 'link-aggregation' in s or 'port link-aggregation' in s:
                ag_line = ir.source_start + idx
                ag_source = rl.strip()  # original source line text
                break
        candidates.append(_typed_candidate(
            ag_source,
            f"# MANUAL_REVIEW: aggregate member group {ir.aggregate_group}",
            from_vendor, to_vendor, "interface.aggregate", Confidence.LOW,
            start=ag_line, end=ag_line,
            semantic_near=False, aggregate_group=ir.aggregate_group, risk=True, **ctx,
        ))

    return candidates


def render_vlan(ir: VlanIR, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    candidates = []
    if not ir.vlan_ids:
        return candidates
    src = ir.raw_lines[0] if ir.raw_lines else f"vlan {ir.vlan_ids[0]}"

    for vid in ir.vlan_ids:
        candidates.append(_typed_candidate(
            src, f"vlan {vid}", from_vendor, to_vendor,
            "vlan", Confidence.EXACT, start=ir.source_start, end=ir.source_end,
        ))
    if ir.name:
        candidates.append(_typed_candidate(
            f"name {ir.name}", f"name {ir.name}", from_vendor, to_vendor,
            "vlan.name", Confidence.EXACT, start=ir.source_start, end=ir.source_end,
        ))
    return candidates


def render_static_route(ir: StaticRouteIR, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    src = ir.raw_lines[0] if ir.raw_lines else ""
    if to_vendor in ("huawei", "h3c"):
        line = f"ip route-static {ir.destination} {ir.mask} {ir.next_hop}"
    else:
        line = f"ip route {ir.destination} {ir.mask} {ir.next_hop}"
    return [_typed_candidate(
        src, line, from_vendor, to_vendor,
        "routing.static", Confidence.EXACT, start=ir.source_start, end=ir.source_end,
    )]


def render_lldp(ir: LldpIR, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    src = ir.raw_lines[0] if ir.raw_lines else "lldp"
    if ir.enabled is True:
        line = "lldp run" if to_vendor in ("cisco", "ruijie") else "lldp enable"
    elif ir.enabled is False:
        line = "no lldp run" if to_vendor in ("cisco", "ruijie") else "undo lldp enable"
    else:
        return []
    return [_typed_candidate(
        src, line, from_vendor, to_vendor,
        "management.lldp", Confidence.EXACT, start=ir.source_start, end=ir.source_end,
    )]


def render_routing_ir(rp: RoutingProcessIR, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    """Render OSPF/BGP/ISIS process header as typed candidates."""
    candidates: list[TranslationCandidate] = []
    rt_ctx = {"protocol": rp.protocol, "process_id": rp.process_id or rp.asn,
              "context_complete": rp.context_complete, "context_warnings": rp.context_warnings}
    src = rp.raw_lines[0] if rp.raw_lines else ""

    # ── Process header (exact) ──
    if rp.protocol == "ospf":
        if to_vendor == "cisco" or to_vendor == "ruijie":
            tgt = f"router ospf {rp.process_id}"
        else:
            tgt = f"ospf {rp.process_id}"
        candidates.append(_typed_candidate(
            src, tgt, from_vendor, to_vendor, "routing.process",
            Confidence.EXACT, start=rp.source_start, end=rp.source_start,
            typed_routing=True, **rt_ctx,
        ))
    elif rp.protocol == "bgp":
        if to_vendor == "cisco" or to_vendor == "ruijie":
            tgt = f"router bgp {rp.asn}"
        else:
            tgt = f"bgp {rp.asn}"
        candidates.append(_typed_candidate(
            src, tgt, from_vendor, to_vendor, "routing.process",
            Confidence.EXACT, start=rp.source_start, end=rp.source_start,
            typed_routing=True, **rt_ctx,
        ))
    elif rp.protocol == "isis":
        candidates.append(_typed_candidate(
            src, f"# SEMANTIC_NEAR: isis {rp.process_id}",
            from_vendor, to_vendor, "routing.process",
            Confidence.MEDIUM, semantic_near=True, typed_routing=True, **rt_ctx,
        ))

    # ── network statements → manual_review ──
    for nw in rp.networks:
        raw = nw.get("source_line", nw.get("raw", ""))
        candidates.append(_typed_candidate(
            raw, f"# MANUAL_REVIEW: {nw.get('raw','')}",
            from_vendor, to_vendor, "routing.network",
            Confidence.LOW, semantic_near=True, typed_routing=True, risk=True, **rt_ctx,
        ))

    # ── router-id → semantic_near ──
    if rp.router_id and from_vendor != to_vendor:
        candidates.append(_typed_candidate(
            f"router-id {rp.router_id}", f"router-id {rp.router_id}",
            from_vendor, to_vendor, "routing.router_id",
            Confidence.MEDIUM, semantic_near=True, typed_routing=True, **rt_ctx,
        ))

    # ── passive-interface → manual_review ──
    for pi in rp.passive_interfaces:
        candidates.append(_typed_candidate(
            f"passive-interface {pi}", f"# MANUAL_REVIEW: passive-interface {pi}",
            from_vendor, to_vendor, "routing.passive",
            Confidence.LOW, semantic_near=True, typed_routing=True, risk=True, **rt_ctx,
        ))

    # ── risky_lines → manual_review marker ──
    for rl in rp.risky_lines:
        candidates.append(_typed_candidate(
            rl, f"# MANUAL_REVIEW: {rl}",
            from_vendor, to_vendor, "routing.review",
            Confidence.LOW, semantic_near=True, typed_routing=True, risk=True, **rt_ctx,
        ))

    return candidates


def render_typed_ir(ir: TypedIRBundle, from_vendor: str, to_vendor: str) -> list[TranslationCandidate]:
    candidates: list[TranslationCandidate] = []
    for iface in ir.interfaces:
        candidates.extend(render_interface(iface, from_vendor, to_vendor))
    for vlan in ir.vlans:
        candidates.extend(render_vlan(vlan, from_vendor, to_vendor))
    for route in ir.static_routes:
        candidates.extend(render_static_route(route, from_vendor, to_vendor))
    for lldp in ir.lldp:
        candidates.extend(render_lldp(lldp, from_vendor, to_vendor))
    for rp in ir.routing_processes:
        candidates.extend(render_routing_ir(rp, from_vendor, to_vendor))
    return candidates
