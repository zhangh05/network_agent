"""Evidence lineage and authority projection for managed artifacts.

Artifact files are immutable observations.  Authority is a read-model decision:
the newest complete observation in one evidence stream is authoritative; an
incomplete observation is provisional only when no complete observation exists.
Pinned consumers such as baselines still reference their exact artifact IDs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from artifacts.schemas import ArtifactRecord


AUTHORITY_POLICY = "latest_complete_then_latest_partial"


def _metadata(record: ArtifactRecord) -> dict[str, Any]:
    return record.metadata if isinstance(record.metadata, dict) else {}


def _evidence_key(record: ArtifactRecord) -> str:
    metadata = _metadata(record)
    if record.artifact_type == "inspection_raw":
        # Inspection authority is scoped per device and script profile. This
        # derivation also repairs the read model for older records whose
        # ``evidence_key`` was mistakenly redacted as a credential.
        asset_id = str(metadata.get("asset_id", "") or "").strip()
        profile_id = str(metadata.get("script_profile_id") or metadata.get("profile_id") or "general").strip()
        if asset_id:
            return f"inspection:{asset_id}:{profile_id}"
    key = str(metadata.get("evidence_key", "") or "").strip()
    return "" if key == "[REDACTED_SECRET]" else key


def _quality(record: ArtifactRecord) -> str:
    quality = str(_metadata(record).get("evidence_quality", "") or "").strip()
    return quality if quality in {"complete", "partial"} else "unknown"


def build_governance(records: Iterable[ArtifactRecord]) -> dict[str, dict[str, Any]]:
    """Return artifact_id -> governance projection for active records."""
    materialized = list(records)
    streams: dict[str, list[ArtifactRecord]] = defaultdict(list)
    for record in materialized:
        key = _evidence_key(record)
        if key:
            streams[key].append(record)

    result: dict[str, dict[str, Any]] = {}
    for key, versions in streams.items():
        ordered = sorted(versions, key=lambda item: (str(item.created_at or ""), item.artifact_id))
        complete = [item for item in ordered if _quality(item) == "complete"]
        selected = complete[-1] if complete else ordered[-1]
        latest = ordered[-1]
        for version, record in enumerate(ordered, start=1):
            quality = _quality(record)
            if record.artifact_id == selected.artifact_id:
                status = "authoritative" if quality == "complete" else "provisional"
            elif quality != "complete":
                status = "incomplete"
            else:
                status = "historical"
            reason = {
                "authoritative": "同一设备与脚本证据流中最近一次完整成功采集",
                "provisional": "该证据流尚无完整成功采集，暂用最近一次部分采集",
                "incomplete": "不完整采集不会覆盖已有权威证据",
                "historical": "已被更新的完整采集替代，仍保留用于审计和固定引用",
            }[status]
            if status == "provisional" and quality == "unknown":
                reason = "该制品缺少完整性证明，仅作为临时证据；完成一次成功巡检后自动建立权威版本"
            result[record.artifact_id] = {
                "evidence_key": key,
                "evidence_role": str(_metadata(record).get("evidence_role") or "raw_observation"),
                "evidence_quality": quality,
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
        "provisional": counts["provisional"],
        "incomplete": counts["incomplete"],
        "historical": counts["historical"],
        "deliverables": sum(1 for record in materialized if record.artifact_id not in projection),
    }
