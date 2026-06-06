# -*- coding: utf-8 -*-
"""Unified Translation Data Model.

Replaces scattered dict/string-based translation output with a single
typed data model consumed by DeployablePolicy and all output paths.

Design:
    translator → list[TranslationCandidate]
    DeployablePolicy.classify(candidate) → ClassifiedTranslation
    TranslationBundle.assemble(candidates, classified) → bundle

All deployable_config writes MUST go through TranslationBundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ──────────────────────────────────────────────────────────────────

class TranslationTarget(str, Enum):
    DEPLOYABLE = "deployable"
    MANUAL_REVIEW = "manual_review"
    SEMANTIC_NEAR = "semantic_near"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class Provenance(str, Enum):
    EXACT_RULE = "exact_rule"
    TYPED_RENDERER = "typed_renderer"
    NORMALIZED_EQUIVALENT = "normalized_equivalent"
    LEGACY_STRING = "legacy_string"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Origin(str, Enum):
    RAW_FALLBACK = "raw_fallback"
    H3C_TO_CISCO = "h3c_to_cisco"
    MODULE_GRAPH = "module_graph"
    GRAPH_FALLBACK = "graph_fallback"
    RENDERER = "renderer"
    SAME_VENDOR = "same_vendor"


# ── TranslationCandidate ───────────────────────────────────────────────────

@dataclass
class TranslationCandidate:
    """A single candidate line produced by a translator, before classification."""

    source_line: str                              # original source config line
    candidate_line: str                           # translated/suggested line
    source_platform: str = ""                     # e.g. "cisco_ios_xe"
    target_platform: str = ""                     # e.g. "huawei_vrp"
    from_vendor: str = ""                         # source vendor name
    to_vendor: str = ""                           # target vendor name
    domain: str = ""                              # SWITCH / ROUTER / FIREWALL
    module: str = ""                              # feature module (vlan, ospf, etc.)
    provenance: Provenance = Provenance.LEGACY_STRING
    confidence: Confidence = Confidence.NONE
    risk_tags: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    origin: Origin = Origin.RAW_FALLBACK

    @property
    def is_cross_vendor(self) -> bool:
        return bool(self.source_platform and self.target_platform
                    and self.source_platform != self.target_platform)


# ── ClassifiedTranslation ──────────────────────────────────────────────────

@dataclass
class ClassifiedTranslation:
    """Policy-classified translation — determines which output layer."""

    target: TranslationTarget
    line: str                                     # the output line (may be redacted)
    source_line: str = ""                         # original source line for audit
    reason: str = ""                              # classification reason
    risk_level: str = "medium"                    # critical / high / medium / low
    provenance: Provenance = Provenance.LEGACY_STRING
    confidence: Confidence = Confidence.NONE
    module: str = ""
    origin: Origin = Origin.RAW_FALLBACK
    confirmation_points: List[str] = field(default_factory=list)
    redaction_applied: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_deployable(self) -> bool:
        return self.target == TranslationTarget.DEPLOYABLE

    def to_review_item(self) -> dict:
        """Convert to structured review item for evaluator compatibility.

        Uses redacted source_line as source_excerpt. Falls back to line
        only if source_line is empty AND evidence.source_line_unknown is set.
        """
        excerpt = self.source_line or ""
        if not excerpt and self.evidence.get("source_line_unknown"):
            excerpt = self.line

        return {
            "source_excerpt": excerpt,
            "reason": self.reason,
            "category": self.target.value,
            "risk_level": self.risk_level,
            "suggested_action": "Manually review and confirm before deployment",
            "confirmation_points": self.confirmation_points or ["Verify semantic equivalence"],
            "redaction_applied": self.redaction_applied,
            "_raw_line": f"# MANUAL_REVIEW {self.line}" if not self.line.startswith("# MANUAL_REVIEW") else self.line,
        }


# ── TranslationBundle ─────────────────────────────────────────────────────

@dataclass
class TranslationBundle:
    """Complete translation output bundle — the single source of truth."""

    candidates: List[TranslationCandidate] = field(default_factory=list)
    classified: List[ClassifiedTranslation] = field(default_factory=list)
    _source_text: str = ""
    coverage_audit: Dict[str, Any] = field(default_factory=dict)

    # ── Computed properties ──

    @property
    def deployable_config(self) -> str:
        return "\n".join(
            c.line for c in self.classified if c.is_deployable
        ).strip()

    @property
    def deployable_lines(self) -> List[str]:
        return [c.line for c in self.classified if c.is_deployable]

    @property
    def manual_review_items(self) -> List[dict]:
        return [c.to_review_item() for c in self.classified
                if c.target == TranslationTarget.MANUAL_REVIEW]

    @property
    def unsupported_items(self) -> List[dict]:
        return [c.to_review_item() for c in self.classified
                if c.target == TranslationTarget.UNSUPPORTED]

    @property
    def semantic_near_items(self) -> List[dict]:
        return [c.to_review_item() for c in self.classified
                if c.target == TranslationTarget.SEMANTIC_NEAR]

    @property
    def unknown_items(self) -> List[dict]:
        return [c.to_review_item() for c in self.classified
                if c.target == TranslationTarget.UNKNOWN]

    @property
    def full_output(self) -> str:
        """Backward-compatible full output with deployable + review markers."""
        parts = [self.deployable_config]
        for item in self.manual_review_items:
            parts.append(f"# MANUAL_REVIEW {item.get('source_excerpt', item.get('candidate_line', ''))}")
        for item in self.unsupported_items:
            parts.append(f"# MANUAL_REVIEW unsupported source command: {item.get('source_excerpt', '')}")
        for item in self.semantic_near_items:
            candidate = item.get('candidate_line', item.get('suggested_line', ''))
            source = item.get('source_excerpt', item.get('source_line', ''))
            parts.append(f"# SEMANTIC_NEAR source: {source}  // suggested: {candidate}")
        return "\n".join(p for p in parts if p)

    @property
    def wrapped_full_output(self) -> str:
        """Full output with markdown code fences (old format compatibility)."""
        body = self.full_output
        if not body.strip():
            return ""
        vendor = "unknown"
        for c in self.classified:
            if c.origin and hasattr(c.origin, 'value'):
                vendor = c.origin.value
                break
        return f"```{vendor}\n{body.strip()}\n```"

    # ── Legacy compatibility ──

    @property
    def audit(self) -> Dict[str, Any]:
        """DEPRECATED: use coverage_audit instead. Kept for backward compat."""
        ca = self.coverage_audit or {}
        legacy_count = sum(1 for c in self.candidates
                           if c.provenance in (Provenance.LEGACY_STRING, Provenance.UNKNOWN))
        return {
            "total_candidates": ca.get("candidate_count", len(self.candidates)),
            "total_classified": ca.get("classified_count", len(self.classified)),
            "deployable_count": ca.get("deployable_count", 0),
            "manual_review_count": ca.get("review_count", len(self.manual_review_items)),
            "unsupported_count": ca.get("unsupported_count", len(self.unsupported_items)),
            "semantic_near_count": ca.get("semantic_near_count", len(self.semantic_near_items)),
            "unknown_count": ca.get("unknown_count", len(self.unknown_items)),
            "exact_candidate_count": ca.get("exact_count", 0),
            "review_candidate_count": 0,
            "legacy_candidate_count": legacy_count,
        }

    def to_sections(self) -> Dict[str, Any]:
        """Return dict compatible with old translate_separated() format."""
        items = {"manual_review": [], "unsupported": []}
        for citem in self.manual_review_items:
            items["manual_review"].append(citem)
        for citem in self.unsupported_items:
            items["unsupported"].append(citem)
        return {
            "deployable_config": self.deployable_config,
            "manual_review_items": items["manual_review"],
            "unsupported_items": items["unsupported"],
            "semantic_near_items": self.semantic_near_items,
            "full_output": self.wrapped_full_output,
            "audit": self.audit,
        }

    @classmethod
    def from_classified(cls, classified: List[ClassifiedTranslation],
                        candidates: Optional[List[TranslationCandidate]] = None,
                        source_text: str = "") -> "TranslationBundle":
        """Create bundle from classified results."""
        return cls(
            candidates=candidates or [],
            classified=classified,
            _source_text=source_text,
        )
