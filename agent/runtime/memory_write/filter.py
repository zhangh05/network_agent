# agent/runtime/memory_write/filter.py
"""MemoryRiskFilter — filters sensitive or low-value memory candidates."""

from __future__ import annotations

import re

from agent.runtime.memory_write.models import MemoryCandidate


_SENSITIVE_PATTERNS = [
    (re.compile(r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)", re.IGNORECASE), "credential_pattern"),
    (re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"), "long_secret_pattern"),
    (re.compile(r"(sk-|pk-|ghp_|gho_|Bearer\s)[A-Za-z0-9_-]{20,}", re.IGNORECASE), "api_key_pattern"),
]


class MemoryRiskFilter:
    """Filter out sensitive or risky memory candidates."""

    def filter(self, candidates: list[MemoryCandidate]) -> tuple[list[MemoryCandidate], list[dict]]:
        accepted: list[MemoryCandidate] = []
        skipped: list[dict] = []
        for c in candidates:
            reason = self._check_risk(c)
            if reason:
                c.risk_level = "high"
                skipped.append({
                    "candidate_id": c.candidate_id,
                    "reason": reason,
                    "memory_type": c.memory_type,
                })
            else:
                accepted.append(c)
        return accepted, skipped

    @staticmethod
    def _check_risk(candidate: MemoryCandidate) -> str:
        content = candidate.content or ""
        for pat, label in _SENSITIVE_PATTERNS:
            if pat.search(content):
                return f"sensitive_match: {label}"
        return ""
