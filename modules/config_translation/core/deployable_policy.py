# -*- coding: utf-8 -*-
"""Unified DeployablePolicy — single gatekeeper for deployable_config.

All fallback / module_graph / graph state paths that write to deployable_config
MUST pass through DeployablePolicy.  The default stance is: a line is NOT
deployable unless the policy explicitly classifies it as safe_deployable.

This replaces the old logic: "a string without MANUAL_REVIEW → deployable".

Design:
    CandidateLine (input)  →  DeployablePolicy.classify()  →  ClassifiedLine (output)

Entry point:
    DeployablePolicy.classify(candidate: CandidateLine) → ClassifiedLine
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set


# ── Enums ──────────────────────────────────────────────────────────────────

class DeployableDecision(str, Enum):
    DEPLOYABLE = "deployable"
    MANUAL_REVIEW = "manual_review"
    SEMANTIC_NEAR = "semantic_near"
    UNSUPPORTED = "unsupported"


class Provenance(str, Enum):
    EXACT_RULE = "exact_rule"           # deterministic rule-based translation
    TYPED_RENDERER = "typed_renderer"    # strong-type IR → renderer
    NORMALIZED_EQUIVALENT = "normalized_equivalent"  # cross-vendor normalized match
    RAW_STRING = "raw_string"      # old-style string from translator
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    EXACT = "exact"      # 100% certain
    HIGH = "high"        # >95%, rule-based with known semantics
    MEDIUM = "medium"    # probabilistic match
    LOW = "low"          # best-effort guess
    NONE = "none"        # no confidence — default reject


# ── High-risk module keywords ──────────────────────────────────────────────
# Lines matching these are default → manual_review, NOT deployable.

_HIGH_RISK_PATTERNS: list[tuple[str, str]] = [
    # NAT (specific commands, not the word alone)
    (r"\bnat\s+(outbound|server|static|source|destination|policy|rule|address-group)\b", "NAT"),
    (r"\bsource-nat\b", "source-nat"),
    (r"\bdestination-nat\b", "destination-nat"),
    # IPsec / IKE / crypto / tunnel / VPN
    (r"\bipsec\b", "IPsec"),
    (r"\bike\s+(proposal|peer|dpd)\b", "IKE"),
    (r"\bcrypto\s+(map|isakmp|ipsec)\b", "crypto"),
    (r"\btunnel\s+(mode|source|destination|protection)\b", "tunnel/VPN"),
    # AAA / RADIUS / TACACS
    (r"\baaa\s+(authentication|authorization|accounting)", "AAA"),
    (r"\bradius\b", "RADIUS"),
    (r"\btacacs", "TACACS+"),
    (r"(?i)\blocal-user\b", "local-user"),
    # QoS
    (r"\bqos\s+(car|gts|cbq)\b", "QoS"),
    (r"\bservice-policy\b", "service-policy"),
    (r"\btraffic-policy\b", "traffic-policy"),
    # Route policy / route-map (should be semantic_near, not raw deployable)
    (r"\broute-policy\b", "route-policy"),
    (r"\broute-map\b", "route-map"),
    # BGP policy sub-commands (NOT the bgp header)
    (r"\bpeer\s+\S+\s+route-policy\b", "BGP peer route-policy"),
    (r"\bpeer\s+\S+\s+prefix-list\b", "BGP peer prefix-list"),
    (r"\bpeer\s+\S+\s+password\b", "BGP peer password"),
    # OSPF redistribute / NSSA / auth (sub-commands, NOT the ospf header)
    (r"\bredistribute\b", "OSPF redistribute"),
    (r"\bnssa\b", "OSPF NSSA"),
    (r"(?i)authentication\s+(message-digest|key-chain|md5)\b", "OSPF authentication"),
    # Firewall/security policy (block-level — should not be raw)
    (r"\bsecurity-policy\b", "security-policy"),
    # PBR
    (r"\bpbr\b", "PBR"),
    (r"\bpolicy-based-route\b", "policy-based-route"),
    # VRF leaking
    (r"\bvrf\s+leaking\b", "VRF leaking"),
]


def _is_high_risk(line: str) -> bool:
    """Check if a line matches high-risk module patterns."""
    stripped = line.strip().lower()
    if not stripped:
        return False
    for pattern, _label in _HIGH_RISK_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


# ── Forbidden-in-deployable markers ────────────────────────────────────────

_FORBIDDEN_MARKERS: list[str] = [
    "manual_review", "unsupported", "semantic_near",
    "source_excerpt", "not directly deployable", "risk summary",
    "action required", "requires confirmation", "suggested_target_lines",
]


def _contains_forbidden_marker(line: str) -> bool:
    """Check if a line contains forbidden review/risk/evidence markers."""
    lower = line.lower()
    return any(m in lower for m in _FORBIDDEN_MARKERS)


def _is_source_residue(line: str, source_platform: str, target_platform: str) -> bool:
    """Quick residue check: cross-vendor keywords that don't belong in target."""
    if not source_platform or not target_platform:
        return False
    lower = line.strip().lower()
    # Ruijie uses Cisco-like syntax — treat as Cisco-family for residue
    is_cisco_family = lambda p: p.lower() in ("ios", "cisco", "ruijie")
    is_comware_family = lambda p: p.lower() in ("huawei", "h3c")

    # Cisco keywords in non-Cisco/non-Ruijie targets
    if not is_cisco_family(target_platform):
        cisco_kw = ["switchport", "hostname ", "spanning-tree", "standby ",
                     "channel-group", "access-group", "nameif", "security-level"]
        for kw in cisco_kw:
            if kw in lower:
                return True
    # Comware keywords in Cisco/Ruijie targets
    if is_cisco_family(target_platform):
        hw_kw = ["sysname", "vlan batch", "undo ", "port link-type",
                  "port trunk", "port default vlan", "ip route-static",
                  "eth-trunk", "bridge-aggregation"]
        for kw in hw_kw:
            if kw in lower:
                return True
    return False


