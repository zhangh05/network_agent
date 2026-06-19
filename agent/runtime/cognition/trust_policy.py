# agent/runtime/cognition/trust_policy.py
"""TrustPolicy — assigns trust levels to evidence items and layers."""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem


# Trust level hierarchy (highest → lowest)
TRUST_LEVELS = {
    "highest": 5,   # user_input
    "high": 4,      # artifact, workspace_state
    "medium": 3,    # knowledge, confirmed_memory
    "low": 2,       # unconfirmed_memory
    "untrusted": 1, # default
    "excluded": 0,  # blocked
}


class TrustPolicy:
    """Apply trust levels to evidence items based on source and status."""

    def apply(self, evidence: EvidenceBundle, ctx: Any = None) -> dict[str, Any]:
        """Apply trust policy to all items in the bundle.

        Rules:
        - user_input = highest
        - artifact = high
        - knowledge = medium
        - confirmed_memory = medium
        - unconfirmed_memory = low
        - blocked = excluded

        Returns a trust report dict.
        """
        report: dict[str, Any] = {
            "applied": True,
            "adjustments": [],
        }

        for item in evidence.memory_items:
            original = item.trust_level
            if item.scan_status == "blocked":
                item.trust_level = "excluded"
            elif hasattr(item, "metadata") and item.metadata.get("confirmation_status") == "confirmed":
                item.trust_level = "medium"
            elif item.metadata.get("confirmation_status") == "unconfirmed":
                item.trust_level = "low"
            else:
                item.trust_level = "low"

            if item.trust_level != original:
                report["adjustments"].append({
                    "item_id": item.evidence_id,
                    "source_type": "memory",
                    "from": original,
                    "to": item.trust_level,
                })

        for item in evidence.knowledge_items:
            original = item.trust_level
            if item.scan_status == "blocked":
                item.trust_level = "excluded"
            else:
                item.trust_level = "medium"

            if item.trust_level != original:
                report["adjustments"].append({
                    "item_id": item.evidence_id,
                    "source_type": "knowledge",
                    "from": original,
                    "to": item.trust_level,
                })

        return report
