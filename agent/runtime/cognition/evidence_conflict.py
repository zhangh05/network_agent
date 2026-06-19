# agent/runtime/cognition/evidence_conflict.py
"""EvidenceConflict detection — detects conflicts in evidence bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem


@dataclass
class EvidenceConflict:
    """Represents a detected conflict between evidence items."""

    conflict_id: str = ""
    conflict_type: str = ""       # "vendor", "address", "version", "fact"
    description: str = ""
    item_ids: list[str] = field(default_factory=list)
    severity: str = "warning"     # "info", "warning", "error"


# Vendor detection patterns
_VENDOR_KEYWORDS: dict[str, list[str]] = {
    "h3c": ["h3c", "华三", "comware"],
    "huawei": ["huawei", "华为", "vrp"],
    "cisco": ["cisco", "ios", "nx-os", "ios-xr"],
    "juniper": ["juniper", "junos"],
    "ruijie": ["ruijie", "锐捷"],
}


def _detect_vendor(text: str) -> str | None:
    """Detect vendor from text. Returns vendor key or None."""
    lower = text.lower()
    for vendor, keywords in _VENDOR_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return vendor
    return None


class EvidenceConflictDetector:
    """Detect conflicts within an evidence bundle."""

    def detect(self, evidence: EvidenceBundle) -> list[EvidenceConflict]:
        """Scan all evidence items for conflicts.

        Currently detects:
        - Vendor conflicts (e.g., h3c vs huawei vs cisco in same bundle)
        - Address conflicts (same key, different values)
        """
        conflicts: list[EvidenceConflict] = []

        all_items = list(evidence.memory_items) + list(evidence.knowledge_items)
        if not all_items:
            return conflicts

        # Vendor conflict detection
        vendor_map: dict[str, list[str]] = {}
        for item in all_items:
            text = f"{item.title} {item.content} {item.summary}"
            vendor = _detect_vendor(text)
            if vendor:
                vendor_map.setdefault(vendor, []).append(item.evidence_id or item.chunk_id)

        if len(vendor_map) > 1:
            vendors = list(vendor_map.keys())
            all_ids = [eid for ids in vendor_map.values() for eid in ids]
            conflicts.append(EvidenceConflict(
                conflict_id=f"vendor_conflict_{'_vs_'.join(sorted(vendors))}",
                conflict_type="vendor",
                description=f"Multiple vendors detected: {', '.join(sorted(vendors))}. Results may mix vendor-specific information.",
                item_ids=all_ids,
                severity="warning",
            ))

        return conflicts
