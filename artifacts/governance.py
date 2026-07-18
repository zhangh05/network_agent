"""Evidence lineage and authority projection for managed artifacts.

Artifact files are immutable observations. Authority is scoped by business
purpose before recency is considered. Only an explicit baseline capture may
establish current network-state authority; every other assurance task remains contextual evidence
and can never demote that state check to history.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from artifacts.schemas import ArtifactRecord


AUTHORITY_POLICY = "domain_scoped_latest_complete"
CURRENT_STATE_KINDS = {"baseline_capture"}


def _metadata(record: ArtifactRecord) -> dict[str, Any]:
    return record.metadata if isinstance(record.metadata, dict) else {}


def _authority_domain(record: ArtifactRecord) -> str:
    metadata = _metadata(record)
    if record.artifact_type == "inspection_raw":
        assurance_kind = str(metadata.get("assurance_kind", "") or "").strip()
        if assurance_kind in CURRENT_STATE_KINDS:
            return "current_state"
        if assurance_kind:
            return "contextual"
        explicit = str(metadata.get("authority_domain", "") or "").strip()
        if explicit in {"current_state", "inspection", "contextual"}:
            return explicit
        return "inspection"
    return "evidence"


def _evidence_key(record: ArtifactRecord) -> str:
    metadata = _metadata(record)
    if record.artifact_type == "inspection_raw":
        # Repair the read model for older records and separate business domains
        # before applying a latest-complete policy.
        asset_id = str(metadata.get("asset_id", "") or "").strip()
        profile_id = str(metadata.get("script_profile_id") or metadata.get("profile_id") or "general").strip()
        if asset_id:
            domain = _authority_domain(record)
            if domain == "contextual":
                kind = str(metadata.get("assurance_kind", "") or "task").strip()
                ref_id = str(metadata.get("assurance_ref_id", "") or metadata.get("producer_id", "") or record.artifact_id).strip()
                return f"contextual:{kind}:{ref_id}:{asset_id}:{profile_id}"
            return f"{domain}:{asset_id}:{profile_id}"
    key = str(metadata.get("evidence_key", "") or "").strip()
    return "" if key == "[REDACTED_SECRET]" else key


def _quality(record: ArtifactRecord) -> str:
    quality = str(_metadata(record).get("evidence_quality", "") or "").strip()
    return quality if quality in {"complete", "partial"} else "unknown"


def build_governance(records: Iterable[ArtifactRecord]) -> dict[str, dict[str, Any]]:
    """Return artifact_id -> governance projection for active records."""
    materialized = list(records)
    streams: dict[str, list[ArtifactRecord]] = defaultdict(list)
    result: dict[str, dict[str, Any]] = {}
    for record in materialized:
        key = _evidence_key(record)
        if not key:
            continue
        domain = _authority_domain(record)
        if domain == "contextual":
            result[record.artifact_id] = {
                "evidence_key": key,
                "evidence_role": str(_metadata(record).get("evidence_role") or "raw_observation"),
                "evidence_quality": _quality(record),
                "authority_domain": domain,
                "authority_status": "contextual",
                "authority_reason": "专项任务证据只服务于本次业务任务，不参与当前状态权威选择",
                "authority_policy": AUTHORITY_POLICY,
                "latest_artifact_id": record.artifact_id,
                "is_latest_observation": True,
                "version": 1,
                "version_count": 1,
            }
            continue
        streams[key].append(record)

    for key, versions in streams.items():
        ordered = sorted(versions, key=lambda item: (str(item.created_at or ""), item.artifact_id))
        complete = [item for item in ordered if _quality(item) == "complete"]
        selected = complete[-1] if complete else ordered[-1]
        latest = ordered[-1]
        for version, record in enumerate(ordered, start=1):
            quality = _quality(record)
            domain = _authority_domain(record)
            if record.artifact_id == selected.artifact_id:
                status = "authoritative" if quality == "complete" else "provisional"
            elif quality != "complete":
                status = "incomplete"
            else:
                status = "historical"
            authoritative_reason = (
                "同一设备与脚本的最近一次完整权威基线采集"
                if domain == "current_state"
                else "同一设备与脚本的最近一次完整资产巡检"
            )
            reason = {
                "authoritative": authoritative_reason,
                "provisional": "该证据流尚无完整成功采集，暂用最近一次部分采集",
                "incomplete": "不完整采集不会覆盖已有权威证据",
                "historical": "已被同一业务域中的更新完整采集替代，仍保留用于审计和固定引用",
            }[status]
            if status == "provisional" and quality == "unknown":
                reason = "该制品缺少完整性证明，仅作为临时证据；完成一次成功巡检后自动建立权威版本"
            result[record.artifact_id] = {
                "evidence_key": key,
                "evidence_role": str(_metadata(record).get("evidence_role") or "raw_observation"),
                "evidence_quality": quality,
                "authority_domain": domain,
                "authority_status": status,
                "authority_reason": reason,
                "authority_policy": AUTHORITY_POLICY,
                "authoritative_artifact_id": selected.artifact_id,
                "latest_artifact_id": latest.artifact_id,
                "is_latest_observation": record.artifact_id == latest.artifact_id,
                "version": version,
                "version_count": len(ordered),
            }
    return result


def governance_summary(records: Iterable[ArtifactRecord]) -> dict[str, Any]:
    materialized = list(records)
    projection = build_governance(materialized)
    counts = Counter(item["authority_status"] for item in projection.values())
    return {
        "policy": AUTHORITY_POLICY,
        "evidence_streams": len({item["evidence_key"] for item in projection.values()}),
        "authoritative": counts["authoritative"],
        "current_state_authoritative": sum(
            1 for item in projection.values()
            if item.get("authority_domain") == "current_state" and item.get("authority_status") == "authoritative"
        ),
        "inspection_current": sum(
            1 for item in projection.values()
            if item.get("authority_domain") == "inspection" and item.get("authority_status") == "authoritative"
        ),
        "contextual": counts["contextual"],
        "provisional": counts["provisional"],
        "incomplete": counts["incomplete"],
        "historical": counts["historical"],
        "deliverables": sum(1 for record in materialized if record.artifact_id not in projection),
    }