def _is_secret_line(line: str) -> bool:
    """Quick check: does a line contain plaintext secrets?"""
    lower = line.strip().lower()
    secret_patterns = [
        r"(?i)password\s+(?!<\w+>)\S+",
        r"(?i)cipher\s+(?!<\w+>)\S+",
        r"(?i)community\s+(?!<\w+>)\S+",
        r"(?i)key-string\s+(?!<\w+>)\S+",
        r"(?i)secret\s+(?!<\w+>)\S+",
        r"(?i)pre-shared-key\s+(?!<\w+>)\S+",
        r"(?i)preshared-key\s+(?!<\w+>)\S+",
        r"(?i)auth-key\s+(?!<\w+>)\S+",
    ]
    for pat in secret_patterns:
        if re.search(pat, lower):
            return True
    return False


def _is_default_any_risk(line: str) -> bool:
    """Quick check: does a line contain dangerous broad-permit patterns?"""
    lower = line.strip().lower()
    if re.search(r"(?i)permit\s+any\s+any", lower):
        return True
    if re.search(r"(?i)permit\s+ip\s+any\s+any", lower):
        return True
    if re.search(r"(?i)rule\s+\S+\s+permit\s+ip\s+source\s+any\s+destination\s+any", lower):
        return True
    if re.search(r"(?i)source\s+any\s+destination\s+any\s+service\s+any", lower):
        return True
    if re.search(r"(?i)source-zone\s+any\s+destination-zone\s+any.*action\s+permit", lower):
        return True
    return False


# ── Source-command detection (for cross-vendor verbatim check) ─────────────

def _looks_like_source_command(line: str, source_platform: str) -> bool:
    """Check if a line looks like it's still in source-vendor syntax."""
    if not source_platform:
        return False
    lower = line.strip().lower()
    if "h3c" in source_platform.lower() or "comware" in source_platform.lower():
        h3c_kw = ["sysname", "vlan batch", "undo ", "port link-type",
                   "port trunk permit", "port default vlan", "ip route-static",
                   "bridge-aggregation", "ntp-service", "info-center",
                   "snmp-agent", "stp "]
        return any(kw in lower for kw in h3c_kw)
    if "huawei" in source_platform.lower():
        hw_kw = ["sysname", "vlan batch", "undo ", "port link-type",
                  "port trunk permit", "ip route-static", "ntp-service",
                  "info-center", "snmp-agent"]
        return any(kw in lower for kw in hw_kw)
    if "cisco" in source_platform.lower() or "ios" in source_platform.lower():
        cisco_kw = ["switchport", "hostname ", "spanning-tree", "standby ",
                     "channel-group", "access-group", "nameif"]
        return any(kw in lower for kw in cisco_kw)
    return False


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class CandidateLine:
    """Input to DeployablePolicy — a line being considered for deployable_config."""

    line: str                           # the candidate line (after translation)
    source_line: str = ""               # original source line (for cross-reference)
    source_platform: str = ""           # source vendor platform
    target_platform: str = ""           # target vendor platform
    from_vendor: str = ""               # source vendor name
    to_vendor: str = ""                 # target vendor name
    module: str = ""                    # feature module name (vlan, ospf, etc.)
    provenance: Provenance = Provenance.RAW_STRING
    confidence: Confidence = Confidence.NONE
    risk_tags: List[str] = field(default_factory=list)


