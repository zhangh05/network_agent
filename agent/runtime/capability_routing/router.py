# agent/runtime/capability_routing/router.py
"""Capability-first router."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from .manifests import CAPABILITY_PACKAGES
from .models import CapabilityPackage

ROUTER_VERSION = "capability_router.v2"


@dataclass(frozen=True)
class CapabilityRoute:
    packages: tuple[CapabilityPackage, ...]
    reasons: dict[str, str]
    confidence: dict[str, float]
    candidate_scores: dict[str, float]
    signals: tuple[str, ...] = ()
    ambiguous: bool = False
    fallback_used: bool = False
    latency_ms: float = 0.0
    route_version: str = ROUTER_VERSION

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(pkg.capability_id for pkg in self.packages)

    @property
    def module_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for pkg in self.packages:
            for module_id in pkg.module_ids:
                if module_id not in seen:
                    seen.add(module_id)
                    out.append(module_id)
        return tuple(out)

    def to_dict(self) -> dict:
        return {
            "route_version": self.route_version,
            "capability_ids": list(self.capability_ids),
            "module_ids": list(self.module_ids),
            "reasons": dict(self.reasons),
            "confidence": dict(self.confidence),
            "candidate_scores": dict(self.candidate_scores),
            "signals": list(self.signals),
            "ambiguous": self.ambiguous,
            "fallback_used": self.fallback_used,
            "latency_ms": round(max(0.0, self.latency_ms), 3),
        }


class CapabilityRouter:
    def __init__(self, packages: tuple[CapabilityPackage, ...] = CAPABILITY_PACKAGES):
        self._packages = packages

    def route(self, user_input: str, *, scene: Any = None, safe_context: dict | None = None, limit: int = 3) -> CapabilityRoute:
        started = time.perf_counter()
        safe_context = safe_context or {}
        text = " ".join(
            str(x or "")
            for x in [
                user_input,
                getattr(scene, "category", ""),
                getattr(scene, "reason", ""),
            ]
        ).lower()
        signals: list[str] = []
        scored: list[tuple[float, CapabilityPackage, str, float]] = []
        for package in self._packages:
            matches = [
                kw for kw in package.intent_keywords
                if _keyword_matches(text, kw)
            ]
            score = sum(_keyword_weight(kw) for kw in matches)
            context_score, context_reasons = _context_score(
                package.capability_id,
                scene=scene,
                safe_context=safe_context,
            )
            score += context_score
            matches.extend(context_reasons)
            for reason in context_reasons:
                if reason not in signals:
                    signals.append(reason)
            if score > 0:
                scored.append((
                    score,
                    package,
                    ",".join(matches[:6]),
                    min(1.0, score / 8.0),
                ))
        scored.sort(key=lambda item: (-item[0], item[1].priority, item[1].capability_id))
        selected = scored[: max(1, limit)]
        fallback_used = False
        if not selected:
            default = next((p for p in self._packages if p.capability_id == "workspace_read"), self._packages[0])
            selected = [(1.0, default, "safe_default", 0.125)]
            fallback_used = True
            signals.append("fallback:safe_default")
        top_score = selected[0][0]
        second_score = selected[1][0] if len(selected) > 1 else 0.0
        ambiguous = bool(
            fallback_used
            or top_score < 3.0
            or (second_score > 0 and top_score - second_score < 1.0)
        )
        packages = tuple(item[1] for item in selected)
        return CapabilityRoute(
            packages=packages,
            reasons={item[1].capability_id: item[2] for item in selected},
            confidence={item[1].capability_id: item[3] for item in selected},
            candidate_scores={item[1].capability_id: item[0] for item in scored},
            signals=tuple(signals),
            ambiguous=ambiguous,
            fallback_used=fallback_used,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def route_capabilities(user_input: str, *, scene: Any = None, safe_context: dict | None = None, limit: int = 3) -> CapabilityRoute:
    return CapabilityRouter().route(user_input, scene=scene, safe_context=safe_context, limit=limit)


def _keyword_matches(text: str, keyword: str) -> bool:
    needle = str(keyword or "").strip().lower()
    if not needle:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in needle):
        return needle in text
    # ASCII keyword: use CJK-aware word boundary.
    # \w matches CJK chars in Python 3, so (?<!\w) would reject
    # keywords adjacent to Chinese text (e.g. "pcap" in "分析这个pcap文件").
    # Treat CJK chars as natural word delimiters.
    cjk_range = r"\u4e00-\u9fff"
    return re.search(
        rf"(?:^|[{cjk_range}\W]){re.escape(needle)}(?:[{cjk_range}\W]|$)",
        text,
    ) is not None


def _keyword_weight(keyword: str) -> float:
    value = str(keyword or "").strip()
    if " " in value or len(value) >= 6:
        return 3.0
    return 2.0


def _context_score(
    capability_id: str,
    *,
    scene: Any,
    safe_context: dict,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    def add(value: float, reason: str) -> None:
        nonlocal score
        score += value
        reasons.append(reason)

    if capability_id == "workspace_read":
        if safe_context.get("artifact_refs") or safe_context.get("file_refs"):
            add(6.0, "context:artifact_refs")
        elif safe_context.get("uploaded_files"):
            add(5.0, "context:uploaded_files")
        if getattr(scene, "is_file_task", False):
            add(3.0, "scene:file")
    elif capability_id == "knowledge_qa":
        if safe_context.get("knowledge_hits"):
            add(5.0, "context:knowledge_hits")
        if getattr(scene, "needs_knowledge", False) or getattr(scene, "is_knowledge_task", False):
            add(5.0, "scene:knowledge")
        elif getattr(scene, "is_factual_query", False):
            add(3.0, "scene:factual")
    elif capability_id == "memory_lookup":
        if safe_context.get("memory_hits"):
            add(5.0, "context:memory_hits")
        if getattr(scene, "needs_memory", False) or getattr(scene, "is_memory_task", False):
            add(6.0, "scene:memory")
    elif capability_id == "pcap_analysis":
        if safe_context.get("pcap_session_id") or safe_context.get("packet_refs"):
            add(6.0, "context:pcap")
    elif capability_id == "config_translation":
        if safe_context.get("source_config_artifact_id"):
            add(6.0, "context:source_config")
    return score, reasons
