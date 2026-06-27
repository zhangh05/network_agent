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
            "grounding": {
                "verified_count": 0,
                "unverified_count": 0,
                "checks": [],
            },
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

            grounding = _verify_item_grounding(item, ctx)
            if grounding:
                item.metadata["grounding_status"] = grounding["status"]
                item.metadata["grounding_reason"] = grounding.get("reason", "")
                report["grounding"]["checks"].append(grounding)
                if grounding["status"] == "verified":
                    report["grounding"]["verified_count"] += 1
                elif grounding["status"] == "unverified":
                    report["grounding"]["unverified_count"] += 1
                    if item.trust_level not in ("excluded", "untrusted"):
                        item.trust_level = "low"

            if item.trust_level != original:
                report["adjustments"].append({
                    "item_id": item.evidence_id,
                    "source_type": "knowledge",
                    "from": original,
                    "to": item.trust_level,
                })

        return report


def _verify_item_grounding(item: EvidenceItem, ctx: Any = None) -> dict[str, Any] | None:
    """Verify lightweight grounding for evidence that references local storage."""
    ws_id = getattr(ctx, "workspace_id", "") if ctx is not None else ""
    source_id = str(getattr(item, "source_id", "") or "")
    metadata = getattr(item, "metadata", {}) or {}
    file_id = (
        metadata.get("file_id")
        or metadata.get("source_file_id")
        or metadata.get("normalized_file_id")
        or (source_id if source_id.startswith("file_") else "")
    )
    if not file_id:
        return None
    base = {
        "item_id": item.evidence_id,
        "source_type": item.source_type,
        "ref_type": "file_id",
        "ref": file_id,
    }
    if not ws_id:
        return {**base, "status": "unverified", "reason": "workspace_id_missing"}
    try:
        from storage.file_store import get_file_record, resolve_file_path
        rec = get_file_record(ws_id, file_id)
        if not rec:
            return {**base, "status": "unverified", "reason": "file_record_missing"}
        resolve_file_path(ws_id, file_id)
        return {**base, "status": "verified", "reason": "file_exists"}
    except Exception as exc:
        return {**base, "status": "unverified", "reason": str(exc)[:160]}
