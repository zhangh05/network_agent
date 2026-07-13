# -*- coding: utf-8 -*-
"""TranslationCandidate factory — unified provenance/confidence injection.

Replaces scattered bare-string returns with rich Candidate objects.
Each factory function produces a TranslationCandidate with correct
provenance/confidence/module/origin fields, eliminating the need for
unmatched-line guesswork.

Design principles:
  - ONLY deterministic, low-risk commands are eligible for exact_candidate.
  - HIGH-RISK modules (NAT, IPsec, AAA, QoS, route-policy, security-policy
    permit) MUST never be matched by the factory as exact_candidate.
  - All factory match functions must produce provenance=EXACT_RULE and
    confidence=HIGH when they are certain the translation is correct.
  - unmatched lines are assessed conservatively, never treated as exact rules.
  - If unsure, return None — let the caller fall back to manual_review.

Usage:
    from modules.config_translation.core.translation_candidate_factory import (
        exact_candidate, review_candidate, unsupported_candidate,
        semantic_near_candidate, high_risk_review_candidate,
    )
"""

from __future__ import annotations

import re
from typing import List, Optional

from modules.config_translation.core.translation_model import (
    TranslationCandidate, ClassifiedTranslation,
    Provenance, Confidence, Origin, TranslationTarget,
)


def _redact_secret(text: str) -> str:
    """Redact secret values in a line."""
    return re.sub(
        r"(?i)(password|cipher|community|key-string|secret|pre-shared-key|"
        r"preshared-key|preshare-key|auth-key|authentication-key|"
        r"encrypted-password|key)\s+\S+",
        r"\1 <redacted>",
        text,
    )


# ── Exact candidate factory ────────────────────────────────────────────────

def exact_candidate(
    source_line: str,
    candidate_line: str,
    from_vendor: str,
    to_vendor: str,
    module: str = "",
    domain: str = "",
    confidence: Confidence = Confidence.HIGH,
) -> TranslationCandidate:
    """Deterministic, safe translation with exact provenance."""
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=candidate_line,
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        source_platform=from_vendor,
        target_platform=to_vendor,
        module=module,
        domain=domain,
        provenance=Provenance.EXACT_RULE,
        confidence=confidence,
        origin=Origin.RAW_FALLBACK,
        risk_tags=[],
        evidence={"factory": "exact_candidate"},
    )


# ── Review candidate factory ───────────────────────────────────────────────

def review_candidate(
    source_line: str,
    reason: str,
    from_vendor: str = "",
    to_vendor: str = "",
    module: str = "",
    risk_level: str = "high",
    confirmation_points: Optional[List[str]] = None,
    redact: bool = True,
) -> TranslationCandidate:
    """Manual review required — source_line preserved, secrets redacted."""
    redacted = _redact_secret(source_line) if redact else source_line
    candidate = TranslationCandidate(
        source_line=source_line,
        candidate_line=f"# MANUAL_REVIEW {redacted}",
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        source_platform=from_vendor,
        target_platform=to_vendor,
        module=module,
        provenance=Provenance.RAW_STRING,
        confidence=Confidence.NONE,
        origin=Origin.RAW_FALLBACK,
        risk_tags=[reason, risk_level],
        evidence={
            "factory": "review_candidate",
            "reason": reason,
            "risk_level": risk_level,
            "confirmation_points": confirmation_points or [],
            "redaction_applied": redact,
        },
    )
    return candidate


# ── Unsupported candidate factory ──────────────────────────────────────────

def unsupported_candidate(
    source_line: str,
    reason: str,
    from_vendor: str = "",
    to_vendor: str = "",
    module: str = "",
) -> TranslationCandidate:
    """Cannot determine translation — route to unsupported. Redacts secrets."""
    redacted = _redact_secret(source_line)
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=f"# MANUAL_REVIEW unsupported source command: {redacted}",
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        source_platform=from_vendor,
        target_platform=to_vendor,
        module=module,
        provenance=Provenance.UNKNOWN,
        confidence=Confidence.NONE,
        origin=Origin.RAW_FALLBACK,
        risk_tags=[reason, "unsupported"],
        evidence={
            "factory": "unsupported_candidate",
            "reason": reason,
            "redaction_applied": ("<redacted>" in redacted),
        },
    )


# ── Semantic-near candidate factory ────────────────────────────────────────

def semantic_near_candidate(
    source_line: str,
    suggested_line: str,
    reason: str,
    from_vendor: str = "",
    to_vendor: str = "",
    module: str = "",
    confirmation_points: Optional[List[str]] = None,
) -> TranslationCandidate:
    """Target-like syntax suggested but not verified equivalent."""
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=suggested_line,
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        source_platform=from_vendor,
        target_platform=to_vendor,
        module=module,
        provenance=Provenance.NORMALIZED_EQUIVALENT,
        confidence=Confidence.MEDIUM,
        origin=Origin.RAW_FALLBACK,
        risk_tags=[reason, "semantic_near"],
        evidence={
            "factory": "semantic_near_candidate",
            "reason": reason,
            "confirmation_points": confirmation_points or [],
        },
    )


# ── High-risk review candidate ─────────────────────────────────────────────

def high_risk_review_candidate(
    source_line: str,
    module: str,
    from_vendor: str = "",
    to_vendor: str = "",
    confirmation_points: Optional[List[str]] = None,
) -> TranslationCandidate:
    """High-risk module (NAT/IPsec/AAA/QoS/route-policy) → manual review."""
    return review_candidate(
        source_line=source_line,
        reason=f"High-risk module: {module} — requires manual review",
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        module=module,
        risk_level="critical",
        confirmation_points=confirmation_points or [
            "Verify semantic equivalence",
            "Check parameter mapping",
            "Confirm target-vendor syntax",
        ],
    )


# ══════════════════════════════════════════════════════════════════════════
# Module-specific candidate functions (5 low-risk modules)
# ══════════════════════════════════════════════════════════════════════════

