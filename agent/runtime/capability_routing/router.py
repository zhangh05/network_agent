# agent/runtime/capability_routing/router.py
"""Capability-first router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifests import CAPABILITY_PACKAGES
from .models import CapabilityPackage


@dataclass(frozen=True)
class CapabilityRoute:
    packages: tuple[CapabilityPackage, ...]
    reasons: dict[str, str]
    confidence: dict[str, float]

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


class CapabilityRouter:
    def __init__(self, packages: tuple[CapabilityPackage, ...] = CAPABILITY_PACKAGES):
        self._packages = packages

    def route(self, user_input: str, *, scene: Any = None, safe_context: dict | None = None, limit: int = 3) -> CapabilityRoute:
        text = " ".join(str(x or "") for x in [user_input, getattr(scene, "category", ""), getattr(scene, "reason", "")]).lower()
        scored: list[tuple[int, CapabilityPackage, str, float]] = []
        for package in self._packages:
            matches = [kw for kw in package.intent_keywords if kw.lower() in text]
            score = len(matches) * 2
            if package.capability_id == "workspace_read" and (safe_context or {}).get("artifact_refs"):
                score += 2
                matches.append("artifact_refs")
            if package.capability_id == "knowledge_qa" and (safe_context or {}).get("knowledge_hits"):
                score += 2
                matches.append("knowledge_hits")
            if package.capability_id == "memory_lookup" and (safe_context or {}).get("memory_hits"):
                score += 2
                matches.append("memory_hits")
            if score > 0:
                scored.append((score, package, ",".join(matches[:5]), min(1.0, score / 5.0)))
        scored.sort(key=lambda item: (-item[0], item[1].priority, item[1].capability_id))
        selected = scored[: max(1, limit)]
        if not selected:
            default = next((p for p in self._packages if p.capability_id == "workspace_read"), self._packages[0])
            selected = [(1, default, "default", 0.2)]
        packages = tuple(item[1] for item in selected)
        return CapabilityRoute(
            packages=packages,
            reasons={item[1].capability_id: item[2] for item in selected},
            confidence={item[1].capability_id: item[3] for item in selected},
        )


def route_capabilities(user_input: str, *, scene: Any = None, safe_context: dict | None = None, limit: int = 3) -> CapabilityRoute:
    return CapabilityRouter().route(user_input, scene=scene, safe_context=safe_context, limit=limit)
