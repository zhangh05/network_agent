# modules/config_translation/core/quality.py
"""Quality accounting for config translation — residue detection, silent-drop tracking,
safe-drop classification, and quality summary generation.

This module provides:
  - QualityAuditor: tracks all source lines and their disposition
  - Source residue detection across vendor boundaries
  - Silent-drop detection (meaningful lines without any output layer assignment)
  - Safe-drop classification (blank lines, comments, display-only markers)
  - QualitySummary generation with actionable metrics
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Safe-drop whitelist patterns ──
# Lines matching these are safely ignorable (no semantic content)
_SAFE_DROP_PATTERNS = [
    (re.compile(r'^\s*$'), "empty_line"),                    # blank
    (re.compile(r'^\s*[!#]\s*'), "comment"),                 # comment (! or #)
    (re.compile(r'^\s*end\s*$', re.IGNORECASE), "block_end_marker"),
    (re.compile(r'^\s*exit\s*$', re.IGNORECASE), "exit_command"),
    (re.compile(r'^\s*banner\s+', re.IGNORECASE), "banner"),
    (re.compile(r'^ntp\s+clock-period\s+', re.IGNORECASE), "ntp_clock_period"),
    (re.compile(r'^\s*logging\s+console\s+', re.IGNORECASE), "logging_console_level"),
    (re.compile(r'^\s*logging\s+monitor\s+', re.IGNORECASE), "logging_monitor_level"),
]

# ── Security-sensitive line patterns (must NEVER be silent-dropped) ──
_SECURITY_SENSITIVE_PATTERNS = [
    (re.compile(r'\baccess-list\b', re.IGNORECASE), "acl"),
    (re.compile(r'\b(?:ip\s+)?nat\s+', re.IGNORECASE), "nat"),
    (re.compile(r'\broute-policy\b', re.IGNORECASE), "route_policy"),
    (re.compile(r'\broute-map\b', re.IGNORECASE), "route_map"),
    (re.compile(r'\bip\s+route\b', re.IGNORECASE), "static_route"),
    (re.compile(r'\broute-static\b', re.IGNORECASE), "static_route_hw"),
    (re.compile(r'\bshutdown\b', re.IGNORECASE), "shutdown"),
    (re.compile(r'\bno\s+shutdown\b', re.IGNORECASE), "no_shutdown"),
    (re.compile(r'\bsnmp-server\s+community\b', re.IGNORECASE), "snmp_community"),
    (re.compile(r'\bcommunity\s+', re.IGNORECASE), "community"),
    (re.compile(r'\bipsec\b', re.IGNORECASE), "ipsec"),
    (re.compile(r'\bcrypto\s+map\b', re.IGNORECASE), "crypto_map"),
    (re.compile(r'\baaa\s+', re.IGNORECASE), "aaa"),
    (re.compile(r'\bradius\b', re.IGNORECASE), "radius"),
    (re.compile(r'\btacacs', re.IGNORECASE), "tacacs"),
    (re.compile(r'\bauthentication\b', re.IGNORECASE), "authentication"),
    (re.compile(r'\bsecurity-policy\b', re.IGNORECASE), "security_policy"),
    (re.compile(r'\bqos\b', re.IGNORECASE), "qos"),
    (re.compile(r'\bvrrp\b', re.IGNORECASE), "vrrp"),
    (re.compile(r'\bhsrp\b', re.IGNORECASE), "hsrp"),
    (re.compile(r'\bswitchport\s+mode\s+trunk\b', re.IGNORECASE), "trunk"),
    (re.compile(r'\bvlan\b', re.IGNORECASE), "vlan"),
    (re.compile(r'\binterface\s+\S', re.IGNORECASE), "interface_def"),
    (re.compile(r'\bip\s+address\b', re.IGNORECASE), "ip_address"),
]

# ── Source residue vendor patterns ──
# Keywords that should NOT appear in target output when crossing vendor families

_VENDOR_RESIDUE_PATTERNS = {
    # Cisco/ASA-specific tokens that must not appear in Comware-family output
    "cisco_in_comware": [
        "gigabitethernet", "fastethernet", "tengigabitethernet",
        "switchport", "hostname ", "spanning-tree", "standby ",
        "channel-group", "access-group", "nameif", "security-level",
        "snmp-server", "router ospf", "router bgp", "router eigrp",
        "crypto isakmp", "crypto ipsec", "ip http server",
        "line vty", "line con", "enable secret", "enable password",
        "banner motd", "banner login",
        "interface gigabitethernet", "interface fastethernet",
        "interface tengigabitethernet",
        "ip access-list", "ip helper-address",
        "ip subnet-zero", "classless",
    ],
    # Comware-family tokens that must not appear in Cisco-family output
    "comware_in_cisco": [
        "sysname", "vlan batch", "undo ", "port link-type",
        "port trunk", "port default vlan", "port access vlan",
        "eth-trunk", "bridge-aggregation", "ip route-static",
        "ospf ", "bgp ", "irf ", "local-user", "domain ",
        "authorization-attribute", "authentication-mode",
        "port link-aggregation", "mad ", "stack",
        "info-center", "display ", "reset ", "network-entity",
        "user-interface", "super password", "user-group",
        "security-zone", "ip ip-prefix", "http server enable",
        "ftp server enable", "telnet server enable",
    ],
}


@dataclass
class QualitySummary:
    """Aggregated quality metrics for a single translation."""

    source_residue_count: int = 0
    silent_drop_count: int = 0
    unsupported_count: int = 0
    safe_drop_count: int = 0
    review_required_count: int = 0
    deployable_count: int = 0
    semantic_near_count: int = 0
    total_source_lines: int = 0
    meaningful_source_lines: int = 0

    source_residue_items: list = field(default_factory=list)
    silent_drop_items: list = field(default_factory=list)
    safe_dropped_lines: list = field(default_factory=list)
    unconverted_items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_residue_count": self.source_residue_count,
            "silent_drop_count": self.silent_drop_count,
            "unsupported_count": self.unsupported_count,
            "safe_drop_count": self.safe_drop_count,
            "review_required_count": self.review_required_count,
            "deployable_count": self.deployable_count,
            "semantic_near_count": self.semantic_near_count,
            "total_source_lines": self.total_source_lines,
            "meaningful_source_lines": self.meaningful_source_lines,
            "source_residue_items": self.source_residue_items[:20],
            "silent_drop_items": self.silent_drop_items[:20],
            "safe_dropped_lines": self.safe_dropped_lines[:20],
            "unconverted_items": self.unconverted_items[:20],
            "warnings": self.warnings[:20],
        }


class QualityAuditor:
    """Audits translation quality: residue detection, silent-drop tracking,
    and coverage accounting for all meaningful source lines."""

    def __init__(self, source_config: str, source_vendor: str, target_vendor: str):
        self.source_config = source_config.strip()
        self.source_vendor = source_vendor.lower()
        self.target_vendor = target_vendor.lower()
        self._source_lines = [l for l in source_config.split("\n")]
        self._accounted: set = set()  # line numbers that are accounted for
        self._safe_drops: list = []
        self._residue_items: list = []
        self._silent_drops: list = []
        self._warnings: list = []

    def classify_source_line(self, line_num: int, line: str) -> str:
        """Classify a single source line for coverage accounting.

        Returns: "safe_drop" | "meaningful" | "security_sensitive"
        """
        stripped = line.strip()
        if not stripped:
            return "safe_drop"
        # Comments
        if stripped.startswith("!") or stripped.startswith("#"):
            return "safe_drop"
        # Safe-drop patterns
        for pattern, label in _SAFE_DROP_PATTERNS:
            if pattern.match(stripped):
                self._safe_drops.append({
                    "line_num": line_num + 1,
                    "line": stripped[:100],
                    "reason": label,
                })
                return "safe_drop"
        # Security check
        for pattern, label in _SECURITY_SENSITIVE_PATTERNS:
            if pattern.search(stripped):
                return "security_sensitive"
        return "meaningful"

    def account_line(self, line_num: int) -> None:
        """Mark a source line as accounted for (appears in some output layer)."""
        self._accounted.add(line_num)

    def check_source_residue(self, deployable_text: str) -> list:
        """Check deployable output for source vendor residue.

        Returns list of residue items found.
        """
        items = []
        is_cisco = self.source_vendor in ("cisco", "ios", "ruijie")
        is_comware = self.source_vendor in ("huawei", "h3c", "comware")

        # Determine which patterns to check
        patterns_to_check = []
        if is_cisco and not self.target_vendor in ("cisco", "ios", "ruijie"):
            # Source is Cisco, target is Comware-family → check for Cisco residue
            for kw in _VENDOR_RESIDUE_PATTERNS["cisco_in_comware"]:
                if kw in deployable_text.lower():
                    items.append({
                        "residue_type": "cisco_in_comware",
                        "keyword": kw,
                        "severity": "high" if any(s in kw for s in ["secret",
                            "password", "community", "snmp"]) else "medium",
                    })
        elif is_comware and self.target_vendor in ("cisco", "ios", "ruijie"):
            # Source is Comware, target is Cisco → check for Comware residue
            for kw in _VENDOR_RESIDUE_PATTERNS["comware_in_cisco"]:
                if kw in deployable_text.lower():
                    items.append({
                        "residue_type": "comware_in_cisco",
                        "keyword": kw,
                        "severity": "high",
                    })

        # Also check for interface name format residue
        if is_cisco and self.target_vendor in ("huawei", "h3c"):
            cisco_iface = re.findall(r'(?:GigabitEthernet|FastEthernet|TenGigabitEthernet)\S*',
                                     deployable_text, re.IGNORECASE)
            for iface in cisco_iface:
                items.append({
                    "residue_type": "cisco_interface_name",
                    "keyword": iface,
                    "severity": "high",
                })

        self._residue_items = items
        return items

    def find_silent_drops(self, accounted_in_output: dict) -> list:
        """Find source lines that were silently dropped (meaningful, unaccounted).

        Args:
            accounted_in_output: dict mapping line_num → where it appeared
                values: "deployable", "manual_review", "unsupported", "semantic_near"
        """
        drops = []
        for i, line in enumerate(self._source_lines):
            stripped = line.strip()
            classification = self.classify_source_line(i, stripped)

            if classification == "safe_drop":
                continue  # safely ignorable

            # Check if accounted for (in any output layer)
            if i in accounted_in_output:
                continue
            if stripped in accounted_in_output:
                continue

            # Build a normalized representation for fuzzy matching
            norm = stripped.lower().replace(" ", "")
            found = False
            for key in accounted_in_output:
                if isinstance(key, str) and norm[:20] in key.lower().replace(" ", ""):
                    found = True
                    break
            if found:
                continue

            # This is a silent drop
            severity = "critical" if classification == "security_sensitive" else "high"
            drops.append({
                "line_num": i + 1,
                "line": stripped[:120],
                "severity": severity,
                "classification": classification,
            })

        self._silent_drops = drops
        return drops

    def build_quality_summary(
        self,
        deployable_count: int,
        manual_review_count: int,
        unsupported_count: int,
        semantic_near_count: int,
        accounted_in_output: dict,
    ) -> QualitySummary:
        """Build a complete quality summary after translation."""
        total = len(self._source_lines)

        # Count meaningful lines
        meaningful = 0
        for i, line in enumerate(self._source_lines):
            if self.classify_source_line(i, line.strip()) != "safe_drop":
                meaningful += 1

        # Find silent drops
        silent_drops = self.find_silent_drops(accounted_in_output)

        summary = QualitySummary(
            source_residue_count=len(self._residue_items),
            silent_drop_count=len(silent_drops),
            unsupported_count=unsupported_count,
            safe_drop_count=total - meaningful,
            review_required_count=manual_review_count,
            deployable_count=deployable_count,
            semantic_near_count=semantic_near_count,
            total_source_lines=total,
            meaningful_source_lines=meaningful,
            source_residue_items=self._residue_items,
            silent_drop_items=silent_drops,
            safe_dropped_lines=[d for d in self._safe_drops],
            unconverted_items=silent_drops,
            warnings=self._warnings,
        )

        return summary


def is_safe_drop(line: str) -> bool:
    """Check if a line is a safe drop (blank, comment, display-only)."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("!") or stripped.startswith("#"):
        return True
    for pattern, _ in _SAFE_DROP_PATTERNS:
        if pattern.match(stripped):
            return True
    return False