@dataclass
class ClassifiedLine:
    """Output from DeployablePolicy — classified line with target layer."""

    target: DeployableDecision          # which output layer
    line: str                           # the line text (may be modified/redacted)
    source_line: str = ""               # original source line for audit
    reason: str = ""                    # classification reason
    risk_level: str = "medium"          # high / medium / low
    provenance: Provenance = Provenance.RAW_STRING
    confidence: Confidence = Confidence.NONE

    @property
    def is_deployable(self) -> bool:
        return self.target == DeployableDecision.DEPLOYABLE


# ── DeployablePolicy ───────────────────────────────────────────────────────

class DeployablePolicy:
    """Single gatekeeper for deployable_config.

    Usage:
        policy = DeployablePolicy()
        classified = policy.classify(candidate)
        if classified.is_deployable:
            deployable_lines.append(classified.line)

        # New model:
        from modules.config_translation.core.translation_model import TranslationCandidate, ClassifiedTranslation
        result = policy.classify_translation(candidate)  # → ClassifiedTranslation
    """

    def classify_translation(self, candidate) -> "ClassifiedTranslation":
        """Classify using the unified TranslationCandidate model.

        Accepts core.translation_model.TranslationCandidate,
        returns core.translation_model.ClassifiedTranslation.
        """
        from modules.config_translation.core.translation_model import (
            ClassifiedTranslation, TranslationTarget, Provenance as TMProv, Confidence as TMConf
        )

        result = self.classify(CandidateLine(
            line=candidate.candidate_line,
            source_line=candidate.source_line,
            source_platform=candidate.source_platform,
            target_platform=candidate.target_platform,
            from_vendor=candidate.from_vendor,
            to_vendor=candidate.to_vendor,
            module=candidate.module,
            provenance=Provenance(candidate.provenance.value) if isinstance(candidate.provenance, TMProv) else Provenance.RAW_STRING,
            confidence=Confidence(candidate.confidence.value) if isinstance(candidate.confidence, TMConf) else Confidence.NONE,
            risk_tags=candidate.risk_tags,
        ))

        # Map decision
        target_map = {
            DeployableDecision.DEPLOYABLE: TranslationTarget.DEPLOYABLE,
            DeployableDecision.MANUAL_REVIEW: TranslationTarget.MANUAL_REVIEW,
            DeployableDecision.SEMANTIC_NEAR: TranslationTarget.SEMANTIC_NEAR,
            DeployableDecision.UNSUPPORTED: TranslationTarget.UNSUPPORTED,
        }

        return ClassifiedTranslation(
            target=target_map.get(result.target, TranslationTarget.UNKNOWN),
            line=result.line,
            source_line=result.source_line,
            reason=result.reason,
            risk_level=result.risk_level,
            provenance=TMProv(result.provenance.value) if hasattr(result.provenance, 'value') else TMProv.RAW_STRING,
            confidence=TMConf(result.confidence.value) if hasattr(result.confidence, 'value') else TMConf.NONE,
            module=candidate.module,
            origin=candidate.origin.value if hasattr(candidate, 'origin') and hasattr(candidate.origin, 'value') else "raw_fallback",
        )

    def classify(self, candidate: CandidateLine) -> ClassifiedLine:
        """Classify a candidate line into deployable/manual_review/semantic_near/unsupported.

        Only lines that pass ALL checks are marked DEPLOYABLE.
        Default: MANUAL_REVIEW or UNSUPPORTED — never DEPLOYABLE.
        """
        line = candidate.line.strip()
        source_line = candidate.source_line.strip()

        # ── Empty / comment → skip (not a candidate for any layer) ──
        if not line:
            return ClassifiedLine(
                target=DeployableDecision.UNSUPPORTED,
                line=line, source_line=source_line,
                reason="Empty line",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Explicit MANUAL_REVIEW marker → keep as is ──
        if "MANUAL_REVIEW" in line.upper():
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason="Explicit MANUAL_REVIEW marker in line",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Forbidden markers in line → reject from deployable ──
        if _contains_forbidden_marker(line):
            return ClassifiedLine(
                target=DeployableDecision.UNSUPPORTED,
                line=line, source_line=source_line,
                reason="Line contains forbidden review/risk/evidence marker",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Provenance check ──
        if candidate.provenance not in (
            Provenance.EXACT_RULE,
            Provenance.TYPED_RENDERER,
            Provenance.NORMALIZED_EQUIVALENT,
        ):
            # Retired string or unknown provenance → not safe for deployable
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason=f"Unsafe provenance: {candidate.provenance.value}",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Confidence check ──
        if candidate.confidence not in (Confidence.EXACT, Confidence.HIGH):
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason=f"Insufficient confidence: {candidate.confidence.value}",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── High-risk module → manual_review ──
        if _is_high_risk(line):
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason="High-risk module — requires manual review",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Secret check ──
        if _is_secret_line(line):
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason="Line contains plaintext secret/credential",
                risk_level="critical",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Default-any risk ──
        if _is_default_any_risk(line):
            return ClassifiedLine(
                target=DeployableDecision.MANUAL_REVIEW,
                line=line, source_line=source_line,
                reason="Line contains dangerous wide-permit (default-any risk)",
                risk_level="critical",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Source residue (cross-vendor keyword leakage) ──
        if _is_source_residue(line, candidate.source_platform, candidate.target_platform):
            return ClassifiedLine(
                target=DeployableDecision.UNSUPPORTED,
                line=line, source_line=source_line,
                reason="Source-vendor executable residue in target config",
                risk_level="high",
                provenance=candidate.provenance,
                confidence=candidate.confidence,
            )

        # ── Cross-vendor verbatim check (skip for EXACT_RULE / TYPED_RENDERER: explicitly confirmed) ──
        if (candidate.source_platform and candidate.target_platform
                and candidate.source_platform != candidate.target_platform
                and candidate.provenance not in (Provenance.EXACT_RULE, Provenance.TYPED_RENDERER)):
            if source_line and _normalize_for_compare(line) == _normalize_for_compare(source_line):
                return ClassifiedLine(
                    target=DeployableDecision.UNSUPPORTED,
                    line=line, source_line=source_line,
                    reason="Cross-vendor verbatim: source line returned unchanged",
                    risk_level="high",
                    provenance=candidate.provenance,
                    confidence=candidate.confidence,
                )
            # Also check if target line still looks like source syntax
            if _looks_like_source_command(line, candidate.source_platform):
                return ClassifiedLine(
                    target=DeployableDecision.MANUAL_REVIEW,
                    line=line, source_line=source_line,
                    reason="Cross-vendor: line still appears to be source-vendor syntax",
                    risk_level="high",
                    provenance=candidate.provenance,
                    confidence=candidate.confidence,
                )

        # ── All checks passed → DEPLOYABLE ──
        return ClassifiedLine(
            target=DeployableDecision.DEPLOYABLE,
            line=line,
            source_line=source_line,
            reason="All policy checks passed",
            risk_level="low",
            provenance=candidate.provenance,
            confidence=candidate.confidence,
        )


def _normalize_for_compare(line: str) -> str:
    """Normalize a line for verbatim comparison. Collapse whitespace, lowercase."""
    return " ".join(line.strip().split()).lower()


def assess_unmatched_line(line: str, source_platform: str, target_platform: str) -> tuple[Provenance, Confidence]:
    """Assess an unmatched same-vendor line before conservative passthrough.

    Candidate factories and DeployablePolicy remain the primary path. This
    function handles only lines that no deterministic candidate matched.

    Checks common patterns that indicate a line is likely a valid target-vendor
    translation (not source residue, not verbatim copy).

    Returns (provenance, confidence) — if confidence is EXACT or HIGH and
    provenance is NORMALIZED_EQUIVALENT, the line passes DeployablePolicy.
    """
    lower = line.strip().lower()
    if not lower:
        return Provenance.RAW_STRING, Confidence.NONE

    # Source residue check
    if _is_source_residue(line, source_platform, target_platform):
        return Provenance.RAW_STRING, Confidence.NONE

    # Forbidden markers
    if _contains_forbidden_marker(line):
        return Provenance.RAW_STRING, Confidence.NONE

    # Verbatim check
    if source_platform and target_platform and source_platform != target_platform:
        if _looks_like_source_command(line, source_platform):
            return Provenance.RAW_STRING, Confidence.NONE

    # High-risk
    if _is_high_risk(line):
        return Provenance.RAW_STRING, Confidence.NONE

    # Secret
    if _is_secret_line(line):
        return Provenance.RAW_STRING, Confidence.NONE

    # Default-any
    if _is_default_any_risk(line):
        return Provenance.RAW_STRING, Confidence.NONE

    # Known-safe patterns (target-vendor syntax indicators)
    safe_patterns = [
        # VLAN
        r"^vlan\s+\d+", r"^vlan\s+batch\s+[\d\s]+",
        # Interface
        r"^interface\s+\S+", r"^interface\s+vlan\S+",
        # IP addressing
        r"^ip\s+address\s+\S+\s+\S+",
        # Static route
        r"^ip\s+route\s+\S+", r"^ip\s+route-static\s+\S+",
        # Hostname
        r"^hostname\s+\S+", r"^sysname\s+\S+",
        # Description
        r"^description\s+",
        # STP edge
        r"^stp\s+edged-port", r"^spanning-tree\s+portfast",
        # Port config
        r"^port\s+link-type\s+\S+", r"^switchport\s+mode\s+\S+",
        r"^port\s+trunk\s+(?:permit|allow-pass|pvid|native)\s+",
        r"^switchport\s+trunk\s+",
        r"^switchport\s+access\s+vlan\s+\d+",
        r"^port\s+default\s+vlan\s+\d+",
        # Undo/no shutdown
        r"^undo\s+shutdown", r"^no\s+shutdown",
        # Zone / security
        r"^zone\s+\S+", r"^security-zone\s+name\s+\S+",
        # Address set
        r"^address\s+\S+", r"^ip\s+address-set\s+\S+",
        # Service
        r"^service\s+\S+\s+(?:tcp|udp)", r"^ip\s+service-set\s+\S+",
        # OSPF header
        r"^ospf\s+\d+", r"^router\s+ospf\s+\d+",
        # BGP header (safe — only sub-commands are high-risk)
        r"^bgp\s+\d+", r"^router\s+bgp\s+\d+",
        # NTP (non-sensitive)
        r"^ntp\s+server\s+\S+", r"^ntp-service\s+unicast-server\s+\S+",
        r"^ntp\s+source\b", r"^ntp-service\s+source\b",
        # Zone (safe)
        r"^zone\s+\S+$", r"^security-zone\s+name\s+\S+$",
        # ACL binding (safe — interface context)
        r"^ip\s+access-group\b", r"^traffic-filter\b", r"^packet-filter\b",
        # SNMP (non-sensitive header)
        r"^snmp-server\s+\S+", r"^snmp-agent\s+\S+",
        # Logging (safe)
        r"^logging\s+\S+", r"^info-center\s+\S+",
        # OSPF passive-interface (safe sub-command)
        r"^passive-interface\b", r"^silent-interface\b",
        # Interface sub-command passthrough
        r"^ip\s+address\s+\S+\s+\S+",
    ]
    # NOTE: BGP neighbor/network/policy, OSPF network, trunk native/pvid,
    # ACL rules, and route-policy are NOT in the safe pattern list.
    # They are handled by typed renderer (conservative) or DeployablePolicy.
    for pat in safe_patterns:
        if re.match(pat, lower):
            return Provenance.NORMALIZED_EQUIVALENT, Confidence.HIGH

    # Default: line doesn't match any known-safe pattern
    return Provenance.RAW_STRING, Confidence.NONE