def candidate_hostname(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """hostname/sysname exact mapping."""
    if lower.startswith("hostname ") and to_vendor in ("huawei", "h3c"):
        name = stripped.split(maxsplit=1)[1]
        return exact_candidate(stripped, f"sysname {name}", from_vendor, to_vendor, module="system", confidence=Confidence.EXACT)
    if lower.startswith("sysname ") and to_vendor in ("cisco", "ruijie"):
        name = stripped.split(maxsplit=1)[1]
        return exact_candidate(stripped, f"hostname {name}", from_vendor, to_vendor, module="system", confidence=Confidence.EXACT)
    if lower.startswith("hostname ") and to_vendor in ("cisco", "ruijie"):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="system", confidence=Confidence.EXACT)
    if lower.startswith("sysname ") and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="system", confidence=Confidence.EXACT)
    return None


def candidate_vlan(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """VLAN creation — single Vlan or Vlan batch."""
    # Single VLAN: "vlan 10" → "vlan 10"
    m = re.match(r"vlan\s+(\d+)$", lower, re.IGNORECASE)
    if m:
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="vlan", confidence=Confidence.EXACT)
    # H3C/Huawei vlan batch → Cisco VLANs
    m = re.match(r"vlan\s+batch\s+([\d\s]+)$", lower, re.IGNORECASE)
    if m and to_vendor == "cisco":
        vlans_raw = m.group(1).strip()
        vlans = ",".join(re.split(r"\s+", vlans_raw))
        lines = [f"vlan {v}" for v in vlans]
        return exact_candidate(stripped, f"vlan {vlans}", from_vendor, to_vendor, module="vlan", confidence=Confidence.EXACT)
    return None


def candidate_description(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Interface description — same across all vendors."""
    if lower.startswith("description "):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="interface", confidence=Confidence.EXACT)
    return None


def candidate_static_route_complex(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Intercept complex static route variants (track/bfd/vrf/tag/name/pref/null0).

    Routes complex variants to semantic_near or manual_review.
    Returns None for simple dest+mask+next-hop (defer to candidate_static_route).
    """
    # ── VRF / vpn-instance check (high-priority, before standard pattern) ──
    if re.search(r"\b(vrf|vpn-instance)\b", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "static_route_vrf", "STATIC_ROUTE_VRF_CONTEXT",
                                from_vendor, to_vendor)

    # Match cisco-style: ip route PREFIX MASK NEXT_HOP [EXTRA]
    cisco_m = re.match(
        r"ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)", stripped, re.IGNORECASE
    )
    # Match huawei/h3c-style: ip route-static PREFIX MASK NEXT_HOP [EXTRA]
    hw_m = re.match(
        r"ip\s+route-static\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)", stripped, re.IGNORECASE
    )
    m = cisco_m or hw_m
    if not m:
        return None

    extra = m.group(4).lower().strip() if m.group(4) else ""
    route_base = f"{m.group(1)} {m.group(2)} {m.group(3)}"

    if not extra:
        return None  # simple route — defer to candidate_static_route

    # ── Context classification ──
    if any(kw in extra for kw in ["vrf ", "\bvrf ", "vpn-instance"]):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW {route_base} [STATIC_ROUTE_VRF_CONTEXT: {extra[:40]}]",
                                "static_route_vrf", "STATIC_ROUTE_VRF_CONTEXT",
                                from_vendor, to_vendor)
    if "track " in extra or extra.startswith("track "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW {route_base} [STATIC_ROUTE_TRACK_CONTEXT: {extra[:40]}]",
                                "static_route_track", "STATIC_ROUTE_TRACK_CONTEXT",
                                from_vendor, to_vendor)
    if "bfd" in extra:
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW {route_base} [STATIC_ROUTE_BFD_CONTEXT: {extra[:40]}]",
                                "static_route_bfd", "STATIC_ROUTE_BFD_CONTEXT",
                                from_vendor, to_vendor)
    if any(kw in extra for kw in ["null0", "null 0", "discard", "blackhole"]):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW {route_base} [STATIC_ROUTE_BLACKHOLE_CONTEXT: {extra[:40]}]",
                                "static_route_blackhole", "STATIC_ROUTE_BLACKHOLE_CONTEXT",
                                from_vendor, to_vendor)

    # semantic_near: metadata variants
    if any(kw in extra for kw in ["tag ", " tag "]) or extra.startswith("tag "):
        tgt_route = f"ip route-static {route_base} {extra}" if to_vendor in ("huawei", "h3c") else f"ip route {route_base} {extra}"
        return semantic_near_candidate(
            stripped, tgt_route or stripped,
            f"Static route with tag: {extra[:40]}",
            from_vendor, to_vendor, module="routing_static.tag",
            confirmation_points=[f"Verify tag syntax for {to_vendor}"])
    if any(kw in extra for kw in ["name ", "\bname ", "description "]):
        tgt_route = f"ip route-static {route_base} {extra}" if to_vendor in ("huawei", "h3c") else f"ip route {route_base} {extra}"
        return semantic_near_candidate(
            stripped, tgt_route or stripped,
            f"Static route with description/name: {extra[:40]}",
            from_vendor, to_vendor, module="routing_static.description",
            confirmation_points=[f"Verify description/name syntax for {to_vendor}"])
    if any(kw in extra for kw in ["preference ", "pref ", "distance "]) or re.search(r"\b\d{2,4}$", extra):
        # preference/distance or bare metric at end
        tgt_route = f"ip route-static {route_base} {extra}" if to_vendor in ("huawei", "h3c") else f"ip route {route_base} {extra}"
        return semantic_near_candidate(
            stripped, tgt_route or stripped,
            f"Static route with preference/distance: {extra[:40]}",
            from_vendor, to_vendor, module="routing_static.preference",
            confirmation_points=[f"Verify preference/distance for {to_vendor}"])
    if "permanent" in extra or "public" in extra:
        return semantic_near_candidate(
            stripped, stripped,
            f"Static route with permanent/public: {extra[:40]}",
            from_vendor, to_vendor, module="routing_static",
            confirmation_points=[f"Verify permanent/public semantics for {to_vendor}"])

    # Unrecognized extra → manual_review
    return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                            "static_route_complex", "static route with unrecognized modifier",
                            from_vendor, to_vendor)


