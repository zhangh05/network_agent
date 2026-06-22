# -*- coding: utf-8 -*-
"""Deterministic rule-based translator — canonical translate_bundle pipeline.

translate_bundle() is the SOLE canonical entry point.
No retired fallback engine. Cross-vendor unmatched lines default to manual_review.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Safety helpers ──────────────────────────────────────────────────────

def _is_high_risk_line(stripped: str) -> bool:
    """Check if a source line is a high-risk line requiring manual review.

    Covers: NAT, IPsec, IKE, AAA, security-policy, route-policy/route-map,
    QoS (traffic classifier/behavior/policy).
    """
    return bool(re.match(
        r"^(security-policy|policy name|nat-policy|ipsec policy|ike|"
        r"aaa\b|authentication|authorization|accounting|"
        r"route-policy|route-map|"
        r"qos\b|traffic classifier|traffic behavior|traffic policy|"
        r"nat\b)",
        stripped, re.IGNORECASE,
    )) or bool(re.search(
        r"\b(security-policy|nat-policy)\b",
        stripped, re.IGNORECASE,
    ))


def _is_comware_cross_vendor_switchport(module: str, from_vendor: str, to_vendor: str) -> bool:
    """Check if a Comware switchport/lag command needs MR due to cross-vendor mismatch."""
    return (module in ("switchport", "lag")
            and from_vendor in ("h3c", "huawei", "ruijie")
            and to_vendor not in ("h3c", "huawei", "ruijie"))


COMWARE_VENDORS = {"h3c", "huawei", "ruijie"}


def _make_review_candidate(source_line, reason, from_vendor, to_vendor,
                            module="", source_line_number=0, rule_id=""):
    """Create a MANUAL_REVIEW TranslationCandidate."""
    from modules.config_translation.core.translation_model import TranslationCandidate, Provenance, Confidence, Origin
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=f"# MANUAL_REVIEW {source_line.strip()}",
        from_vendor=from_vendor, to_vendor=to_vendor,
        source_platform=from_vendor, target_platform=to_vendor,
        provenance=Provenance.RAW_STRING,
        confidence=Confidence.NONE,
        origin=Origin.RAW_FALLBACK,
        module=module,
        evidence={"reason": reason},
        source_line_number=source_line_number,
        rule_id=rule_id or f"manual_review__{reason[:40]}",
    )


def _make_semantic_near_candidate(source_line, suggested_line, reason,
                                   from_vendor, to_vendor, module=""):
    """Create a NORMALIZED_EQUIVALENT TranslationCandidate."""
    from modules.config_translation.core.translation_model import TranslationCandidate, Provenance, Confidence, Origin
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=suggested_line,
        from_vendor=from_vendor, to_vendor=to_vendor,
        source_platform=from_vendor, target_platform=to_vendor,
        provenance=Provenance.NORMALIZED_EQUIVALENT,
        confidence=Confidence.LOW,
        origin=Origin.RAW_FALLBACK,
        module=module,
        evidence={"reason": reason},
    )


def _make_unsupported_candidate(source_line, reason, from_vendor, to_vendor,
                                 module=""):
    """Create an UNSUPPORTED TranslationCandidate."""
    from modules.config_translation.core.translation_model import TranslationCandidate, Provenance, Confidence, Origin
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=source_line.strip(),
        from_vendor=from_vendor, to_vendor=to_vendor,
        source_platform=from_vendor, target_platform=to_vendor,
        provenance=Provenance.UNKNOWN,
        confidence=Confidence.NONE,
        origin=Origin.RAW_FALLBACK,
        module=module,
        evidence={"reason": reason},
    )


def _guess_module(source_line: str) -> str:
    """Conservative module guess from source line prefix."""
    lower = source_line.strip().lower()
    if not lower:
        return "unknown"
    # ── Switchport ──
    if lower.startswith(("port link-type", "port trunk", "port default vlan",
                       "port access vlan", "undo port", "undo shutdown",
                       "port hybrid", "port-security")):
        return "switchport"
    if lower.startswith("stp ") or lower.startswith("spanning-tree "):
        return "switchport.stp"
    if lower.startswith(("eth-trunk", "bridge-aggregation", "port-channel",
                       "link-aggregation", "mode lacp", "mode manual",
                       "channel-group", "interface eth-trunk",
                       "interface bridge-aggregation")):
        return "lag"
    if lower.startswith("banner "):
        return "management.banner"
    # ── Management ──
    if lower.startswith(("description ", "name ")):
        return "description"
    if lower.startswith(("snmp-server ", "snmp-agent ")):
        return "management.snmp"
    if lower.startswith(("ntp ", "ntp-service ", "clock timezone", "clock summer-time")):
        return "management.ntp"
    if lower.startswith(("logging ", "syslog ", "info-center ")):
        return "management.logging"
    if lower.startswith(("enable secret", "enable password", "super password",
                       "local-user", "line vty", "user-interface vty",
                       "aaa local-user", "password")):
        return "management.aaa"
    if lower.startswith(("ip http server", "ip http secure-server", "ip https server",
                       "http server enable", "http secure-server enable")):
        return "management.http"
    if lower.startswith(("radius-server", "tacacs-server", "radius ", "tacacs ",
                       "authentication-mode", "authorization-mode")):
        return "management.aaa"
    # ── Routing ──
    if lower.startswith(("ip route ", "ip route-static ")):
        return "static_route"
    if lower.startswith(("router ospf", "router bgp", "router isis", "router rip")):
        return "routing"
    if lower.startswith(("router-id ", "bgp ", "ospf ", "isis ", "network ", "area ", "rip ")):
        return "routing"
    if lower.startswith(("neighbor ", "peer ")):
        return "routing.bgp"
    if lower.startswith(("ipv4-family ", "ipv6-family ", "address-family ",
                       "exit-address-family", "route-distinguisher ",
                       "vpn-target ", "import-route ", "default-route-advertise",
                       "no passive-interface", "undo silent-interface",
                       "silent-interface", "maximum-prefix", "maximum load-balancing")):
        return "routing.bgp"
    if lower.startswith(("network-entity ", "cost-style ", "is-level", "isis circuit-level")):
        return "routing.isis"
    if lower.startswith(("route-map ", "route-policy ", "match ",
                       "set ", "apply ", "if-match ", "ip prefix-list ",
                       "prefix-list ", "ip ip-prefix ")):
        return "route_policy"
    if lower.startswith(("ip vrf ", "ip vpn-instance ", "vrf definition",
                       "rd ", "vpn-target")):
        return "routing.vrf"
    # ── Firewall / Security ──
    if lower.startswith(("security-policy", "nat-policy", "ipsec ", "ike ",
                       "crypto ", "encryption ", "hash ", "protocol ",
                       "encapsulation-mode", "transform ",
                       "security-zone name", "pre-shared-key ",
                       "esp ", "encap ", "proposal ", "preshare-key ")):
        return "firewall.ipsec"
    if lower.startswith(("nat ", "source-zone ", "destination-zone ",
                       "rule name ", "action ", "policy ")):
        return "firewall"
    if lower.startswith(("ip address-set", "ip service-set", "object service",
                       "object address", "service name", "service 0",
                       "address-group", "address 0",
                       "source-address ", "destination-address ")):
        return "firewall"
    if lower.startswith(("service ",)) and (
        re.search(r"\b(tcp|udp|icmp|http|https|dns|ssh|smtp|ping|snmp)\b", lower)):
        return "firewall"
    if lower.startswith(("firewall", "undo firewall", "session ")):
        return "firewall"
    # ── QoS ──
    if lower.startswith(("class-map", "policy-map", "class ", "service-policy input",
                       "priority ", "police ", "bandwidth ",
                       "traffic classifier", "traffic behavior", "traffic policy",
                       "queue", "qos ", "wred ")):
        return "routing.qos"
    # ── ACL ──
    if lower.startswith("permit ") or lower.startswith("deny "):
        return "acl"
    if lower.startswith("rule ") and re.search(r"\b(permit|deny)\b", lower):
        return "acl"
    if lower.startswith("access-list ") or lower.startswith("ip access-list "):
        return "acl"
    # ── VLAN / STP ──
    if lower.startswith("vlan "):
        return "vlan"
    if lower.startswith("switchport "):
        return "switchport"
    if lower.startswith(("spanning-tree", "stp ", "bpdu")):
        return "switchport.stp"
    # ── Interface ──
    if lower.startswith("interface "):
        return "interface"
    if lower.startswith("interface range ") or lower.startswith("port-group "):
        return "interface.range"
    # ── DHCP ──
    if lower.startswith(("dhcp enable", "dhcp server", "ip dhcp", "dhcp pool")):
        return "management.dhcp"
    # ── LLDP ──
    if lower.startswith(("lldp", "no lldp", "undo lldp")):
        return "management.lldp"
    # ── System ──
    if lower.startswith(("hostname ", "sysname ", "ip tcp synwait-time",
                       "line ", "user-interface ", "terminal ")):
        return "system"
    if lower.startswith(("ip binding")):
        return "routing"
    return "unknown"


class RuleBasedTranslator:
    """Translate common network configuration lines without an LLM.

    Canonical entry: translate_bundle() — deterministic translation pipeline.
    Returns TranslationBundle. No retired fallback engine.
    """

    def __init__(self):
        pass

    def translate_bundle(
        self, config_text: str, from_vendor: str, to_vendor: str
    ) -> "TranslationBundle":
        """CANONICAL structured translation returning TranslationBundle.

        Factory-matched lines → candidate with provenance.
        Unmatched same-vendor lines → passthrough with RAW_STRING.
        Unmatched cross-vendor lines → manual_review (conservative, safe).
        High-risk lines → forced to manual_review.
        """
        from modules.config_translation.core.translation_model import (
            TranslationBundle, TranslationCandidate,
            Provenance, Confidence, Origin, TranslationTarget,
        )
        from modules.config_translation.core.deployable_policy import DeployablePolicy, quick_assess
        from modules.config_translation.core.translation_candidate_factory import try_make_candidate

        from_vendor = (from_vendor or "unknown").lower()
        to_vendor = (to_vendor or "unknown").lower()

        candidates: list[TranslationCandidate] = []

        if not config_text or not to_vendor:
            return TranslationBundle()

        policy = DeployablePolicy()
        candidate_count = 0
        unmatched_count = 0
        review_count = 0
        semantic_count = 0
        unsupported_count = 0
        typed_renderer_count = 0
        typed_covered_lines: set[int] = set()
        typed_interface_count = 0
        typed_interface_exact_count = 0
        typed_interface_semantic_near_count = 0
        typed_interface_access_exact_count = 0
        typed_interface_trunk_semantic_count = 0
        typed_interface_context_complete_count = 0
        typed_interface_context_incomplete_count = 0
        typed_routing_count = 0
        typed_routing_exact_count = 0
        typed_routing_semantic_near_count = 0
        typed_routing_review_count = 0
        typed_routing_ospf_count = 0
        typed_routing_bgp_count = 0
        typed_routing_isis_count = 0
        typed_routing_network_semantic_count = 0
        typed_routing_neighbor_review_count = 0
        typed_routing_policy_review_count = 0
        typed_routing_auth_review_count = 0
        _dedup_keys: set[tuple] = set()

        # ── Phase 0: Typed IR v2 pipeline ──
        typed_ir_fallback = False
        try:
            from modules.config_translation.core.parser.config_block_parser import parse_config_blocks
            from modules.config_translation.core.ir_parser import parse_typed_ir
            from modules.config_translation.core.typed_renderer import render_typed_ir

            blocks = parse_config_blocks(config_text, from_vendor)
            ir_bundle = parse_typed_ir(blocks, from_vendor)
            typed_candidates = render_typed_ir(ir_bundle, from_vendor, to_vendor)

            if typed_candidates:
                typed_renderer_count = len(typed_candidates)
                for tc in typed_candidates:
                    evidence = tc.evidence or {}
                    # Source line tracking
                    sl = evidence.get("source_line_start", 0)
                    el = evidence.get("source_line_end", 0)
                    for ln in range(sl, el + 1):
                        typed_covered_lines.add(ln)
                    # Annotate rule_id for mapping log
                    block_type = evidence.get("block_type", "")
                    protocol = evidence.get("protocol", "")
                    if not tc.rule_id:
                        if block_type.startswith("interface"):
                            tc.rule_id = "typed_interface"
                        elif protocol:
                            tc.rule_id = f"typed_{protocol}"
                        elif block_type == "vlan":
                            tc.rule_id = "typed_vlan"
                        elif block_type == "static_route":
                            tc.rule_id = "typed_static_route"
                        elif block_type == "lldp":
                            tc.rule_id = "typed_lldp"
                        else:
                            tc.rule_id = f"typed_ir__{block_type}"
                    if tc.source_line_number <= 0:
                        tc.source_line_number = sl
                    # Interface tracking
                    if evidence.get("block_type", "").startswith("interface"):
                        typed_interface_count += 1
                        if tc.confidence and tc.confidence.value == "exact":
                            typed_interface_exact_count += 1
                            if evidence.get("mode") == "access":
                                typed_interface_access_exact_count += 1
                        else:
                            typed_interface_semantic_near_count += 1
                            if evidence.get("mode") == "trunk":
                                typed_interface_trunk_semantic_count += 1
                        if evidence.get("context_complete"):
                            typed_interface_context_complete_count += 1
                        else:
                            typed_interface_context_incomplete_count += 1
                    # Routing tracking
                    if evidence.get("typed_routing"):
                        typed_routing_count += 1
                        if tc.confidence and tc.confidence.value == "exact":
                            typed_routing_exact_count += 1
                            if evidence.get("protocol") == "ospf": typed_routing_ospf_count += 1
                            elif evidence.get("protocol") == "bgp": typed_routing_bgp_count += 1
                        else:
                            typed_routing_semantic_near_count += 1
                            if evidence.get("protocol") == "isis": typed_routing_isis_count += 1
                            if "network" in evidence.get("block_type", ""): typed_routing_network_semantic_count += 1
                        if evidence.get("risk"): typed_routing_review_count += 1
                        if "neighbor" in evidence.get("block_type", "") or "peer" in evidence.get("block_type", ""):
                            typed_routing_neighbor_review_count += 1
                        if "policy" in evidence.get("block_type", "") or "route-map" in evidence.get("block_type", ""):
                            typed_routing_policy_review_count += 1
                        if "ospf_auth" in evidence.get("risk_tags", []):
                            typed_routing_auth_review_count += 1

                    # Dedup: track (candidate_line, source_line_start, provenance) per source position
                    sl_start = evidence.get("source_line_start", 0)
                    key = (tc.candidate_line, tc.source_line or "", sl_start, str(tc.provenance.value))
                    if key not in _dedup_keys:
                        _dedup_keys.add(key)
                        candidates.append(tc)
                        candidate_count += 1
                    continue
                # Non-interface typed candidates (vlan, static route, lldp)
                for tc in typed_candidates:
                    if not (tc.evidence or {}).get("block_type", "").startswith("interface"):
                        sl_start = (tc.evidence or {}).get("source_line_start", 0)
                        key = (tc.candidate_line, tc.source_line or "", sl_start, str(tc.provenance.value))
                        if key not in _dedup_keys:
                            _dedup_keys.add(key)
                            candidates.append(tc)
                            candidate_count += 1
        except Exception as e:
            typed_ir_fallback = True
            logger.warning("Typed IR pipeline error (falling through to factory): %s", e)

        # ── Phase 1: Line-by-line factory path ──

        # Track which raw line numbers have been covered by typed renderer
        covered_line_nums: set[int] = typed_covered_lines
        _line_counter = 1  # 1-indexed, matches config file line numbers

        for raw in config_text.splitlines():
            line_num = _line_counter
            _line_counter += 1
            stripped = raw.strip()
            if not stripped or stripped.startswith(("!", "#")):
                continue

            # ── Skip lines already covered by typed renderer ──
            if line_num in covered_line_nums:
                continue

            # ── High-risk lines: always manual_review ──
            if _is_high_risk_line(stripped):
                candidates.append(_make_review_candidate(
                    raw, "high-risk pattern: requires manual review",
                    from_vendor, to_vendor, module="firewall",
                    source_line_number=line_num,
                    rule_id="manual_review__high_risk",
                ))
                review_count += 1
                continue

            # ── Try factory matcher ──
            mc = try_make_candidate(stripped, stripped.lower(), from_vendor, to_vendor)
            if mc is not None:
                items = mc if isinstance(mc, list) else [mc]
                for item in items:
                    # ── Annotate with source line position for block-aware dedup ──
                    if not item.evidence:
                        item.evidence = {}
                    if item.evidence.get("source_line_start", 0) <= 0:
                        item.evidence["source_line_start"] = line_num
                    if item.source_line_number <= 0:
                        item.source_line_number = line_num
                    if not item.rule_id:
                        item.rule_id = item.evidence.get("rule_id", f"factory__{item.module or 'unknown'}")
                    candidates.append(item)
                    candidate_count += 1
                continue

            # ── Unmatched line ──
            unmatched_count += 1
            module = _guess_module(stripped)

            if from_vendor == to_vendor:
                # Same vendor: passthrough with quick assessment
                prov, conf = quick_assess(stripped, from_vendor, to_vendor)
                candidates.append(TranslationCandidate(
                    source_line=raw, candidate_line=stripped,
                    from_vendor=from_vendor, to_vendor=to_vendor,
                    source_platform=from_vendor, target_platform=to_vendor,
                    provenance=prov, confidence=conf,
                    origin=Origin.SAME_VENDOR, module=module,
                    source_line_number=line_num,
                    rule_id=f"passthrough__{module or 'unknown'}",
                ))
            else:
                # Cross-vendor unmatched → conservative: manual_review
                if _is_comware_cross_vendor_switchport(module, from_vendor, to_vendor):
                    candidates.append(_make_review_candidate(
                        raw, f"cross-vendor {module}: requires manual review",
                        from_vendor, to_vendor, module=module,
                        source_line_number=line_num,
                        rule_id="manual_review__cross_vendor_comware",
                    ))
                    review_count += 1
                else:
                    candidates.append(_make_review_candidate(
                        raw, f"cross-vendor '{stripped[:50]}': requires manual review",
                        from_vendor, to_vendor, module=module,
                        source_line_number=line_num,
                        rule_id="manual_review__cross_vendor_unmatched",
                    ))
                    review_count += 1

        # ── Sort candidates by source line order ──
        # Typed renderer candidates have source_line_start in evidence;
        # fall back to source_line position in original config.
        source_lines = config_text.splitlines()
        _source_pos: dict[str, int] = {}
        for i, sl in enumerate(source_lines):
            stripped = sl.strip()
            if stripped and stripped not in _source_pos:
                _source_pos[stripped] = i

        def _sort_key(c) -> tuple[int, int]:
            ev = c.evidence or {}
            sl_start = ev.get("source_line_start")
            if isinstance(sl_start, int) and sl_start > 0:
                return (sl_start - 1, 0)  # convert 1-indexed → 0-indexed
            src = (c.source_line or "").strip()
            pos = _source_pos.get(src, len(source_lines))
            return (pos, 1)

        candidates.sort(key=_sort_key)

        # ── Final dedup: remove candidates with identical output lines ──
        # (factory may produce same output as typed renderer for canonical commands)
        # Uses (candidate_line, source_line_start) to preserve per-interface duplicates.
        _seen_output: set[tuple] = set()
        deduped: list = []
        for c in candidates:
            ev = c.evidence or {}
            sl_start = ev.get("source_line_start", 0)
            key = (c.candidate_line.strip().lower(), sl_start)
            if key not in _seen_output:
                _seen_output.add(key)
                deduped.append(c)
        candidates = deduped

        # Classify all candidates
        classified = [policy.classify_translation(c) for c in candidates]

        # ── Post-classification safety: force high-risk to manual_review ──
        for c, cl in zip(candidates, classified):
            source_text = c.source_line or ""
            if _is_high_risk_line(source_text.strip()) and cl.target != TranslationTarget.MANUAL_REVIEW:
                cl.target = TranslationTarget.MANUAL_REVIEW
                cl.reason = f"[FORCED_REVIEW] high-risk: {cl.reason}"
                cl.risk_level = "critical"

        # ── Build bundle ──
        bundle = TranslationBundle.from_classified(
            classified=classified,
            candidates=candidates,
            source_text=config_text,
        )
        bundle.coverage_audit = {
            "candidate_count": candidate_count,
            "exact_count": sum(1 for c in candidates if c.provenance == Provenance.EXACT_RULE),
            "semantic_near_count": semantic_count + sum(
                1 for c in candidates if c.provenance == Provenance.NORMALIZED_EQUIVALENT
            ),
            "review_count": review_count,
            "unsupported_count": unsupported_count + sum(
                1 for c in candidates if c.provenance == Provenance.UNKNOWN
            ),
            "unmatched_count": unmatched_count,
            "high_risk_review_count": review_count,
            "typed_renderer_count": typed_renderer_count,
            "typed_exact_count": sum(1 for c in candidates if c.provenance == Provenance.TYPED_RENDERER and c.confidence == Confidence.EXACT),
            "typed_semantic_near_count": sum(1 for c in candidates if c.provenance == Provenance.TYPED_RENDERER and c.confidence in (Confidence.LOW, Confidence.MEDIUM)),
            "typed_review_count": 0,
            "typed_covered_line_count": len(typed_covered_lines),
            "typed_uncovered_line_count": 0,
            "typed_interface_count": typed_interface_count,
            "typed_interface_exact_count": typed_interface_exact_count,
            "typed_interface_semantic_near_count": typed_interface_semantic_near_count,
            "typed_interface_access_exact_count": typed_interface_access_exact_count,
            "typed_interface_trunk_semantic_count": typed_interface_trunk_semantic_count,
            "typed_interface_context_complete_count": typed_interface_context_complete_count,
            "typed_interface_context_incomplete_count": typed_interface_context_incomplete_count,
            "typed_routing_count": typed_routing_count,
            "typed_routing_exact_count": typed_routing_exact_count,
            "typed_routing_semantic_near_count": typed_routing_semantic_near_count,
            "typed_routing_review_count": typed_routing_review_count,
            "typed_routing_ospf_count": typed_routing_ospf_count,
            "typed_routing_bgp_count": typed_routing_bgp_count,
            "typed_routing_isis_count": typed_routing_isis_count,
            "typed_routing_network_semantic_count": typed_routing_network_semantic_count,
            "typed_routing_neighbor_review_count": typed_routing_neighbor_review_count,
            "typed_routing_policy_review_count": typed_routing_policy_review_count,
            "typed_routing_auth_review_count": typed_routing_auth_review_count,
            "typed_ir_fallback": typed_ir_fallback,
        }
        return bundle