def candidate_acl_policy_review(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """ACL / Policy / QoS commands → manual_review with proper source trace.

    Never produce deployable-exact for policy-class commands.
    """
    # ── ACL headers ──
    if re.match(r"^(ip\s+)?access-list\s+(standard|extended|\d+)\b", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_header", "ACL_HEADER_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="acl.header")
    if re.match(r"^acl\s+(number|name)\s+\S+", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_header", "ACL_HEADER_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="acl.header")
    # ── ACL named ip access-list ──
    if lower.startswith("ip access-list "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_header", "ACL_NAMED_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="acl.header")
    # ── ACL ip access-group binding ──
    if lower.startswith("ip access-group "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_binding", "ACL_BINDING_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="acl.binding")
    # ── permit any any (critical) ──
    if re.search(r"\bpermit\s+.*\bany\s+any\b", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_any_any", "ACL_DEFAULT_ANY_REVIEW_REQUIRED",
                                from_vendor, to_vendor, module="acl.rule")
    # ── Route-policy / route-map headers ──
    if re.match(r"^route-(policy|map)\s+\S+\s+(permit|deny)\s+\d+", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "route_policy", "ROUTE_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="route_policy.header")
    # ── if-match / match ip (route-policy sub-commands) ──
    if re.match(r"^(if-match|match\s+ip)\s", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "route_policy", "ROUTE_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="route_policy.match")
    # ── set / apply (route-policy actions) ──
    if re.match(r"^(set\s+|apply\s+)", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "route_policy", "ROUTE_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="route_policy.apply")
    # ── prefix-list / ip-prefix ──
    if lower.startswith("ip prefix-list ") or lower.startswith("ip ip-prefix "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "prefix_list", "PREFIX_LIST_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="prefix_list.basic")
    # ── distribute-list / filter-policy ──
    if re.match(r"^(distribute-list|filter-policy)\s", lower):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "filter_policy", "FILTER_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="filter_policy.basic")
    # ── QoS headers ──
    if lower.startswith("class-map "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="qos.classifier")
    if lower.startswith("policy-map "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="qos.policy")
    if lower.startswith("service-policy "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_BINDING_REVIEW_REQUIRED",
                                from_vendor, to_vendor, module="qos.binding")
    if lower.startswith("traffic classifier "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="qos.classifier")
    if lower.startswith("traffic behavior "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="qos.behavior")
    if lower.startswith("traffic policy ") or lower.startswith("traffic-policy "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "qos", "QOS_POLICY_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="qos.policy")
    if lower.startswith("acl number ") or lower.startswith("acl name "):
        return _static_review_candidate(stripped, f"# MANUAL_REVIEW: {stripped}",
                                "acl_header", "ACL_HEADER_CONTEXT_REQUIRED",
                                from_vendor, to_vendor, module="acl.header")
    return None


def _static_review_candidate(source_line: str, candidate_line: str, tag: str, reason: str,
                     from_vendor: str = "", to_vendor: str = "", module: str = "",
                     confidence: Confidence | None = None) -> TranslationCandidate:
    """Generate a manual_review candidate with proper source trace."""
    return TranslationCandidate(
        source_line=source_line,
        candidate_line=candidate_line,
        source_platform=from_vendor,
        target_platform=to_vendor,
        from_vendor=from_vendor,
        to_vendor=to_vendor,
        domain="routing",
        module=module or tag,
        provenance=Provenance.NORMALIZED_EQUIVALENT,
        confidence=confidence or Confidence.LOW,
        risk_tags=[tag, "manual_review"],
        evidence={
            "reason": reason,
            "source_excerpt": source_line,
        },
        origin=Origin.RAW_FALLBACK,
    )


def candidate_static_route(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Static route exact mapping."""
    # Cisco ip route → H3C/Huawei ip route-static
    m = re.match(r"ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(.+))?$", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        route = f"ip route-static {m.group(1)} {m.group(2)} {m.group(3)}"
        if m.group(4):
            route += f" {m.group(4)}"
        return exact_candidate(stripped, route, from_vendor, to_vendor, module="routing", confidence=Confidence.EXACT)
    # H3C/Huawei ip route-static → Cisco/Ruijie ip route
    m = re.match(r"ip\s+route-static\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(.+))?$", stripped, re.IGNORECASE)
    if m and to_vendor in ("cisco", "ruijie"):
        route = f"ip route {m.group(1)} {m.group(2)} {m.group(3)}"
        if m.group(4):
            route += f" {m.group(4)}"
        return exact_candidate(stripped, route, from_vendor, to_vendor, module="routing", confidence=Confidence.EXACT)
    return None


def candidate_access_trunk(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Access/trunk VLAN port mode mapping — semantic_near (requires interface context)."""
    reason = "interface mode/access-vlan requires interface context verification"
    # port link-type access → switchport mode access (semantic_near only)
    if lower == "port link-type access" and to_vendor == "cisco":
        return semantic_near_candidate(stripped, "switchport mode access", reason, from_vendor, to_vendor, module="interface")
    # port link-type trunk → switchport mode trunk (semantic_near only)
    if lower == "port link-type trunk" and to_vendor == "cisco":
        return semantic_near_candidate(stripped, "switchport mode trunk", reason, from_vendor, to_vendor, module="interface")
    # switchport mode access → port link-type access (semantic_near only)
    if lower == "switchport mode access" and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, "port link-type access", reason, from_vendor, to_vendor, module="interface")
    # switchport mode trunk → port link-type trunk (semantic_near only)
    if lower == "switchport mode trunk" and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, "port link-type trunk", reason, from_vendor, to_vendor, module="interface")
    # switchport access vlan N → port default vlan N (semantic_near only)
    m = re.match(r"switchport\s+access\s+vlan\s+(\d+)$", lower, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, f"port default vlan {m.group(1)}", reason, from_vendor, to_vendor, module="interface")
    # port default vlan N → switchport access vlan N (semantic_near only)
    m = re.match(r"port\s+default\s+vlan\s+(\d+)$", lower, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return semantic_near_candidate(stripped, f"switchport access vlan {m.group(1)}", reason, from_vendor, to_vendor, module="interface")
    return None


def candidate_interface_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Interface header (bare interface declaration). Excludes aggregation ports."""
    m = re.match(r"^interface\s+(\S+)", stripped, re.IGNORECASE)
    if not m:
        return None
    iface = m.group(1).lower()
    # Aggregation interfaces → let lag_header/eth_trunk handlers match first (registry order)
    if re.match(r"(eth-trunk|bridge-aggregation|port-channel|aggregateport)", iface, re.IGNORECASE):
        return None
    return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="interface", confidence=Confidence.EXACT)


def candidate_logging(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Logging / info-center non-sensitive lines."""
    if lower.startswith("logging host ") or lower.startswith("logging trap "):
        if to_vendor in ("huawei", "h3c"):
            if lower.startswith("logging host "):
                ip_part = stripped[len("logging host "):].strip()
                return exact_candidate(stripped, f"info-center loghost {ip_part}", from_vendor, to_vendor, module="management.logging", confidence=Confidence.EXACT)
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.logging", confidence=Confidence.EXACT)
    if lower.startswith("info-center loghost "):
        if to_vendor in ("cisco", "ruijie"):
            target = f"logging host {stripped[len('info-center loghost '):]}"
            return exact_candidate(stripped, target, from_vendor, to_vendor, module="management.logging", confidence=Confidence.EXACT)
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.logging", confidence=Confidence.EXACT)
    if lower.startswith("logging console ") or lower.startswith("logging monitor "):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.logging")
    return None


def candidate_ntp(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """NTP server/source non-sensitive lines."""
    if re.match(r"^ntp\s+server\s+\S+", lower) or re.match(r"^ntp\s+source\b", lower):
        if to_vendor in ("huawei", "h3c"):
            m = re.search(r"\S+\s+(\S+)$", stripped)  # extract server IP
            if "source" in lower:
                return exact_candidate(stripped, f"ntp-service source {stripped.split()[-1]}", from_vendor, to_vendor, module="management.ntp")
            server = m.group(1) if m else ""
            return exact_candidate(stripped, f"ntp-service unicast-server {server}", from_vendor, to_vendor, module="management.ntp", confidence=Confidence.EXACT)
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.ntp", confidence=Confidence.EXACT)
    if re.match(r"^ntp-service\s+unicast-server\s+\S+", lower) or re.match(r"^ntp-service\s+source\b", lower):
        if to_vendor in ("cisco", "ruijie"):
            m = re.search(r"\S+\s+(\S+)$", stripped)  # extract server IP
            server = m.group(1) if m else ""
            return exact_candidate(stripped, f"ntp server {server}", from_vendor, to_vendor, module="management.ntp")
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.ntp", confidence=Confidence.EXACT)
    return None


def candidate_stp_edge(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """STP edge / portfast simple equivalence."""
    if lower == "stp edged-port enable" and to_vendor == "cisco":
        return exact_candidate(stripped, "spanning-tree portfast", from_vendor, to_vendor, module="stp")
    if lower == "spanning-tree portfast" and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, "stp edged-port enable", from_vendor, to_vendor, module="stp")
    return None


def candidate_trunk_vlan(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Trunk allowed VLAN / trunk pvid mapping — semantic_near (requires interface context)."""
    reason = "trunk allowed/native/PVID semantics require interface context verification"
    m = re.match(r"port\s+trunk\s+allow-pass\s+vlan\s+([\d\s,]+)$", lower, re.IGNORECASE)
    if m and to_vendor == "cisco":
        vlans = ",".join(re.split(r"\s+", m.group(1).strip()))
        return semantic_near_candidate(stripped, f"switchport trunk allowed vlan {vlans}", reason, from_vendor, to_vendor, module="interface")
    m = re.match(r"switchport\s+trunk\s+allowed\s+vlan\s+([\d,\s]+)$", lower, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        vlans = " ".join(re.split(r"\s*,\s*", m.group(1).strip()))
        return semantic_near_candidate(stripped, f"port trunk allow-pass vlan {vlans}", reason, from_vendor, to_vendor, module="interface")
    m = re.match(r"port\s+trunk\s+pvid\s+vlan\s+(\d+)$", lower, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return semantic_near_candidate(stripped, f"switchport trunk native vlan {m.group(1)}", reason, from_vendor, to_vendor, module="interface")
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        # Same-family command: exact only if same vendor, else semantic_near
        if from_vendor == to_vendor:
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="interface", confidence=Confidence.EXACT)
        return semantic_near_candidate(stripped, stripped, reason, from_vendor, to_vendor, module="interface")
    m = re.match(r"switchport\s+trunk\s+native\s+vlan\s+(\d+)$", lower, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, f"port trunk pvid vlan {m.group(1)}", reason, from_vendor, to_vendor, module="interface")
    return None


def candidate_lag_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """LAG header: Eth-Trunk/Bridge-Aggregation/Port-channel → target mapping."""
    m = re.match(r"interface\s+(Eth-Trunk|Bridge-Aggregation)(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return exact_candidate(stripped, f"interface Port-channel{m.group(2)}", from_vendor, to_vendor, module="interface.lag", confidence=Confidence.EXACT)
    m = re.match(r"interface\s+(Port-channel)(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, f"interface Eth-Trunk{m.group(2)}", from_vendor, to_vendor, module="interface.lag", confidence=Confidence.EXACT)
    return None


def candidate_ospf_bgp_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """OSPF/BGP process header mapping."""
    m = re.match(r"router\s+ospf\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, f"ospf {m.group(1)}", from_vendor, to_vendor, module="ospf.process", confidence=Confidence.EXACT)
    m = re.match(r"ospf\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return exact_candidate(stripped, f"router ospf {m.group(1)}", from_vendor, to_vendor, module="ospf.process", confidence=Confidence.EXACT)
    m = re.match(r"router\s+bgp\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, f"bgp {m.group(1)}", from_vendor, to_vendor, module="bgp.process", confidence=Confidence.EXACT)
    m = re.match(r"bgp\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return exact_candidate(stripped, f"router bgp {m.group(1)}", from_vendor, to_vendor, module="bgp.process", confidence=Confidence.EXACT)
    return None


def candidate_ospf_bgp_network(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """OSPF/BGP network statements — semantic_near (requires routing-process context)."""
    reason = "network statement requires routing-process context verification"
    if re.match(r"^network\s+\S+\s+\S+\s+area\s+\S+", lower, re.IGNORECASE):
        return semantic_near_candidate(stripped, stripped, reason, from_vendor, to_vendor, module="ospf.network")
    if re.match(r"^network\s+\S+\s+mask\s+\S+", lower, re.IGNORECASE):
        return semantic_near_candidate(stripped, stripped, reason, from_vendor, to_vendor, module="bgp.network")
    return None


def candidate_neighbor_peer_base(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """BGP neighbor remote-as / peer as-number — semantic_near (requires address-family/policy context)."""
    reason = "BGP neighbor requires address-family/policy context verification"
    m = re.match(r"neighbor\s+(\S+)\s+remote-as\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, f"peer {m.group(1)} as-number {m.group(2)}", reason, from_vendor, to_vendor, module="bgp.neighbor")
    m = re.match(r"peer\s+(\S+)\s+as-number\s+(\d+)", stripped, re.IGNORECASE)
    if m and to_vendor == "cisco":
        return semantic_near_candidate(stripped, f"neighbor {m.group(1)} remote-as {m.group(2)}", reason, from_vendor, to_vendor, module="bgp.neighbor")
    # description on neighbor/peer: exact only if same vendor
    m = re.match(r"(neighbor|peer)\s+(\S+)\s+description\s+(.+)", stripped, re.IGNORECASE)
    if m:
        if from_vendor == to_vendor:
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="bgp.neighbor", confidence=Confidence.EXACT)
        return semantic_near_candidate(stripped, stripped, reason, from_vendor, to_vendor, module="bgp.neighbor")
    return None


def candidate_zone(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Zone / security-zone name — only for same-family targets."""
    m = re.match(r"zone\s+(\S+)$", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "h3c", "ruijie", "hillstone", "topsec", "dptech"):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.zone", confidence=Confidence.EXACT)
    m = re.match(r"security-zone\s+name\s+(\S+)$", stripped, re.IGNORECASE)
    if m and to_vendor in ("huawei", "huawei_usg", "h3c", "ruijie"):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.zone", confidence=Confidence.EXACT)
    # USG security-zone → hillstone/topsec: not exact
    if "security-zone" in lower and to_vendor in ("hillstone", "topsec"):
        return None  # routed to conservative unmatched-line handling
    return None


def candidate_address_object(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Address object / address-set header."""
    if re.match(r"^address\s+\S+", lower) and not re.search(r"\bmask\s+\S+|\bip\s+\S+", lower):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.address", confidence=Confidence.EXACT)
    if re.match(r"^ip\s+address-set\s+\S+", lower):
        if to_vendor in ("huawei", "huawei_usg", "h3c", "ruijie"):
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.address", confidence=Confidence.EXACT)
        return None  # USG address-set → non-Comware: not exact
    m = re.match(r"address\s+name\s+(\S+)\s+ip\s+(\S+)\s+(\S+)", stripped, re.IGNORECASE)
    if m:
        return exact_candidate(stripped, f"address {m.group(1)} {m.group(2)} {m.group(3)}", from_vendor, to_vendor, module="firewall.address")
    return None


def candidate_service_object(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Service object / service-set header."""
    if re.match(r"^service\s+\S+\s+(tcp|udp)\b", lower, re.IGNORECASE):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.service")
    if re.match(r"^ip\s+service-set\s+\S+", lower):
        if to_vendor in ("huawei", "huawei_usg", "h3c", "ruijie"):
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="firewall.service")
        return None  # USG service-set → non-Comware: not exact
    return None


def candidate_acl_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """ACL header — exact only for pure header; rule content → semantic_near."""
    # Pure ACL number header (no rule content): exact
    if re.match(r"^acl\s+(number\s+)?\d+$", lower, re.IGNORECASE):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="acl")
    # ACL number with rule: semantic_near (order/direction semantics uncertain)
    if re.match(r"^acl\s+(number\s+)?\d+\s+rule\b", lower, re.IGNORECASE):
        return semantic_near_candidate(stripped, stripped,
            "ACL rule semantics require direction/object/order verification",
            from_vendor, to_vendor, module="acl")
    # Cisco access-list permit/deny: semantic_near (order-sensitive)
    if re.match(r"^access-list\s+\d+\s+(permit|deny)\b", lower, re.IGNORECASE):
        return semantic_near_candidate(stripped, stripped,
            "ACL rule semantics require direction/object/order verification",
            from_vendor, to_vendor, module="acl")
    # Named ACL header: exact
    if re.match(r"^ip\s+access-list\s+(standard|extended)\s+\S+$", lower, re.IGNORECASE):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="acl")
    return None


def candidate_acl_binding(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """ACL binding on interface. Same-vendor passes through; cross-vendor requires review."""
    # Same-vendor: exact passthrough
    if from_vendor == to_vendor:
        if re.match(r"^(ip\s+)?access-group\s+\S+", lower, re.IGNORECASE):
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="acl.binding")
        if re.match(r"^traffic-filter\s+\S+", lower, re.IGNORECASE):
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="acl.binding")
        if re.match(r"^packet-filter\s+\S+", lower, re.IGNORECASE):
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="acl.binding")
    # Cross-vendor: return None — translate_bundle will route to manual_review
    return None


# ── Residue 4 specific handlers ───────────────────────────────────────────

def candidate_eth_trunk_to_h3c(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Eth-Trunk → H3C: route to semantic_near if Bridge-Aggregation mapping uncertain."""
    if to_vendor != "h3c":
        return None
    m = re.match(r"interface\s+Eth-Trunk(\d+)", stripped, re.IGNORECASE)
    if m:
        return semantic_near_candidate(
            stripped, f"interface Bridge-Aggregation{m.group(1)}",
            "Eth-Trunk → H3C: Bridge-Aggregation mapping needs verification",
            from_vendor, to_vendor, module="interface.lag",
            confirmation_points=["Verify Bridge-Aggregation index mapping", "Confirm L2/L3 mode"],
        )
    return None


def candidate_silent_interface_to_h3c(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """silent-interface → H3C: route to semantic_near or review."""
    if to_vendor != "h3c":
        return None
    if re.match(r"silent-interface\s+\S+", lower, re.IGNORECASE):
        return semantic_near_candidate(
            stripped, stripped,
            "silent-interface → H3C: OSPF passive-interface equivalent needs verification",
            from_vendor, to_vendor, module="ospf.passive_interface",
            confirmation_points=["Verify OSPF silent-interface semantic equivalence"],
        )
    return None


# ── Round 1 low-risk migrations ──────────────────────────────────────────

def candidate_logging_buffered(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """logging buffered ↔ info-center logbuffer (deterministic 1:1)."""
    m = re.match(r"^logging\s+buffered\s+(\d+)", lower)
    if m:
        target_line = f"info-center logbuffer size {m.group(1)}"
        return exact_candidate(stripped, target_line, from_vendor, to_vendor, module="management.logging")
    m = re.match(r"^info-center\s+logbuffer\s+size\s+(\d+)", lower)
    if m:
        target_line = f"logging buffered {m.group(1)}"
        return exact_candidate(stripped, target_line, from_vendor, to_vendor, module="management.logging")
    return None


def candidate_snmp_basic(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """SNMP non-secret basic commands (no community/password/key)."""
    # MUST NOT contain community/secret/key
    if re.search(r"\b(community|secret|key|cipher|password)\b", lower):
        return None
    # Cisco → Huawei SNMP
    m = re.match(r"^snmp-server\s+host\s+(\S+)", lower)
    if m:
        return exact_candidate(stripped, f"snmp-agent target-host trap address {m.group(1)}",
                               from_vendor, to_vendor, module="management.snmp")
    m = re.match(r"^snmp-server\s+location\s+(.+)", lower)
    if m:
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.snmp")
    m = re.match(r"^snmp-server\s+contact\s+(.+)", lower)
    if m:
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.snmp")
    # snmp-agent sys-info location/contact
    m = re.match(r"^snmp-agent\s+sys-info\s+(location|contact)\s+(.+)", lower)
    if m:
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.snmp")
    return None


def candidate_vrf_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """VRF header only (ip vrf / ip vpn-instance). Not route-target/import/export."""
    # Must NOT contain route-target/import/export
    if re.search(r"\b(route-target|import|export|leaking|rd)\b", lower):
        return None
    m = re.match(r"^ip\s+vrf\s+(\S+)", lower)
    if m:
        return exact_candidate(stripped, f"ip vpn-instance {m.group(1)}",
                               from_vendor, to_vendor, module="router.vrf")
    m = re.match(r"^ip\s+vpn-instance\s+(\S+)", lower)
    if m:
        return exact_candidate(stripped, f"ip vrf {m.group(1)}",
                               from_vendor, to_vendor, module="router.vrf")
    return None


def candidate_undo_no(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """undo → no for low-risk deterministic commands (H3C/Huawei → Cisco).

    ONLY low-risk: undo shutdown, undo portswitch, undo negotiation auto.
    NOT: undo security-policy, undo ipsec, undo aaa, undo nat.
    """
    if to_vendor != "cisco":
        return None
    if not lower.startswith("undo "):
        return None
    # High-risk undo patterns → never exact
    if re.search(r"\b(security-policy|ipsec|ike|nat|aaa|radius|tacacs|route-policy|crypto|vpn)",
                 lower):
        return None
    # Low-risk deterministic: undo shutdown, undo portswitch, undo negotiation auto
    if lower == "undo shutdown":
        return exact_candidate(stripped, "no shutdown", from_vendor, to_vendor, module="interface")
    if lower == "undo portswitch":
        return exact_candidate(stripped, "no switchport", from_vendor, to_vendor, module="interface")
    if lower == "undo negotiation auto":
        return exact_candidate(stripped, "no negotiation auto", from_vendor, to_vendor, module="interface")
    return None


def candidate_no_switchport(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """no switchport ↔ undo portswitch (deterministic 1:1)."""
    if lower == "no switchport":
        return exact_candidate(stripped, "undo portswitch", from_vendor, to_vendor, module="interface.switchport")
    if lower == "undo portswitch":
        return exact_candidate(stripped, "no switchport", from_vendor, to_vendor, module="interface.switchport")
    return None


def candidate_stp_enable(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """stp enable ↔ spanning-tree (basic enable, not mode/edge)."""
    if lower == "stp enable":
        return exact_candidate(stripped, "spanning-tree", from_vendor, to_vendor, module="stp")
    if lower == "spanning-tree" and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, "stp enable", from_vendor, to_vendor, module="stp")
    return None


# ── Round 2 low-risk matchers ────────────────────────────────────────────

def candidate_banner(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """banner motd/exec/login → manual_review (safe, but not deterministically deployable)."""
    if re.match(r"^banner\s+(motd|exec|login)\s", lower):
        return _static_review_candidate(stripped, "Banner: requires manual review for content",
                                from_vendor, to_vendor, module="management.banner")
    return None


def candidate_description_extended(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """description/name lines → exact passthrough (deterministic text labels)."""
    if lower.startswith("description ") or lower.startswith("name "):
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="description")
    return None


def candidate_eth_trunk_header(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """eth-trunk / Bridge-Aggregation / port-channel header → review (cross-family unsafe).

    LAG naming is vendor-specific. Deterministic mapping is not safe cross-family.
    Always route to manual_review to avoid residue false positives.
    """
    if re.match(r"^(eth-trunk|bridge-aggregation|port-channel)\s+\d+", lower, re.I):
        return _static_review_candidate(stripped, "LAG header: cross-family mapping requires manual review",
                                from_vendor, to_vendor, module="lag")
    if re.match(r"^interface\s+(eth-trunk|bridge-aggregation|port-channel)\d+", lower, re.I):
        return _static_review_candidate(stripped, "LAG interface: cross-family mapping requires manual review",
                                from_vendor, to_vendor, module="lag")
    return None


def candidate_shutdown(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Interface shutdown/no shutdown — deterministic 1:1 mapping."""
    # All vendors: 'shutdown' is universal
    if lower == "shutdown":
        return exact_candidate(stripped, "shutdown", from_vendor, to_vendor, module="interface.shutdown")
    # Huawei/H3C/Ruijie 'undo shutdown' → Cisco 'no shutdown'
    if lower in ("undo shutdown", "undo  shutdown"):
        return exact_candidate(stripped, "no shutdown", from_vendor, to_vendor, module="interface.shutdown")
    # Cisco 'no shutdown' → Huawei/H3C/Ruijie 'undo shutdown'
    if lower == "no shutdown":
        return exact_candidate(stripped, "undo shutdown", from_vendor, to_vendor, module="interface.shutdown")
    return None


def candidate_lldp(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """LLDP enable/disable — deterministic 1:1 mapping."""
    # Huawei/H3C/Ruijie 'lldp enable' → Cisco 'lldp run'
    if lower == "lldp enable":
        return exact_candidate(stripped, "lldp run", from_vendor, to_vendor, module="management.lldp")
    # Cisco 'lldp run' → Huawei/H3C/Ruijie 'lldp enable'
    if lower == "lldp run":
        return exact_candidate(stripped, "lldp enable", from_vendor, to_vendor, module="management.lldp")
    # Huawei/H3C/Ruijie 'undo lldp enable' → Cisco 'no lldp run'
    if lower in ("undo lldp enable", "undo  lldp enable"):
        return exact_candidate(stripped, "no lldp run", from_vendor, to_vendor, module="management.lldp")
    # Cisco 'no lldp run' → Huawei/H3C/Ruijie 'undo lldp enable'
    if lower == "no lldp run":
        return exact_candidate(stripped, "undo lldp enable", from_vendor, to_vendor, module="management.lldp")
    # LLDP holdtime/timer/hold-multiplier (info level, deterministic)
    m = re.match(r"^lldp\s+hold-multiplier\s+(\d+)", lower)
    if m:
        return exact_candidate(stripped, f"lldp timer hold {m.group(1)}",
                               from_vendor, to_vendor, module="management.lldp")
    m = re.match(r"^lldp\s+timer\s+hold\s+(\d+)", lower)
    if m:
        return exact_candidate(stripped, f"lldp hold-multiplier {m.group(1)}",
                               from_vendor, to_vendor, module="management.lldp")
    return None


def candidate_vlan_batch(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """VLAN batch creation → normalize to target syntax (semantic_near)."""
    m = re.match(r"^vlan\s+batch\s+(.+)", lower)
    if m:
        vlan_spec = m.group(1).strip()
        # Huawei/H3C/Ruijie 'vlan batch 10 20 30' → Cisco needs 'vlan 10', 'vlan 20', ...
        # Since it may generate multiple lines, route as semantic_near
        return semantic_near_candidate(
            stripped,
            f"vlan {vlan_spec}",
            f"VLAN batch: translate to target vendor syntax (may need line splitting)",
            from_vendor, to_vendor,
            module="vlan.batch",
            confirmation_points=[f"Verify VLAN range/batch syntax for {to_vendor}"],
        )
    return None


def candidate_l2_semantic(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """L2 semantic-near mappings: bpduguard, storm-control, etc.

    These features have cross-vendor equivalents but the syntax differs
    significantly -> route as semantic_near with a suggested translation.
    """
    # spanning-tree bpduguard enable → stp bpdu-guard enable (semantic_near)
    if re.match(r"spanning-tree\s+bpduguard\s+enable", lower):
        if to_vendor in ("huawei", "h3c"):
            return semantic_near_candidate(
                stripped, "stp bpdu-guard enable",
                "spanning-tree bpduguard → stp bpdu-guard (semantic_near)",
                from_vendor, to_vendor, module="interface.stp_bpduguard",
                confirmation_points=[f"Verify BPDU guard syntax for {to_vendor}"])
    if re.match(r"stp\s+bpdu-guard\s+enable", lower):
        if to_vendor in ("cisco", "ruijie"):
            return semantic_near_candidate(
                stripped, "spanning-tree bpduguard enable",
                "stp bpdu-guard → spanning-tree bpduguard (semantic_near)",
                from_vendor, to_vendor, module="interface.stp_bpduguard",
                confirmation_points=[f"Verify bpduguard syntax for {to_vendor}"])
    # storm-control → storm-control suppression (semantic_near)
    m = re.match(r"storm-control\s+(broadcast|multicast|unicast)\s+level\s+(\S+)", lower)
    if m:
        typ, val = m.group(1), m.group(2)
        if to_vendor in ("huawei", "h3c"):
            return semantic_near_candidate(
                stripped, f"{typ}-suppression {val}",
                f"storm-control {typ} → {typ}-suppression (semantic_near)",
                from_vendor, to_vendor, module="storm_control",
                confirmation_points=[f"Verify storm control syntax for {to_vendor}"])
    return None


# ── v0.9.2 expanded factory matchers ──

def candidate_firewall_enable(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    if lower == "firewall enable" and to_vendor in ("cisco", "ruijie"):
        return semantic_near_candidate(stripped, "ip firewall",
            "firewall enable → Cisco: ip firewall (semantic_near)", from_vendor, to_vendor, module="firewall",
            confirmation_points=["Verify firewall enable syntax for target vendor"])
    return None

def candidate_ssh_server(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    if lower == "ssh server enable" and to_vendor == "cisco":
        return exact_candidate(stripped, "ip ssh server enable", from_vendor, to_vendor, module="management.ssh")
    if lower == "ip ssh server enable" and to_vendor in ("huawei", "h3c", "ruijie"):
        return exact_candidate(stripped, "ssh server enable", from_vendor, to_vendor, module="management.ssh")
    return None

def candidate_http_server(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    if lower == "ip http server" and to_vendor in ("huawei", "h3c"):
        return exact_candidate(stripped, "http server enable", from_vendor, to_vendor, module="management.http")
    if lower == "http server enable" and to_vendor == "cisco":
        return exact_candidate(stripped, "ip http server", from_vendor, to_vendor, module="management.http")
    if lower in ("ip http secure-server", "ip https server") and to_vendor in ("huawei", "h3c"):
        return exact_candidate(stripped, "http secure-server enable", from_vendor, to_vendor, module="management.http")
    return None

def candidate_vty_interface(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    m = re.match(r"user-interface\s+vty\s+(\d+)\s+(\d+)", lower)
    if m and to_vendor == "cisco":
        return semantic_near_candidate(stripped, f"line vty {m.group(1)} {m.group(2)}",
            "user-interface vty → line vty", from_vendor, to_vendor, module="management.vty")
    m = re.match(r"line\s+vty\s+(\d+)\s+(\d+)", lower)
    if m and to_vendor in ("huawei", "h3c", "ruijie"):
        return semantic_near_candidate(stripped, f"user-interface vty {m.group(1)} {m.group(2)}",
            "line vty → user-interface vty", from_vendor, to_vendor, module="management.vty")
    return None

def candidate_dhcp(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    if lower == "dhcp enable":
        return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.dhcp")
    if lower.startswith(("dhcp server ", "dhcp relay ")):
        if from_vendor == to_vendor:
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="management.dhcp")
        return semantic_near_candidate(stripped, stripped, "DHCP cross-vendor", from_vendor, to_vendor, module="management.dhcp")
    return None

def candidate_bfd(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    if re.match(r"bfd\s+", lower):
        if from_vendor == to_vendor:
            return exact_candidate(stripped, stripped, from_vendor, to_vendor, module="routing.bfd")
        return semantic_near_candidate(stripped, stripped, "BFD cross-vendor", from_vendor, to_vendor, module="routing.bfd")
    return None


# ── Unified registry (function + metadata) ───────────────────────────────────
# Each entry: (func, name, category, expected_target, risk_level, requires_context, high_risk)
_CANDIDATE_REGISTRY = [
    (candidate_firewall_enable, "firewall_enable", "firewall", "exact", "low", False, False),
    (candidate_ssh_server, "ssh_server", "management", "exact", "low", False, False),
    (candidate_http_server, "http_server", "management", "exact", "low", False, False),
    (candidate_vty_interface, "vty_interface", "management", "exact", "low", False, False),
    (candidate_dhcp, "dhcp", "management", "exact", "low", False, False),
    (candidate_bfd, "bfd", "routing.bfd", "semantic_near", "low", True, False),
    (candidate_hostname, "hostname", "management", "exact", "low", False, False),
    (candidate_logging, "logging", "management", "exact", "low", False, False),
    (candidate_logging_buffered, "logging_buffered", "management", "exact", "low", False, False),
    (candidate_snmp_basic, "snmp_basic", "management", "exact", "low", False, False),
    (candidate_ntp, "ntp", "management", "exact", "low", False, False),
    (candidate_banner, "banner", "management", "review", "medium", True, False),
    (candidate_description_extended, "description_extended", "management", "exact", "low", False, False),
    (candidate_lldp, "lldp", "management", "exact", "low", False, False),
    (candidate_lag_header, "lag_header", "interface", "exact", "low", False, False),
    (candidate_eth_trunk_header, "eth_trunk_header", "interface", "review", "medium", True, False),
    (candidate_eth_trunk_to_h3c, "eth_trunk_to_h3c", "interface", "semantic_near", "medium", True, False),
    (candidate_silent_interface_to_h3c, "silent_interface", "interface", "semantic_near", "medium", True, False),
    (candidate_interface_header, "interface_header", "interface", "exact", "low", False, False),
    (candidate_shutdown, "shutdown", "interface", "exact", "low", False, False),
    (candidate_vlan, "vlan_single", "switch", "exact", "low", False, False),
    (candidate_vlan_batch, "vlan_batch", "switch", "semantic_near", "medium", True, False),
    (candidate_l2_semantic, "l2_semantic", "switch", "semantic_near", "medium", True, False),
    (candidate_description, "description", "interface", "exact", "low", False, False),
    (candidate_access_trunk, "access_trunk", "switch", "semantic_near", "medium", True, False),
    (candidate_trunk_vlan, "trunk_vlan", "switch", "semantic_near", "medium", True, False),
    (candidate_stp_edge, "stp_edge", "switch", "semantic_near", "low", True, False),
    (candidate_stp_enable, "stp_enable", "switch", "exact", "low", False, False),
    (candidate_no_switchport, "no_switchport", "switch", "exact", "low", False, False),
    (candidate_static_route_complex, "static_route_complex", "routing", "semantic_near", "high", True, False),
    (candidate_acl_policy_review, "acl_policy_review", "security", "manual_review", "high", True, False),
    (candidate_static_route, "static_route", "routing", "exact", "low", False, False),
    (candidate_vrf_header, "vrf_header", "routing", "semantic_near", "medium", True, False),
    (candidate_ospf_bgp_header, "ospf_bgp_header", "routing", "exact", "low", False, False),
    (candidate_ospf_bgp_network, "ospf_bgp_network", "routing", "semantic_near", "medium", True, False),
    (candidate_neighbor_peer_base, "neighbor_peer", "routing", "semantic_near", "medium", True, False),
    (candidate_zone, "zone", "firewall", "exact", "low", False, False),
    (candidate_address_object, "address_object", "firewall", "exact", "low", False, False),
    (candidate_service_object, "service_object", "firewall", "exact", "low", False, False),
    (candidate_acl_header, "acl_header", "acl", "exact", "low", False, False),
    (candidate_acl_binding, "acl_binding", "acl", "semantic_near", "medium", True, False),
    (candidate_undo_no, "undo_no", "management", "exact", "low", False, False),
]


def try_make_candidate(stripped: str, lower: str, from_vendor: str, to_vendor: str) -> Optional[TranslationCandidate]:
    """Try all module candidate functions. Returns first match or None."""
    for func, *_ in _CANDIDATE_REGISTRY:
        result = func(stripped, lower, from_vendor, to_vendor)
        if result is not None:
            return result
    return None
