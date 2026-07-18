"""Network Assurance service.

The service composes existing CMDB and inspection evidence. It never stores
credentials or raw device output and never deploys configuration.
"""

from __future__ import annotations

import hashlib
import ipaddress
import fnmatch
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.modules.cmdb import service as cmdb_service
from agent.modules.inspection import service as inspection_service
from agent.modules.inspection.structured import STRUCTURED_SCHEMA_VERSION, parse_device_output
from artifacts.store import read_artifact_content
from agent.runtime.utils import now_iso
from storage.index import IndexLock
from storage.workspace_store import list_workspace_ids
from workspace.ids import validate_workspace_id

from . import store
from .models import (
    AssuranceBaseline,
    AssuranceAlarm,
    AssuranceSchedule,
    AssuranceOperation,
    BaselineCheck,
    ChangePlan,
    DriftRecord,
    IncidentRecord,
    NormalizedFact,
    StateSnapshot,
    TopologySnapshot,
)


_TERMINAL = {"succeeded", "partial", "failed", "cancelled"}
_LOG = logging.getLogger(__name__)
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_CHECK_LOCK = threading.RLock()
_OPERATION_LOCK = threading.RLock()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _llm_named_evidence(workspace_id: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project internal asset IDs to CMDB names before evidence reaches the LLM."""
    names = {
        str(item.get("asset_id", "")): str(item.get("name") or item.get("host") or "未知设备")
        for item in cmdb_service.list_assets(workspace_id)
        if item.get("asset_id")
    }
    result: list[dict[str, Any]] = []
    for item in evidence:
        row = dict(item)
        asset_id = str(row.get("asset_id", ""))
        row["asset_name"] = names.get(asset_id, "未知设备")
        for field in ("key", "rationale", "before", "after"):
            if not isinstance(row.get(field), str):
                continue
            text = str(row[field])
            for internal_id, name in names.items():
                text = text.replace(internal_id, name)
            row[field] = text
        row.pop("asset_id", None)
        result.append(row)
    return result


def _ws(workspace_id: str) -> str:
    return validate_workspace_id(workspace_id)


def _scope_dict(raw: dict[str, Any] | None) -> dict[str, Any]:
    scope = dict(raw or {})
    allowed = {"region", "location", "search", "type", "vendor", "protocol", "tags", "asset_ids", "limit"}
    scope = {key: value for key, value in scope.items() if key in allowed and value not in (None, "", [])}
    if "limit" in scope:
        try:
            scope["limit"] = max(1, min(int(scope["limit"]), 500))
        except (TypeError, ValueError):
            scope.pop("limit", None)
    return scope


def _task_scope(task: Any) -> dict[str, Any]:
    scope = getattr(task, "scope", None)
    if scope is None:
        return {}
    if isinstance(scope, dict):
        return _scope_dict(scope)
    return _scope_dict({
        "region": getattr(scope, "region", ""),
        "location": getattr(scope, "location", ""),
        "search": getattr(scope, "search", ""),
        "type": getattr(scope, "type", ""),
        "vendor": getattr(scope, "vendor", ""),
        "protocol": getattr(scope, "protocol", ""),
        "tags": list(getattr(scope, "tags", ()) or ()),
        "asset_ids": list(getattr(scope, "asset_ids", ()) or ()),
        "limit": getattr(scope, "limit", 50),
    })


def _latest_task(workspace_id: str, scope: dict[str, Any] | None = None):
    wanted = _scope_dict(scope)
    for item in inspection_service.list_tasks(workspace_id, limit=100):
        if str(item.get("status", "")) not in {"succeeded", "partial"}:
            continue
        task = inspection_service.get_task(workspace_id, str(item.get("task_id", "")), record_poll=False)
        if task is None:
            continue
        if wanted:
            actual = _task_scope(task)
            mismatch = any(actual.get(k) != v for k, v in wanted.items() if k not in {"limit"})
            if mismatch:
                continue
        return task
    return None


def _resolve_task(workspace_id: str, task_id: str = "", scope: dict[str, Any] | None = None):
    task = inspection_service.get_task(workspace_id, task_id, record_poll=False) if task_id else _latest_task(workspace_id, scope)
    if task is None:
        raise ValueError("completed_inspection_required")
    if task.status not in {"succeeded", "partial"}:
        raise ValueError(f"inspection_not_ready:{task.status}")
    return task


_VOLATILE = re.compile(
    r"(?:\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}:\d{2}:\d{2}\b|"
    r"\buptime\s*[:=]?\s*[^\n]+)", re.IGNORECASE,
)


def _digest(value: str) -> str:
    stable = _VOLATILE.sub("<volatile>", value or "")
    stable = " ".join(stable.split())
    return hashlib.sha256(stable.encode("utf-8", errors="replace")).hexdigest()[:16]


def _flatten(prefix: str, value: Any):
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(f"{prefix}.{key}" if prefix else str(key), value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(f"{prefix}[{index}]", item)
    elif value is not None:
        yield prefix, value


def _facts_from_task(task: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    observed_at = str(getattr(task, "finished_at", "") or getattr(task, "started_at", "") or now_iso())
    for asset_id, device in sorted((getattr(task, "devices", {}) or {}).items()):
        base = f"asset.{asset_id}"
        evidence = f"inspection:{task.task_id}:{asset_id}"
        metadata = {
            "name": getattr(device, "asset_name", ""),
            "host": getattr(device, "host", ""),
            "region": getattr(device, "region", ""),
            "location": getattr(device, "location", ""),
            "vendor": getattr(device, "vendor", ""),
            "type": getattr(device, "type", ""),
            "protocol": getattr(device, "protocol", ""),
            "status": getattr(device, "status", "unknown"),
        }
        for key, value in metadata.items():
            facts.append(asdict(NormalizedFact(
                key=f"{base}.{key}", value=value, asset_id=asset_id,
                category="identity" if key != "status" else "health",
                evidence_ref=evidence, observed_at=observed_at,
            )))
        parsed = dict(getattr(device, "parsed_metrics", {}) or {})
        typed = (list(parsed.get("facts") or [])
                 if isinstance(parsed.get("facts"), list)
                 and int(parsed.get("schema_version", 0) or 0) >= STRUCTURED_SCHEMA_VERSION else [])
        # Older completed tasks can be upgraded from their immutable raw artifact.
        if not typed:
            raw_parts: list[str] = []
            for result in getattr(device, "command_results", []) or []:
                artifact_id = str(getattr(result, "artifact_id", "") or "")
                content = ""
                if artifact_id:
                    try:
                        content = read_artifact_content(task.workspace_id, artifact_id, allow_sensitive=True) or ""
                    except Exception:
                        content = ""
                raw_parts.append(content or str(getattr(result, "output_snippet", "") or ""))
            parsed = parse_device_output(getattr(device, "vendor", ""), "\n".join(raw_parts))
            typed = list(parsed.get("facts") or [])
        for item in typed:
            if not isinstance(item, dict) or not item.get("key"):
                continue
            command = str(item.get("command", "") or "")
            matching = next((result for result in (getattr(device, "command_results", []) or [])
                             if command and command in str(getattr(result, "output_snippet", "") or "").lower()), None)
            artifact_id = str(getattr(matching, "artifact_id", "") or "") if matching else ""
            if not artifact_id:
                artifact_id = next((str(getattr(result, "artifact_id", "") or "")
                                    for result in (getattr(device, "command_results", []) or [])
                                    if getattr(result, "artifact_id", "")), "")
            fact_ref = f"artifact:{artifact_id}" if artifact_id else evidence
            facts.append(asdict(NormalizedFact(
                key=f"{base}.{item['key']}", value=item.get("value"), asset_id=asset_id,
                category=str(item.get("category", "state")), evidence_ref=fact_ref,
                observed_at=observed_at, resource_type=str(item.get("resource_type", "device")),
                resource_id=str(item.get("resource_id", "")), policy=str(item.get("policy", "must_equal")),
                severity=str(item.get("severity", "warning")), unit=str(item.get("unit", "")),
                warning=item.get("warning"), critical=item.get("critical"),
                direction=str(item.get("direction", "max")), command=command,
            )))
        for index, result in enumerate(getattr(device, "command_results", []) or []):
            command_key = str(getattr(result, "command_key", "") or getattr(result, "check_id", "") or index)
            prefix = f"{base}.command.{command_key}"
            artifact_id = str(getattr(result, "artifact_id", "") or "")
            ref = f"artifact:{artifact_id}" if artifact_id else evidence
            facts.append(asdict(NormalizedFact(
                key=f"{prefix}.ok", value=bool(getattr(result, "ok", False)),
                asset_id=asset_id, category="command", evidence_ref=ref,
                observed_at=observed_at,
            )))
            snippet = str(getattr(result, "output_snippet", "") or "")
            if snippet:
                facts.append(asdict(NormalizedFact(
                    key=f"{prefix}.digest", value=_digest(snippet), asset_id=asset_id,
                    category="observation", evidence_ref=ref, observed_at=observed_at,
                    severity="info",
                )))
    return facts


def _task_extraction_quality(task: Any) -> dict[str, Any]:
    complete_assets = 0
    fallback_assets = 0
    total_assets = len((getattr(task, "devices", {}) or {}))
    for device in (getattr(task, "devices", {}) or {}).values():
        parsed = dict(getattr(device, "parsed_metrics", {}) or {})
        if (parsed.get("quality") == "complete" and parsed.get("facts")
                and int(parsed.get("schema_version", 0) or 0) >= STRUCTURED_SCHEMA_VERSION):
            complete_assets += 1
            continue
        artifact_complete = False
        for result in (getattr(device, "command_results", []) or []):
            artifact_id = str(getattr(result, "artifact_id", "") or "")
            if not artifact_id:
                continue
            try:
                content = read_artifact_content(task.workspace_id, artifact_id, allow_sensitive=True) or ""
            except Exception:
                content = ""
            if content and parse_device_output(getattr(device, "vendor", ""), content).get("quality") == "complete":
                artifact_complete = True
                break
        if artifact_complete:
            complete_assets += 1
        else:
            fallback_assets += 1
    return {
        "total_assets": total_assets, "complete_assets": complete_assets,
        "fallback_assets": fallback_assets,
        "evidence_complete": total_assets > 0 and complete_assets == total_assets,
    }


def _snapshot_quality(facts: list[dict[str, Any]], source_status: str,
                      extraction: dict[str, Any] | None = None) -> dict[str, Any]:
    typed = [item for item in facts if item.get("resource_type") not in {"", "device"}
             or item.get("category") in {"interface", "routing", "protocol"}]
    categories = sorted({str(item.get("category", "")) for item in typed if item.get("category")})
    required = {"health", "interface", "routing", "protocol"}
    missing = sorted(required - set(categories))
    if source_status != "succeeded":
        level = "incomplete"
    elif not typed:
        level = "legacy"
    elif missing or (extraction is not None and not extraction.get("evidence_complete", False)):
        level = "partial"
    else:
        level = "complete"
    return {
        "level": level, "typed_fact_count": len(typed), "categories": categories,
        "missing_categories": missing, "comparable": level in {"complete", "partial", "legacy"},
        **dict(extraction or {}),
    }


def capture_snapshot(workspace_id: str, inspection_task_id: str = "", scope: dict[str, Any] | None = None) -> dict[str, Any]:
    ws = _ws(workspace_id)
    task = _resolve_task(ws, inspection_task_id, scope)
    facts = _facts_from_task(task)
    snapshot = StateSnapshot(
        snapshot_id=_id("snap"), workspace_id=ws, scope=_task_scope(task),
        inspection_task_id=task.task_id, source_status=str(task.status), facts=facts,
        asset_count=len(getattr(task, "devices", {}) or {}),
        quality=_snapshot_quality(facts, str(task.status), _task_extraction_quality(task)),
        parser_schema_version=STRUCTURED_SCHEMA_VERSION,
    )
    return store.save(ws, "snapshots", snapshot.snapshot_id, snapshot)


def create_baseline(workspace_id: str, name: str, scope: dict[str, Any] | None = None,
                    inspection_task_id: str = "") -> dict[str, Any]:
    ws = _ws(workspace_id)
    if not str(name or "").strip():
        raise ValueError("baseline_name_required")
    snapshot = capture_snapshot(ws, inspection_task_id, scope)
    if snapshot["source_status"] != "succeeded":
        store.delete(ws, "snapshots", snapshot["snapshot_id"])
        raise ValueError("complete_inspection_required_for_baseline")
    if not snapshot.get("quality", {}).get("evidence_complete", False):
        store.delete(ws, "snapshots", snapshot["snapshot_id"])
        raise ValueError("complete_evidence_required_for_baseline")
    baseline = AssuranceBaseline(
        baseline_id=_id("base"), workspace_id=ws, name=str(name).strip()[:120],
        scope=snapshot["scope"], snapshot_id=snapshot["snapshot_id"],
        source_task_id=snapshot["inspection_task_id"], fact_count=len(snapshot["facts"]),
        quality=dict(snapshot.get("quality") or {}),
        parser_schema_version=STRUCTURED_SCHEMA_VERSION,
    )
    return store.save(ws, "baselines", baseline.baseline_id, baseline)


def _upgrade_baseline_schema(ws: str, baseline: dict[str, Any]) -> dict[str, Any]:
    """Re-extract typed facts from the baseline's original immutable evidence."""
    snapshot = store.get(ws, "snapshots", str(baseline.get("snapshot_id", "")))
    if snapshot is None:
        return baseline
    quality = dict(snapshot.get("quality") or {})
    if (quality.get("typed_fact_count", 0) and "evidence_complete" in quality
            and int(snapshot.get("parser_schema_version", 0) or 0) >= STRUCTURED_SCHEMA_VERSION):
        if baseline.get("quality") != quality:
            baseline["quality"] = quality
            baseline["fact_count"] = len(snapshot.get("facts", []))
            store.save(ws, "baselines", str(baseline.get("baseline_id", "")), baseline)
        return baseline
    task = inspection_service.get_task(ws, str(baseline.get("source_task_id", "")), record_poll=False)
    if task is None or str(getattr(task, "status", "")) != "succeeded":
        return baseline
    facts = _facts_from_task(task)
    upgraded_quality = _snapshot_quality(facts, "succeeded", _task_extraction_quality(task))
    if not upgraded_quality.get("typed_fact_count"):
        return baseline
    snapshot.update(facts=facts, quality=upgraded_quality, schema_version=2,
                    parser_schema_version=STRUCTURED_SCHEMA_VERSION,
                    schema_migrated_at=now_iso())
    store.save(ws, "snapshots", str(snapshot.get("snapshot_id", "")), snapshot)
    baseline.update(fact_count=len(facts), quality=upgraded_quality, schema_version=2,
                    parser_schema_version=STRUCTURED_SCHEMA_VERSION,
                    schema_migrated_at=now_iso())
    return store.save(ws, "baselines", str(baseline.get("baseline_id", "")), baseline)


def list_baselines(workspace_id: str) -> list[dict[str, Any]]:
    ws = _ws(workspace_id)
    return [_upgrade_baseline_schema(ws, item) for item in store.list_records(ws, "baselines")]


def start_baseline_check(workspace_id: str, baseline_id: str) -> dict[str, Any]:
    """Start a fresh inspection for a baseline instead of reusing old evidence."""
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None:
        raise ValueError("baseline_not_found")
    baseline = _upgrade_baseline_schema(ws, baseline)
    for existing in store.list_records(ws, "checks", limit=100):
        if existing.get("baseline_id") == baseline_id and existing.get("status") == "collecting":
            refreshed = refresh_baseline_check(ws, str(existing.get("check_id", "")))
            if refreshed.get("status") == "collecting":
                return refreshed
    check_id = _id("check")
    task = inspection_service.start_background_task(
        workspace_id=ws,
        profile_id="general",
        scope=baseline.get("scope") or {},
        created_by=f"assurance:baseline_check:{check_id}",
        max_concurrency=3,
    )
    check = BaselineCheck(
        check_id=check_id, workspace_id=ws, baseline_id=baseline_id,
        scope=_scope_dict(baseline.get("scope") or {}), inspection_task_id=task.task_id,
        status="failed" if task.status == "failed" else "collecting",
        error=str(task.error or ""), total_assets=int(task.total_assets or 0),
        finished_at=now_iso() if task.status == "failed" else "",
    )
    return store.save(ws, "checks", check.check_id, check)


def _task_progress(task: Any) -> dict[str, int]:
    total = int(getattr(task, "total_assets", 0) or len(getattr(task, "devices", {}) or {}))
    succeeded = int(getattr(task, "succeeded", 0) or 0)
    failed = int(getattr(task, "failed", 0) or 0)
    partial = int(getattr(task, "partial", 0) or 0)
    skipped = int(getattr(task, "skipped", 0) or 0)
    return {
        "total_assets": total,
        "completed_assets": succeeded + failed + partial + skipped,
        "succeeded_assets": succeeded,
        "failed_assets": failed,
        "partial_assets": partial,
    }


def _task_artifact_ids(task: Any) -> list[str]:
    artifact_ids: list[str] = []
    for device in (getattr(task, "devices", {}) or {}).values():
        for result in (getattr(device, "command_results", []) or []):
            artifact_id = str(getattr(result, "artifact_id", "") or "")
            if artifact_id and artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
    return artifact_ids


def _task_error_details(task: Any) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for asset_id, device in (getattr(task, "devices", {}) or {}).items():
        errors = [str(item).strip() for item in (getattr(device, "errors", []) or []) if str(item).strip()]
        errors.extend(str(getattr(item, "error", "") or "").strip()
                      for item in (getattr(device, "command_results", []) or [])
                      if not getattr(item, "ok", False) and getattr(item, "error", ""))
        for message in list(dict.fromkeys(errors))[:3]:
            details.append({
                "asset_id": str(asset_id),
                "asset_name": str(getattr(device, "asset_name", "") or asset_id),
                "message": message[:500],
            })
    return details[:50]


def refresh_baseline_check(workspace_id: str, check_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    with _CHECK_LOCK:
        check = store.get(ws, "checks", check_id)
        if check is None:
            raise ValueError("baseline_check_not_found")
        if check.get("status") != "collecting":
            if check.get("status") in {"failed", "cancelled"} and not check.get("error_details"):
                task = inspection_service.get_task(
                    ws, str(check.get("inspection_task_id", "")), record_poll=False,
                )
                if task is not None:
                    details = _task_error_details(task)
                    if details:
                        check["error_details"] = details
                        if check.get("error") in {"", "inspection_failed", "inspection_cancelled"}:
                            check["error"] = details[0]["message"]
                        check["updated_at"] = now_iso()
                        return store.save(ws, "checks", check_id, check)
            return check
        task = inspection_service.get_task(
            ws, str(check.get("inspection_task_id", "")), record_poll=False,
        )
        if task is None:
            check.update(status="failed", error="inspection_task_missing", finished_at=now_iso())
        else:
            check.update(_task_progress(task))
            check["artifact_ids"] = _task_artifact_ids(task)
            task_status = str(task.status or "")
            if task_status in {"succeeded", "partial"}:
                drift = check_baseline(
                    ws, str(check.get("baseline_id", "")), str(task.task_id),
                )
                check.update(
                    status="completed", drift_id=drift["drift_id"],
                    error="", finished_at=now_iso(),
                )
            elif task_status in {"failed", "cancelled"}:
                details = _task_error_details(task)
                check.update(
                    status=task_status,
                    error=str(task.error or (details[0]["message"] if details else f"inspection_{task_status}")),
                    error_details=details,
                    finished_at=now_iso(),
                )
        check["updated_at"] = now_iso()
        return store.save(ws, "checks", check_id, check)


def get_baseline_check(workspace_id: str, check_id: str) -> dict[str, Any]:
    return refresh_baseline_check(workspace_id, check_id)


def list_baseline_checks(workspace_id: str) -> list[dict[str, Any]]:
    ws = _ws(workspace_id)
    rows = store.list_records(ws, "checks", limit=100)
    return [
        refresh_baseline_check(ws, str(row.get("check_id", "")))
        if row.get("status") in {"collecting", "failed", "cancelled"} else row
        for row in rows
    ]


def _change_severity(key: str, kind: str) -> str:
    if key.endswith(".status") or kind in {"added", "removed"}:
        return "critical" if kind == "changed" else "warning"
    if key.endswith(".ok") or ".metric." in key:
        return "warning"
    return "info"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_fact(old: dict[str, Any] | None, new: dict[str, Any] | None,
                   *, incomplete: bool = False,
                   reference_incomplete: bool = False) -> dict[str, Any] | None:
    fact = new or old or {}
    policy = str(fact.get("policy", "must_equal") or "must_equal")
    if policy == "ignore" or (new is None and incomplete):
        return None
    kind = "added" if old is None else "removed" if new is None else "changed"
    before = old.get("value") if old else None
    after = new.get("value") if new else None
    if old is None and new is not None and reference_incomplete:
        return {
            "key": str(fact.get("key", "")), "kind": "newly_observable",
            "asset_id": str(fact.get("asset_id", "")), "before": None, "after": after,
            "severity": "info", "policy": "coverage",
            "rationale": "基线证据未覆盖该事实，本次首次观察，不判定为异常",
            "category": str(fact.get("category", "state")),
            "resource_type": str(fact.get("resource_type", "device")),
            "resource_id": str(fact.get("resource_id", "")), "unit": str(fact.get("unit", "")),
            "evidence_ref": str(fact.get("evidence_ref", "")),
        }
    severity = str(fact.get("severity", "") or _change_severity(str(fact.get("key", "")), kind))
    violated = old is None or new is None or before != after
    rationale = "与状态基线不一致"
    if policy == "threshold" and new is not None:
        value = _numeric(after)
        warning = _numeric(new.get("warning"))
        critical = _numeric(new.get("critical"))
        direction = str(new.get("direction", "max"))
        if value is None:
            violated, severity, rationale = True, "warning", "数值事实无法解析"
        else:
            warn_hit = warning is not None and (value >= warning if direction == "max" else value <= warning)
            crit_hit = critical is not None and (value >= critical if direction == "max" else value <= critical)
            violated = warn_hit or crit_hit
            severity = "critical" if crit_hit else "warning"
            rationale = f"当前值 {value:g} {'超过' if direction == 'max' else '低于'}阈值 {critical if crit_hit else warning:g}"
            kind = "threshold_breach"
    elif policy == "baseline_delta" and old is not None and new is not None:
        old_value, new_value = _numeric(before), _numeric(after)
        if old_value is None or new_value is None:
            violated = before != after
        else:
            delta = abs(new_value - old_value) / max(abs(old_value), 1.0)
            warning = _numeric(new.get("warning")) or 0.2
            critical = _numeric(new.get("critical")) or 0.5
            violated = delta >= warning
            severity = "critical" if delta >= critical else "warning"
            rationale = f"相对基线偏差 {delta:.1%}，允许偏差 {warning:.1%}"
            kind = "baseline_delta"
    if not violated:
        return None
    return {
        "key": str(fact.get("key", "")), "kind": kind,
        "asset_id": str(fact.get("asset_id", "")), "before": before, "after": after,
        "severity": severity, "policy": policy, "rationale": rationale,
        "category": str(fact.get("category", "state")),
        "resource_type": str(fact.get("resource_type", "device")),
        "resource_id": str(fact.get("resource_id", "")),
        "unit": str(fact.get("unit", "")),
        "evidence_ref": str((new or old or {}).get("evidence_ref", "")),
    }


def compare_snapshots(reference: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {item["key"]: item for item in reference.get("facts", [])}
    after = {item["key"]: item for item in current.get("facts", [])}
    changes: list[dict[str, Any]] = []
    reference_quality = dict(reference.get("quality") or {})
    reference_incomplete = reference_quality.get("level") != "complete" or reference_quality.get("evidence_complete") is False
    for key in sorted(set(before) | set(after)):
        change = _evaluate_fact(before.get(key), after.get(key),
                                incomplete=current.get("source_status") == "partial",
                                reference_incomplete=reference_incomplete)
        if change:
            changes.append(change)
    return changes


def check_baseline(workspace_id: str, baseline_id: str, inspection_task_id: str = "") -> dict[str, Any]:
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None:
        raise ValueError("baseline_not_found")
    baseline = _upgrade_baseline_schema(ws, baseline)
    reference = store.get(ws, "snapshots", str(baseline.get("snapshot_id", "")))
    if reference is None:
        raise ValueError("baseline_snapshot_not_found")
    current = capture_snapshot(ws, inspection_task_id, baseline.get("scope") or {})
    changes = compare_snapshots(reference, current)
    summary = {level: sum(1 for change in changes if change["severity"] == level) for level in ("critical", "warning", "info")}
    summary["newly_observable"] = sum(1 for change in changes if change.get("kind") == "newly_observable")
    meaningful_change = bool(summary["critical"] or summary["warning"])
    drift = DriftRecord(
        drift_id=_id("drift"), workspace_id=ws, baseline_id=baseline_id,
        snapshot_id=current["snapshot_id"], source_task_id=current["inspection_task_id"],
        status=("partial" if current.get("source_status") == "partial"
                else "unverified" if not current.get("quality", {}).get("comparable", False)
                else "drifted" if meaningful_change else "compliant"),
        changes=changes, summary=summary,
        incomplete=current.get("source_status") == "partial",
    )
    return store.save(ws, "drifts", drift.drift_id, drift)


def list_drifts(workspace_id: str, baseline_id: str = "") -> list[dict[str, Any]]:
    ws = _ws(workspace_id)
    rows = store.list_records(ws, "drifts", limit=200)
    # State-baseline checks were an invalid product concept: a baseline only
    # establishes authority. Hide records produced by that retired workflow;
    # other domains (scheduled checks, incidents, changes) still compare
    # against the baseline under their own business purpose.
    retired = {str(item.get("drift_id", "")) for item in store.list_records(ws, "checks", limit=500) if item.get("drift_id")}
    return [row for row in rows if row.get("drift_id") not in retired and (not baseline_id or row.get("baseline_id") == baseline_id)]


def _inspection_text(task: Any, asset_id: str) -> str:
    device = (getattr(task, "devices", {}) or {}).get(asset_id)
    if device is None:
        return ""
    return "\n".join(str(getattr(result, "output_snippet", "") or "") for result in (getattr(device, "command_results", []) or []))


def _aggregate_topology_edges(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw observations into one logical relationship per device pair."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        source, target = str(claim.get("source", "")), str(claim.get("target", ""))
        if not source or not target or source == target:
            continue
        pair = sorted((source, target))
        grouped.setdefault("|".join(pair), []).append(claim)
    result: list[dict[str, Any]] = []
    for edge_id, pair_claims in sorted(grouped.items()):
        source, target = edge_id.split("|", 1)
        relationship_types = sorted({str(item.get("type", "relationship")) for item in pair_claims})
        evidence_refs = sorted({
            str(ref)
            for item in pair_claims
            for ref in ([item.get("evidence_ref")] + list(item.get("evidence_refs") or []))
            if ref
        })
        result.append({
            "edge_id": edge_id,
            "source": source,
            "target": target,
            "type": "device_relationship",
            "relationship_types": relationship_types,
            "claim_count": len(pair_claims),
            "evidence_refs": evidence_refs,
            "confidence": "confirmed" if any(item.get("confidence") == "confirmed" for item in pair_claims) else "observed",
        })
    return result


def _dependency(source: str, target: str, kind: str, *, bidirectional: bool = False,
                **evidence: Any) -> list[dict[str, Any]]:
    """Describe fault propagation, not merely drawing direction.

    A route observed on ``source`` via ``target`` means target failure may affect
    source. Symmetric adjacencies emit both propagation directions.
    """
    rows = [{
        "source_asset": source,
        "target_asset": target,
        "type": kind,
        "propagates_from": target,
        "propagates_to": source,
        **evidence,
    }]
    if bidirectional:
        rows.append({
            "source_asset": target,
            "target_asset": source,
            "type": kind,
            "propagates_from": source,
            "propagates_to": target,
            **evidence,
        })
    return rows


def _dedupe_dependencies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (str(item.get("propagates_from", "")), str(item.get("propagates_to", "")), str(item.get("type", "")))
        if not all(key):
            continue
        existing = grouped.setdefault(key, {**item, "evidence_refs": []})
        refs = [item.get("evidence_ref"), *(item.get("evidence_refs") or [])]
        existing["evidence_refs"] = sorted(set(existing.get("evidence_refs") or []) | {str(ref) for ref in refs if ref})
        existing.pop("evidence_ref", None)
    return list(grouped.values())


def build_topology(workspace_id: str, inspection_task_id: str = "") -> dict[str, Any]:
    ws = _ws(workspace_id)
    assets = cmdb_service.list_assets(ws)
    task = None
    if inspection_task_id:
        task = _resolve_task(ws, inspection_task_id)
    else:
        task = _latest_task(ws)
    nodes = [{
        "asset_id": item.get("asset_id", ""), "name": item.get("name", ""),
        "host": item.get("host", ""), "type": item.get("type", ""),
        "vendor": item.get("vendor", ""), "region": item.get("region", ""),
        "location": item.get("location", ""),
        "tags": list(item.get("tags") or []),
    } for item in assets]
    by_id = {node["asset_id"]: node for node in nodes if node["asset_id"]}
    edges: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for asset in assets:
        source = str(asset.get("asset_id", ""))
        explicit = asset.get("peer_asset_ids") or asset.get("links") or []
        if isinstance(explicit, str):
            explicit = [part.strip() for part in explicit.split(",") if part.strip()]
        for target in explicit if isinstance(explicit, list) else []:
            target_id = str(target.get("asset_id", "") if isinstance(target, dict) else target)
            if source in by_id and target_id in by_id and source != target_id:
                key = "|".join(sorted((source, target_id)))
                edges[key] = {"edge_id": key, "source": source, "target": target_id, "type": "cmdb_link", "confidence": "confirmed", "evidence_ref": "cmdb"}
                dependencies.extend(_dependency(source, target_id, "cmdb_link", bidirectional=True, evidence_ref="cmdb"))
    if task is not None:
        typed_facts = _facts_from_task(task)
        ip_owners: dict[str, str] = {}
        network_owners: dict[str, list[tuple[str, str, str]]] = {}
        observed_interfaces: list[tuple[str, Any, str]] = []
        for fact in typed_facts:
            if fact.get("category") == "interface" and str(fact.get("key", "")).endswith(".address"):
                try:
                    interface = ipaddress.ip_interface(str(fact.get("value")))
                    owner = str(fact.get("asset_id", ""))
                    ip_owners[str(interface.ip)] = owner
                    network_owners.setdefault(str(interface.network), []).append(
                        (owner, str(fact.get("resource_id", "")), str(fact.get("evidence_ref", ""))),
                    )
                    observed_interfaces.append((owner, interface, str(fact.get("evidence_ref", ""))))
                except ValueError:
                    continue
            if fact.get("resource_type") not in {"", "device"}:
                resources.append({
                    "resource_key": fact.get("key"), "asset_id": fact.get("asset_id"),
                    "resource_type": fact.get("resource_type"), "resource_id": fact.get("resource_id"),
                    "category": fact.get("category"), "evidence_ref": fact.get("evidence_ref"),
                })
        for fact in typed_facts:
            source = str(fact.get("asset_id", ""))
            target = ""
            edge_type = ""
            if fact.get("resource_type") == "bgp_peer" and str(fact.get("key", "")).endswith(".state"):
                target = ip_owners.get(str(fact.get("resource_id", "")), "")
                edge_type = "bgp_peer"
            elif fact.get("resource_type") == "route" and isinstance(fact.get("value"), dict):
                target = ip_owners.get(str(fact["value"].get("next_hop", "")), "")
                edge_type = "route_next_hop"
            if source and target and source != target:
                key = f"{source}|{target}|{edge_type}"
                edges[key] = {
                    "edge_id": key, "source": source, "target": target, "type": edge_type,
                    "confidence": "observed", "evidence_ref": fact.get("evidence_ref", ""),
                    "resource_key": fact.get("key", ""),
                }
                dependencies.extend(_dependency(
                    source, target, edge_type, bidirectional=edge_type == "bgp_peer",
                    source_resource=fact.get("key", ""), evidence_ref=fact.get("evidence_ref", ""),
                ))
        for network, owners in network_owners.items():
            unique = list(dict.fromkeys(owner for owner, _interface, _ref in owners if owner))
            for index, source in enumerate(unique):
                for target in unique[index + 1:]:
                    refs = sorted({ref for owner, _interface, ref in owners if owner in {source, target} and ref})
                    key = f"{source}|{target}|connected_subnet"
                    edges[key] = {
                        "edge_id": key, "source": source, "target": target, "type": "connected_subnet",
                        "confidence": "observed", "evidence_ref": refs[0] if refs else "",
                        "network": network,
                    }
                    dependencies.extend(_dependency(
                        source, target, "connected_subnet", bidirectional=True,
                        network=network, evidence_refs=refs,
                    ))
        for index, (source, source_if, source_ref) in enumerate(observed_interfaces):
            for target, target_if, target_ref in observed_interfaces[index + 1:]:
                if source == target or not (source_if.ip in target_if.network or target_if.ip in source_if.network):
                    continue
                left, right = sorted((source, target))
                key = f"{left}|{right}|connected_subnet"
                if key in edges:
                    continue
                refs = [ref for ref in (source_ref, target_ref) if ref]
                edges[key] = {
                    "edge_id": key, "source": left, "target": right, "type": "connected_subnet",
                    "confidence": "observed", "evidence_ref": refs[0] if refs else "",
                    "network": f"{source_if.network}|{target_if.network}", "mask_mismatch": True,
                }
                dependencies.extend(_dependency(
                    left, right, "connected_subnet", bidirectional=True,
                    network=f"{source_if.network}|{target_if.network}", mask_mismatch=True,
                    evidence_refs=refs,
                ))
        identifier_owners: dict[str, set[str]] = {}
        for target, node in by_id.items():
            for raw in (node.get("name", ""), node.get("host", "")):
                token = str(raw).strip().lower()
                if len(token) >= 3:
                    identifier_owners.setdefault(token, set()).add(target)
        identifiers = tuple(identifier_owners)

        def is_unambiguous(token: str, target: str) -> bool:
            return (
                len(token) >= 3
                and identifier_owners.get(token) == {target}
                and not any(token != other and token in other for other in identifiers)
            )

        for source in by_id:
            text = _inspection_text(task, source).lower()
            if not text:
                continue
            for target, node in by_id.items():
                if source == target:
                    continue
                names = [str(node.get("name", "")).lower(), str(node.get("host", "")).lower()]
                if any(
                    token and is_unambiguous(token, target)
                    and token in text
                    for token in names
                ):
                    key = "|".join(sorted((source, target)))
                    if key not in edges:
                        evidence_ref = f"inspection:{task.task_id}"
                        edges[key] = {"edge_id": key, "source": source, "target": target, "type": "observed_neighbor", "confidence": "observed", "evidence_ref": evidence_ref}
                        dependencies.extend(_dependency(source, target, "observed_neighbor", bidirectional=True, evidence_ref=evidence_ref))
    evidence_claims = list(edges.values())
    topology = TopologySnapshot(
        topology_id=_id("topo"), workspace_id=ws, nodes=nodes,
        edges=_aggregate_topology_edges(evidence_claims), evidence_claims=evidence_claims,
        resources=resources, dependencies=_dedupe_dependencies(dependencies),
        source_task_id=getattr(task, "task_id", "") if task else "",
    )
    saved = store.save(ws, "topologies", topology.topology_id, topology)
    store.prune(ws, "topologies", "topology_id", keep=20)
    return saved


def get_topology(workspace_id: str) -> dict[str, Any]:
    rows = store.list_records(_ws(workspace_id), "topologies", limit=1)
    return rows[0] if rows else build_topology(workspace_id)


def _affected_resources(topology: dict[str, Any], affected_ids: set[str]) -> list[dict[str, Any]]:
    """Summarise only explicitly observed resources on potentially affected devices."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in topology.get("resources", []):
        asset_id = str(item.get("asset_id", ""))
        resource_type = str(item.get("resource_type", ""))
        resource_id = str(item.get("resource_id", ""))
        if asset_id not in affected_ids or not resource_type or not resource_id:
            continue
        key = (asset_id, resource_type, resource_id)
        row = grouped.setdefault(key, {
            "asset_id": asset_id, "resource_type": resource_type,
            "resource_id": resource_id, "categories": [], "evidence_refs": [],
        })
        category = str(item.get("category", ""))
        evidence_ref = str(item.get("evidence_ref", ""))
        if category and category not in row["categories"]:
            row["categories"].append(category)
        if evidence_ref and evidence_ref not in row["evidence_refs"]:
            row["evidence_refs"].append(evidence_ref)
    return list(grouped.values())


def _business_services(topology: dict[str, Any], affected_ids: set[str]) -> list[dict[str, str]]:
    """Read explicit CMDB service tags; absence is reported as missing coverage."""
    rows: list[dict[str, str]] = []
    for node in topology.get("nodes", []):
        asset_id = str(node.get("asset_id", ""))
        if asset_id not in affected_ids:
            continue
        for tag in node.get("tags", []) or []:
            raw = str(tag).strip()
            prefix, separator, value = raw.partition(":")
            if separator and prefix.lower() in {"service", "business"} and value.strip():
                rows.append({"asset_id": asset_id, "service": value.strip(), "source": "cmdb_tag"})
    return rows


def _source_validation(workspace_id: str, inspection_task_id: str,
                       source_assets: list[str], source_mode: str,
                       drift_id: str = "") -> dict[str, Any]:
    """Use the fresh source inspection instead of treating selection as a fault fact."""
    ws = _ws(workspace_id)
    current = capture_snapshot(ws, inspection_task_id)
    baseline = next(iter(list_baselines(ws)), None)
    result: dict[str, Any] = {
        "mode": source_mode, "status": "hypothetical", "baseline_id": "",
        "current_snapshot_id": current["snapshot_id"], "changes": [],
        "evidence_complete": bool(current.get("quality", {}).get("evidence_complete")),
    }
    if source_mode == "hypothetical":
        result["message"] = "按设备故障假设计算，不宣称设备当前已发生故障。"
        return result
    if baseline is None:
        result.update(status="blocked", message="尚未确立权威状态基线，无法确认当前故障事实。")
        return result
    reference = store.get(ws, "snapshots", str(baseline.get("snapshot_id", "")))
    if reference is None:
        result.update(status="blocked", message="权威基线缺少状态快照，无法确认当前故障事实。")
        return result
    selected = set(source_assets)
    scoped_reference = {
        **reference,
        "facts": [item for item in reference.get("facts", []) if str(item.get("asset_id", "")) in selected],
    }
    changes = [
        item for item in compare_snapshots(scoped_reference, current)
        if item.get("severity") in {"critical", "warning"}
        and item.get("resource_type") not in {"", "device"}
    ]
    result.update(
        baseline_id=str(baseline.get("baseline_id", "")), changes=changes,
        status="confirmed" if changes else "not_confirmed",
        message=("本次巡检发现相对权威基线的结构化异常。" if changes
                 else "本次巡检未复现可确认的结构化异常，停止传播计算。"),
    )
    if drift_id:
        result["source_record_id"] = drift_id
    return result


def fault_propagation_analysis(workspace_id: str, asset_ids: list[str], depth: int = 2,
                               drift_id: str = "", source_validation: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(asset_ids, list):
        raise TypeError("asset_ids_must_be_array")
    topology = get_topology(workspace_id)
    depth = max(1, min(int(depth or 2), 6))
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for dependency in topology.get("dependencies", []):
        source = str(dependency.get("propagates_from", ""))
        target = str(dependency.get("propagates_to", ""))
        if source and target and source != target:
            adjacency.setdefault(source, []).append({**dependency, "asset_id": target})
    drift = store.get(_ws(workspace_id), "drifts", drift_id) if drift_id else None
    if drift_id and drift is None:
        raise ValueError("drift_not_found")
    drift_changes = list((drift or {}).get("changes") or [])
    drift_assets = [str(item.get("asset_id", "")) for item in drift_changes if item.get("asset_id")]
    starts = list(dict.fromkeys(str(item).strip() for item in (asset_ids or drift_assets) if str(item).strip()))
    nodes = {str(item.get("asset_id", "")): item for item in topology.get("nodes", [])}
    if not starts:
        raise ValueError("impact_asset_required")
    missing = [item for item in starts if item not in nodes]
    if missing:
        raise ValueError(f"impact_asset_not_found:{','.join(missing)}")
    seen = set(starts)
    frontier = set(starts)
    paths: dict[str, list[str]] = {item: [item] for item in starts}
    layers: list[list[str]] = []
    propagation: list[dict[str, Any]] = []
    validation = dict(source_validation or {"mode": "hypothetical", "status": "hypothetical", "changes": []})
    may_propagate = validation.get("status") in {"confirmed", "hypothetical"}
    if not may_propagate:
        return {
            "source_assets": starts, "source_validation": validation,
            "drift_id": drift_id, "trigger_changes": validation.get("changes", []),
            "affected_assets": [], "affected_resources": [], "business_services": [],
            "business_impact": {"status": "not_evaluated", "reason": "source_fault_not_confirmed"},
            "layers": [], "propagation": [], "edge_count": len(topology.get("edges", [])),
            "evidence_claim_count": len(topology.get("evidence_claims", [])),
            "dependency_count": len(topology.get("dependencies", [])),
            "confidence": "blocked", "conclusion": validation.get("message", "故障源尚未确认。"),
        }
    for _ in range(depth):
        incoming: dict[str, list[dict[str, Any]]] = {}
        for node in frontier:
            for relation in adjacency.get(node, []):
                target = str(relation.get("asset_id", ""))
                if target and target not in seen:
                    incoming.setdefault(target, []).append(relation)
        next_layer = set(incoming)
        if not next_layer:
            break
        layer_index = len(layers) + 1
        layers.append(sorted(next_layer))
        for target in sorted(next_layer):
            supporting = incoming[target]
            predecessor = str(supporting[0].get("propagates_from", ""))
            paths[target] = [*paths.get(predecessor, [predecessor]), target]
            alternatives = sorted({
                str(candidate.get("propagates_from", ""))
                for candidate in topology.get("dependencies", [])
                if str(candidate.get("propagates_to", "")) == target
                and str(candidate.get("type", "")) in {str(item.get("type", "")) for item in supporting}
                and str(candidate.get("propagates_from", "")) not in set(paths[target])
            } - {""})
            propagation.append({
                "asset_id": target, "layer": layer_index,
                "path": paths[target],
                "via": sorted({str(item.get("type", "dependency")) for item in supporting}),
                "evidence_refs": sorted({str(ref) for item in supporting for ref in item.get("evidence_refs", []) if ref}),
                "redundancy": {
                    "status": "alternate_dependency_observed" if alternatives else "single_dependency_observed",
                    "alternate_sources": alternatives,
                    "scope": "observed_dependencies_only",
                    "failover_verified": False,
                },
            })
        seen.update(next_layer); frontier = next_layer
    affected_ids = set(seen - set(starts))
    resources = _affected_resources(topology, affected_ids)
    services = _business_services(topology, affected_ids)
    confidence = "evidence_based" if topology.get("dependencies") else "blocked"
    return {
        "source_assets": starts, "drift_id": drift_id,
        "source_validation": validation,
        "trigger_changes": list(validation.get("changes") or drift_changes)[:100],
        "affected_assets": [nodes[item] for item in sorted(seen - set(starts)) if item in nodes],
        "affected_resources": resources,
        "business_services": services,
        "business_impact": ({"status": "mapped", "service_count": len(services)} if services else {
            "status": "unavailable",
            "reason": "CMDB 未提供 service: 或 business: 业务标签，不能把设备传播等同于业务影响。",
        }),
        "layers": layers, "propagation": propagation,
        "edge_count": len(topology.get("edges", [])),
        "evidence_claim_count": len(topology.get("evidence_claims", [])),
        "dependency_count": len(topology.get("dependencies", [])),
        "confidence": confidence,
        "conclusion": ("已沿观测证据支持的有向依赖计算故障传播候选。" if topology.get("dependencies")
                       else "缺少可验证的有向依赖，不能计算故障传播。"),
    }


_OPERATION_KINDS = {"baseline_capture", "topology_refresh", "fault_propagation", "incident", "change_pre", "change_post"}


def _operation_scope(ws: str, kind: str, ref_id: str, asset_ids: list[str],
                     scope: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    selected = list(dict.fromkeys(str(item).strip() for item in asset_ids if str(item).strip()))
    if kind == "topology_refresh":
        selected = [str(item.get("asset_id", "")) for item in cmdb_service.list_assets(ws) if item.get("asset_id")]
    elif kind == "incident":
        incident = store.get(ws, "incidents", ref_id)
        if incident is None:
            raise ValueError("incident_not_found")
        selected = selected or list(incident.get("affected_assets") or [])
        scope = scope or incident.get("scope") or {}
        if not selected and not _scope_dict(scope):
            baseline = next(iter(list_baselines(ws)), None)
            scope = (baseline or {}).get("scope") or {}
        if not selected and not _scope_dict(scope):
            selected = [str(item.get("asset_id", "")) for item in cmdb_service.list_assets(ws) if item.get("asset_id")]
    elif kind in {"change_pre", "change_post"}:
        change = store.get(ws, "changes", ref_id)
        if change is None:
            raise ValueError("change_not_found")
        selected = list(change.get("asset_ids") or [])
    elif kind == "fault_propagation" and not selected:
        drift = store.get(ws, "drifts", ref_id) if ref_id else None
        if drift is not None:
            selected = list(dict.fromkeys(str(item.get("asset_id", "")) for item in drift.get("changes", []) if item.get("asset_id")))
        if not selected:
            raise ValueError("impact_asset_or_drift_required")
    resolved = _scope_dict(scope)
    if selected:
        known = {str(item.get("asset_id", "")) for item in cmdb_service.list_assets(ws)}
        missing = [item for item in selected if item not in known]
        if missing:
            raise ValueError(f"impact_asset_not_found:{','.join(missing)}")
        resolved["asset_ids"] = selected
        resolved["limit"] = max(len(selected), int(resolved.get("limit", 0) or 0), 1)
    return resolved, selected


def start_assurance_operation(workspace_id: str, kind: str, *, ref_id: str = "",
                              asset_ids: list[str] | None = None,
                              scope: dict[str, Any] | None = None,
                              depth: int = 2, baseline_name: str = "",
                              source_mode: str = "hypothetical") -> dict[str, Any]:
    ws = _ws(workspace_id)
    kind = str(kind or "").strip()
    if kind not in _OPERATION_KINDS:
        raise ValueError("invalid_assurance_operation_kind")
    if asset_ids is not None and not isinstance(asset_ids, list):
        raise TypeError("asset_ids_must_be_array")
    if kind == "baseline_capture" and not str(baseline_name or "").strip():
        raise ValueError("baseline_name_required")
    resolved_scope, selected = _operation_scope(ws, kind, ref_id, asset_ids or [], scope)
    propagation_depth = max(1, min(int(depth), 5))
    if kind == "fault_propagation":
        source_mode = "confirmed" if ref_id else str(source_mode or "hypothetical")
        if source_mode not in {"confirmed", "hypothetical"}:
            raise ValueError("invalid_fault_source_mode")
    for row in store.list_records(ws, "operations", limit=200):
        same_request = row.get("kind") == kind and row.get("ref_id") == ref_id
        if kind == "baseline_capture":
            same_request = same_request and str((row.get("result") or {}).get("baseline_name", "")) == str(baseline_name).strip()
        if kind == "fault_propagation":
            existing_result = dict(row.get("result") or {})
            same_request = same_request and (
                list(existing_result.get("source_assets") or []) == selected
                and int(existing_result.get("depth", 2) or 2) == propagation_depth
                and str(existing_result.get("source_mode", "hypothetical")) == source_mode
            )
        if same_request and row.get("status") == "collecting":
            return refresh_assurance_operation(ws, str(row.get("operation_id", "")))
    operation_id = _id("op")
    task = inspection_service.start_background_task(
        workspace_id=ws, profile_id="general", scope=resolved_scope,
        created_by=f"assurance:{kind}:{operation_id}", max_concurrency=3,
    )
    operation = AssuranceOperation(
        operation_id=operation_id, workspace_id=ws, kind=kind, ref_id=ref_id,
        scope=resolved_scope, inspection_task_id=task.task_id,
        status="failed" if task.status == "failed" else "collecting",
        phase="failed" if task.status == "failed" else "collecting_evidence",
        result=({"baseline_name": str(baseline_name).strip()[:120]} if kind == "baseline_capture"
                else {"source_assets": selected, "depth": propagation_depth, "source_mode": source_mode} if kind == "fault_propagation"
                else {"source_assets": selected} if selected else {}),
        error=str(task.error or ""), total_assets=int(task.total_assets or 0),
        finished_at=now_iso() if task.status == "failed" else "",
    )
    saved = store.save(ws, "operations", operation.operation_id, operation)
    if kind == "incident":
        incident = store.get(ws, "incidents", ref_id) or {}
        incident.update(operation_id=operation.operation_id, inspection_task_id=task.task_id,
                        status="investigating", updated_at=now_iso())
        store.save(ws, "incidents", ref_id, incident)
    elif kind in {"change_pre", "change_post"}:
        change = store.get(ws, "changes", ref_id) or {}
        change[f"{'precheck' if kind == 'change_pre' else 'postcheck'}_operation_id"] = operation.operation_id
        change["status"] = "collecting_precheck" if kind == "change_pre" else "collecting_postcheck"
        change["updated_at"] = now_iso()
        store.save(ws, "changes", ref_id, change)
    return saved


def _snapshot_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return compare_snapshots(before, after)


def _incident_result(ws: str, operation: dict[str, Any], task: Any) -> dict[str, Any]:
    incident = store.get(ws, "incidents", str(operation.get("ref_id", ""))) or {}
    hypotheses: list[dict[str, Any]] = []
    evidence_refs: set[str] = set()
    affected: set[str] = set(incident.get("affected_assets") or [])
    changes: list[dict[str, Any]] = []
    current = capture_snapshot(ws, task.task_id)
    drift = store.get(ws, "drifts", str(incident.get("drift_id", ""))) if incident.get("drift_id") else None
    baseline = store.get(ws, "baselines", str((drift or {}).get("baseline_id", ""))) if drift else None
    if baseline is None:
        baseline = next((row for row in list_baselines(ws)
                         if not incident.get("scope") or all((row.get("scope") or {}).get(k) == v for k, v in incident.get("scope", {}).items())), None)
    reference = store.get(ws, "snapshots", str((baseline or {}).get("snapshot_id", ""))) if baseline else None
    if reference:
        changes = compare_snapshots(reference, current)
        for index, change in enumerate(sorted(changes, key=lambda item: {"critical": 0, "warning": 1, "info": 2}.get(item.get("severity"), 3))[:20]):
            affected.add(str(change.get("asset_id", "")))
            evidence_refs.add(str(change.get("evidence_ref", "")))
            hypotheses.append({
                "hypothesis_id": f"hyp_fact_{index + 1}",
                "statement": f"{change.get('resource_type')} {change.get('resource_id') or change.get('key')}：{change.get('rationale')}",
                "confidence": "confirmed", "evidence_ref": change.get("evidence_ref", ""),
                "status": "open", "fact_key": change.get("key", ""),
            })
    for asset_id, device in (getattr(task, "devices", {}) or {}).items():
        failed_commands = [result for result in (getattr(device, "command_results", []) or []) if not getattr(result, "ok", False)]
        errors = list(getattr(device, "errors", []) or [])
        if str(getattr(device, "status", "")) not in {"succeeded"} or failed_commands or errors:
            affected.add(asset_id)
        for result in failed_commands[:6]:
            ref = f"artifact:{getattr(result, 'artifact_id', '')}" if getattr(result, "artifact_id", "") else f"inspection:{task.task_id}:{asset_id}"
            evidence_refs.add(ref)
            hypotheses.append({
                "hypothesis_id": _id("hyp"),
                "statement": f"{getattr(device, 'asset_name', asset_id)} 的 {getattr(result, 'command_key', '检查项')} 未通过：{getattr(result, 'error', '') or '命令未成功'}",
                "confidence": "confirmed", "evidence_ref": ref, "status": "open",
            })
        for error in errors[:3]:
            ref = f"inspection:{task.task_id}:{asset_id}"
            evidence_refs.add(ref)
            hypotheses.append({
                "hypothesis_id": _id("hyp"), "statement": f"{getattr(device, 'asset_name', asset_id)} 采集异常：{error}",
                "confidence": "confirmed", "evidence_ref": ref, "status": "open",
            })
    if not hypotheses:
        hypotheses = [{
            "hypothesis_id": _id("hyp"), "statement": "本轮设备采集未发现失败检查项，需结合症状时间窗继续观察。",
            "confidence": "likely", "evidence_ref": f"inspection:{task.task_id}", "status": "monitoring",
        }]
        evidence_refs.add(f"inspection:{task.task_id}")
    from .llm_analysis import explain
    structured_changes = [item for item in changes if item.get("resource_type") not in {"", "device"}]
    llm_analysis = explain("incident_investigation", _llm_named_evidence(ws, structured_changes), str(incident.get("symptom", ""))) if structured_changes else {"status": "skipped", "error": "no_structured_anomaly"}
    incident.update(
        hypotheses=hypotheses[:20], evidence_refs=sorted(evidence_refs),
        affected_assets=sorted(affected), inspection_task_id=task.task_id,
        status="monitoring", severity="critical" if any(getattr(d, "status", "") == "failed" for d in (getattr(task, "devices", {}) or {}).values()) else "warning",
        conclusion=("已发现与状态基线不一致的结构化事实。" if changes
                    else "当前采集未复现可由结构化证据确认的故障。"),
        next_actions=(list(llm_analysis.get("next_actions") or []) or ["查看已确认的设备证据", "处理异常后重新发起调查验证"]),
        analysis={"baseline_id": (baseline or {}).get("baseline_id", ""),
                  "current_snapshot_id": current["snapshot_id"], "changes": changes[:100],
                  "llm": llm_analysis}, updated_at=now_iso(),
    )
    store.save(ws, "incidents", str(incident.get("incident_id", "")), incident)
    return {"incident_id": incident.get("incident_id"), "hypotheses": hypotheses[:20],
            "affected_assets": sorted(affected), "changes": changes[:100], "llm": llm_analysis}


def _finish_change_operation(ws: str, operation: dict[str, Any], task: Any) -> dict[str, Any]:
    change_id = str(operation.get("ref_id", ""))
    plan = store.get(ws, "changes", change_id)
    if plan is None:
        raise ValueError("change_not_found")
    snapshot = capture_snapshot(ws, task.task_id)
    if operation.get("kind") == "change_pre":
        baseline = next((item for item in list_baselines(ws)
                         if set(plan.get("asset_ids") or []).issubset(set((item.get("scope") or {}).get("asset_ids") or plan.get("asset_ids") or []))), None)
        reference = store.get(ws, "snapshots", str((baseline or {}).get("snapshot_id", ""))) if baseline else None
        deviations = compare_snapshots(reference, snapshot) if reference else []
        blockers = [item for item in deviations if item.get("severity") in {"critical", "warning"}]
        ready = task.status == "succeeded" and bool(reference) and not blockers
        plan.update(pre_snapshot_id=snapshot["snapshot_id"], status="ready_for_change" if ready else "blocked",
                    validation={"precheck_status": task.status, "precheck_task_id": task.task_id,
                                "baseline_id": (baseline or {}).get("baseline_id", ""),
                                "baseline_deviations": deviations[:100],
                                "blockers": blockers[:100] if reference else [{"reason": "baseline_required"}]},
                    updated_at=now_iso())
        result = {"snapshot_id": snapshot["snapshot_id"], "ready_for_change": ready,
                  "baseline_id": (baseline or {}).get("baseline_id", ""), "blockers": plan["validation"]["blockers"]}
    else:
        before = store.get(ws, "snapshots", str(plan.get("pre_snapshot_id", "")))
        if before is None:
            raise ValueError("change_precheck_required")
        changes = _snapshot_changes(before, snapshot)
        summary = {level: sum(1 for item in changes if item["severity"] == level) for level in ("critical", "warning", "info")}
        expected_contract = list(plan.get("expected_changes") or [])
        invariant_contract = list(plan.get("invariants") or [])
        def matches(change: dict[str, Any], contract: dict[str, Any]) -> bool:
            return fnmatch.fnmatchcase(str(change.get("key", "")), str(contract.get("key_pattern", "")))
        expected_results = [{**contract, "matched_changes": [item for item in changes if matches(item, contract)]}
                            for contract in expected_contract]
        invariant_violations = [{"contract": contract, "change": item} for contract in invariant_contract
                                for item in changes if matches(item, contract)]
        expected_ids = {id(item) for result in expected_results for item in result["matched_changes"]}
        unexpected = [item for item in changes if id(item) not in expected_ids]
        missing_expected = [item for item in expected_results if item.get("required") and not item.get("matched_changes")]
        passed = (task.status == "succeeded" and not invariant_violations and not missing_expected
                  and not any(item.get("severity") in {"critical", "warning"} for item in unexpected))
        from .llm_analysis import explain
        structured_changes = [item for item in changes if item.get("resource_type") not in {"", "device"}]
        llm_analysis = explain("change_verification", _llm_named_evidence(ws, structured_changes), str(plan.get("summary", ""))) if structured_changes else {"status": "skipped", "error": "no_structured_changes"}
        plan.update(
            post_snapshot_id=snapshot["snapshot_id"], status="verified" if passed else "rollback_required",
            validation={**dict(plan.get("validation") or {}), "postcheck_status": task.status,
                        "postcheck_task_id": task.task_id, "passed": passed, "summary": summary,
                        "changes": changes[:100], "expected_results": expected_results,
                        "invariant_violations": invariant_violations[:100], "unexpected_changes": unexpected[:100],
                        "missing_expected": missing_expected, "llm": llm_analysis,
                        "validated_at": now_iso()}, updated_at=now_iso(),
        )
        result = {"snapshot_id": snapshot["snapshot_id"], "passed": passed, "summary": summary,
                  "changes": changes[:100], "expected_results": expected_results,
                  "invariant_violations": invariant_violations[:100], "unexpected_changes": unexpected[:100],
                  "missing_expected": missing_expected, "llm": llm_analysis}
    store.save(ws, "changes", change_id, plan)
    return result


def refresh_assurance_operation(workspace_id: str, operation_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    with _OPERATION_LOCK:
        operation = store.get(ws, "operations", operation_id)
        if operation is None:
            raise ValueError("assurance_operation_not_found")
        if operation.get("status") != "collecting":
            return operation
        task = inspection_service.get_task(ws, str(operation.get("inspection_task_id", "")), record_poll=False)
        if task is None:
            operation.update(status="failed", phase="failed", error="inspection_task_missing", finished_at=now_iso())
        else:
            operation.update(_task_progress(task))
            operation["artifact_ids"] = _task_artifact_ids(task)
            if task.status in {"failed", "cancelled"}:
                operation.update(status=task.status, phase="failed", error=str(task.error or f"inspection_{task.status}"), finished_at=now_iso())
                kind, ref_id = str(operation.get("kind", "")), str(operation.get("ref_id", ""))
                if kind == "incident":
                    incident = store.get(ws, "incidents", ref_id) or {}
                    incident.update(status="monitoring", conclusion="设备证据采集失败，当前无法确认根因。",
                                    next_actions=["检查设备连接后重新发起调查"], updated_at=now_iso())
                    store.save(ws, "incidents", ref_id, incident)
                elif kind in {"change_pre", "change_post"}:
                    change = store.get(ws, "changes", ref_id) or {}
                    change.update(status="blocked", validation={**dict(change.get("validation") or {}),
                                  "error": operation["error"]}, updated_at=now_iso())
                    store.save(ws, "changes", ref_id, change)
            elif task.status in {"succeeded", "partial"}:
                kind = str(operation.get("kind", ""))
                if kind == "baseline_capture":
                    if task.status != "succeeded":
                        operation.update(
                            status="failed", phase="failed",
                            error="权威基线采集未完整成功，请查看失败设备后重新采集。",
                            finished_at=now_iso(), updated_at=now_iso(),
                        )
                    else:
                        try:
                            baseline = create_baseline(
                                ws, str((operation.get("result") or {}).get("baseline_name", "")),
                                operation.get("scope") or {}, task.task_id,
                            )
                            operation.update(
                                status="completed", phase="completed", error="",
                                result={"baseline": baseline}, finished_at=now_iso(), updated_at=now_iso(),
                            )
                        except (TypeError, ValueError) as exc:
                            message = "权威基线证据不完整，请检查本次巡检制品后重新采集。" if str(exc) == "complete_evidence_required_for_baseline" else str(exc)
                            operation.update(status="failed", phase="failed", error=message, finished_at=now_iso(), updated_at=now_iso())
                    return store.save(ws, "operations", operation_id, operation)
                operation["phase"] = "analyzing_evidence"
                if kind == "topology_refresh":
                    operation["result"] = {"topology": build_topology(ws, task.task_id)}
                elif kind == "fault_propagation":
                    topology = get_topology(ws)
                    pending_result = dict(operation.get("result") or {})
                    source_assets = list(pending_result.get("source_assets") or [])
                    validation = _source_validation(
                        ws, task.task_id, source_assets,
                        str(pending_result.get("source_mode", "hypothetical")),
                        str(operation.get("ref_id", "")),
                    )
                    propagation_result = fault_propagation_analysis(
                        ws,
                        source_assets,
                        int(pending_result.get("depth", 2) or 2),
                        str(operation.get("ref_id", "")),
                        validation,
                    )
                    llm_evidence = [
                        item for item in propagation_result.get("trigger_changes", [])
                        if item.get("resource_type") not in {"", "device"}
                    ]
                    llm_evidence.extend({
                        "key": f"fault_propagation.path.{index}",
                        "asset_id": item.get("asset_id", ""),
                        "before": (item.get("path") or [""])[0],
                        "after": item.get("asset_id", ""),
                        "severity": "warning" if (item.get("redundancy") or {}).get("status") == "single_dependency_observed" else "info",
                        "rationale": (
                            f"沿 {', '.join(item.get('via') or [])} 传播，第 {item.get('layer')} 层；"
                            f"冗余证据 {(item.get('redundancy') or {}).get('status', 'unknown')}"
                        ),
                        "evidence_ref": (item.get("evidence_refs") or [""])[0],
                    } for index, item in enumerate(propagation_result.get("propagation", []), start=1))
                    llm_evidence.extend({
                        "key": f"fault_propagation.resource.{index}",
                        "asset_id": item.get("asset_id", ""), "before": "reachable",
                        "after": f"{item.get('resource_type')}:{item.get('resource_id')}",
                        "severity": "info", "rationale": "传播候选设备上观测到的网络资源",
                        "evidence_ref": (item.get("evidence_refs") or [""])[0],
                    } for index, item in enumerate(propagation_result.get("affected_resources", [])[:50], start=1))
                    from .llm_analysis import explain
                    propagation_result["llm"] = explain(
                        "fault_propagation_analysis", _llm_named_evidence(ws, llm_evidence),
                        "基于已确认或明确标注为假设的故障源、有向依赖、资源和冗余证据，解释可能传播到哪里；不得把设备传播写成未映射的业务影响。",
                    ) if llm_evidence else {"status": "skipped", "error": "no_evidence_based_propagation"}
                    operation["result"] = {
                        "topology_id": topology["topology_id"],
                        **propagation_result,
                    }
                elif kind == "incident":
                    operation["result"] = _incident_result(ws, operation, task)
                else:
                    operation["result"] = _finish_change_operation(ws, operation, task)
                operation.update(status="completed", phase="completed", error="", finished_at=now_iso())
        operation["updated_at"] = now_iso()
        return store.save(ws, "operations", operation_id, operation)


def get_assurance_operation(workspace_id: str, operation_id: str) -> dict[str, Any]:
    return refresh_assurance_operation(workspace_id, operation_id)


def list_assurance_operations(workspace_id: str, kind: str = "") -> list[dict[str, Any]]:
    ws = _ws(workspace_id)
    rows = store.list_records(ws, "operations", limit=200)
    rows = [row for row in rows if not kind or row.get("kind") == kind]
    return [refresh_assurance_operation(ws, str(row.get("operation_id", ""))) if row.get("status") == "collecting" else row for row in rows]


def create_incident(workspace_id: str, title: str, symptom: str,
                    scope: dict[str, Any] | None = None, drift_id: str = "") -> dict[str, Any]:
    ws = _ws(workspace_id)
    if not str(title or "").strip() or not str(symptom or "").strip():
        raise ValueError("incident_title_and_symptom_required")
    drift = store.get(ws, "drifts", drift_id) if drift_id else None
    if drift_id and drift is None:
        raise ValueError("drift_not_found")
    changes = list((drift or {}).get("changes", []))
    affected = sorted({str(change.get("asset_id", "")) for change in changes if change.get("asset_id")})
    kind_labels = {"added": "新增", "removed": "消失", "changed": "变化"}
    hypotheses = [{
        "hypothesis_id": f"hyp_{index + 1}",
        "statement": f"检测到 {change.get('key')} 出现{kind_labels.get(str(change.get('kind')), '变化')}",
        "confidence": "confirmed" if change.get("severity") == "critical" else "likely",
        "evidence_ref": change.get("evidence_ref", ""),
        "status": "open",
    } for index, change in enumerate(changes[:10])]
    if not hypotheses:
        hypotheses.append({"hypothesis_id": "hyp_1", "statement": "原因尚未确认，需要采集当前设备状态进行验证", "confidence": "unverified", "evidence_ref": "", "status": "open"})
    incident = IncidentRecord(
        incident_id=_id("inc"), workspace_id=ws, title=str(title).strip()[:160],
        symptom=str(symptom).strip()[:2000], scope=_scope_dict(scope), drift_id=drift_id,
        hypotheses=hypotheses, affected_assets=affected,
        evidence_refs=sorted({str(item.get("evidence_ref", "")) for item in hypotheses if item.get("evidence_ref")}),
        next_actions=["采集或选择一次已完成的设备巡检", "使用当前设备证据逐项验证排查假设"],
    )
    saved = store.save(ws, "incidents", incident.incident_id, incident)
    operation = start_assurance_operation(
        ws, "incident", ref_id=incident.incident_id,
        asset_ids=affected, scope=incident.scope,
    )
    return store.get(ws, "incidents", incident.incident_id) or {
        **saved, "operation_id": operation["operation_id"],
        "inspection_task_id": operation["inspection_task_id"],
    }


def list_incidents(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "incidents", limit=200)


def update_incident(workspace_id: str, incident_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ws = _ws(workspace_id); item = store.get(ws, "incidents", incident_id)
    if item is None: raise ValueError("incident_not_found")
    status = str(updates.get("status", "") or "")
    severity = str(updates.get("severity", "") or "")
    if status and status not in {"investigating", "monitoring", "resolved", "closed"}:
        raise ValueError("invalid_incident_status")
    if severity and severity not in {"info", "warning", "critical"}:
        raise ValueError("invalid_incident_severity")
    if "next_actions" in updates:
        actions = updates["next_actions"]
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            raise TypeError("incident_next_actions_must_be_string_array")
        item["next_actions"] = [action.strip()[:500] for action in actions if action.strip()][:20]
    if "hypotheses" in updates:
        hypotheses = updates["hypotheses"]
        if not isinstance(hypotheses, list) or not all(isinstance(entry, dict) for entry in hypotheses):
            raise TypeError("incident_hypotheses_must_be_array")
        known_evidence = set(str(ref) for ref in item.get("evidence_refs", []) if ref)
        normalized: list[dict[str, Any]] = []
        for index, entry in enumerate(hypotheses[:20]):
            statement = str(entry.get("statement", "")).strip()
            confidence = str(entry.get("confidence", "unverified"))
            evidence_ref = str(entry.get("evidence_ref", "")).strip()
            if not statement:
                raise ValueError("incident_hypothesis_statement_required")
            if confidence not in {"unverified", "likely", "confirmed"}:
                raise ValueError("invalid_hypothesis_confidence")
            if confidence == "confirmed" and evidence_ref not in known_evidence:
                raise ValueError("confirmed_hypothesis_requires_known_evidence")
            normalized.append({
                "hypothesis_id": str(entry.get("hypothesis_id", "") or f"hyp_{index + 1}"),
                "statement": statement[:1000], "confidence": confidence,
                "evidence_ref": evidence_ref, "status": str(entry.get("status", "open"))[:40],
            })
        item["hypotheses"] = normalized
    if status: item["status"] = status
    if severity: item["severity"] = severity
    if "conclusion" in updates: item["conclusion"] = str(updates["conclusion"] or "").strip()[:4000]
    item["updated_at"] = now_iso()
    return store.save(ws, "incidents", incident_id, item)


def _change_contract(items: Any, field: str) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{field}_must_be_array")
    result: list[dict[str, Any]] = []
    for item in items[:100]:
        pattern = str(item.get("key_pattern", "") or "").strip()
        if not pattern:
            raise ValueError(f"{field}_key_pattern_required")
        result.append({
            "key_pattern": pattern[:500], "description": str(item.get("description", ""))[:500],
            "required": bool(item.get("required", field == "invariants")),
        })
    return result


def create_change_plan(workspace_id: str, title: str, summary: str, asset_ids: list[str],
                       expected_changes: Any = None, invariants: Any = None) -> dict[str, Any]:
    ws = _ws(workspace_id)
    if not isinstance(asset_ids, list):
        raise TypeError("asset_ids_must_be_array")
    targets = list(dict.fromkeys(str(item).strip() for item in asset_ids if str(item).strip()))
    if not str(title or "").strip() or not str(summary or "").strip() or not targets:
        raise ValueError("change_title_summary_and_assets_required")
    plan = ChangePlan(
        change_id=_id("chg"), workspace_id=ws, title=str(title).strip()[:160],
        summary=str(summary).strip()[:2000], asset_ids=targets,
        prechecks=["确认 CMDB 中的目标设备身份", "保存变更前的设备状态", "确认设备管理连接正常"],
        postchecks=["使用相同范围重新巡检", "与变更前状态进行比较", "确认相关邻接与路由正常"],
        rollback_conditions=["目标设备无法连接", "关键邻接或路由消失", "变更后出现严重状态偏差"],
        expected_changes=_change_contract(expected_changes, "expected_changes"),
        invariants=_change_contract(invariants, "invariants"),
    )
    return store.save(ws, "changes", plan.change_id, plan)


def list_change_plans(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "changes", limit=200)


def validate_change_plan(workspace_id: str, change_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id); plan = store.get(ws, "changes", change_id)
    if plan is None: raise ValueError("change_not_found")
    assets = {item.get("asset_id"): item for item in cmdb_service.list_assets(ws)}
    missing = [item for item in plan.get("asset_ids", []) if item not in assets]
    impact = fault_propagation_analysis(
        ws, list(plan.get("asset_ids", [])),
        source_validation={"mode": "hypothetical", "status": "hypothetical", "changes": []},
    )
    blockers = [f"CMDB asset not found: {item}" for item in missing]
    plan["impact"] = impact
    warnings: list[str] = []
    if impact.get("confidence") != "evidence_based":
        warnings.append("Topology impact is unverified")
    if not list_baselines(ws):
        warnings.append("No assurance baseline exists for pre/post comparison")
    plan["validation"] = {
        "valid": not blockers, "blockers": blockers,
        "warnings": warnings,
        "validated_at": now_iso(),
    }
    plan["status"] = "validated" if not blockers else "blocked"
    plan["updated_at"] = now_iso()
    return store.save(ws, "changes", change_id, plan)


def start_change_precheck(workspace_id: str, change_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    validate_change_plan(ws, change_id)
    operation = start_assurance_operation(ws, "change_pre", ref_id=change_id)
    return {"change": store.get(ws, "changes", change_id), "operation": operation}


def start_change_postcheck(workspace_id: str, change_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    plan = store.get(ws, "changes", change_id)
    if plan is None:
        raise ValueError("change_not_found")
    if not plan.get("pre_snapshot_id"):
        raise ValueError("change_precheck_required")
    operation = start_assurance_operation(ws, "change_post", ref_id=change_id)
    return {"change": store.get(ws, "changes", change_id), "operation": operation}


def update_change_plan(workspace_id: str, change_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ws = _ws(workspace_id); plan = store.get(ws, "changes", change_id)
    if plan is None: raise ValueError("change_not_found")
    status = str(updates.get("status", "") or "")
    if status and status not in {"draft", "rejected"}:
        raise ValueError("invalid_change_status")
    if status: plan["status"] = status
    plan["updated_at"] = now_iso()
    return store.save(ws, "changes", change_id, plan)


def _next_run(interval_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat()


def create_schedule(workspace_id: str, name: str, baseline_id: str, interval_minutes: int,
                    scope: dict[str, Any] | None = None, confirm_after: int = 2,
                    recover_after: int = 2) -> dict[str, Any]:
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None: raise ValueError("baseline_not_found")
    interval = max(5, min(int(interval_minutes or 60), 43200))
    schedule = AssuranceSchedule(
        schedule_id=_id("sched"), workspace_id=ws, name=str(name or "持续保障").strip()[:120],
        baseline_id=baseline_id, scope=_scope_dict(scope or baseline.get("scope")), interval_minutes=interval,
        next_run_at=_next_run(interval), confirm_after=max(1, min(int(confirm_after or 2), 10)),
        recover_after=max(1, min(int(recover_after or 2), 10)),
    )
    return store.save(ws, "schedules", schedule.schedule_id, schedule)


def list_schedules(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "schedules", limit=200)


def list_alarms(workspace_id: str, state: str = "") -> list[dict[str, Any]]:
    rows = store.list_records(_ws(workspace_id), "alarms", limit=500)
    return [item for item in rows if not state or item.get("state") == state]


def _update_schedule_alarms(ws: str, schedule: dict[str, Any], drift: dict[str, Any]) -> int:
    current = {f"{item.get('asset_id')}|{item.get('key')}": item for item in drift.get("changes", [])
               if item.get("severity") in {"critical", "warning"}}
    existing = {str(item.get("fingerprint", "")): item for item in list_alarms(ws)
                if item.get("schedule_id") == schedule.get("schedule_id") and item.get("state") != "resolved"}
    confirm_after = max(1, int(schedule.get("confirm_after", 2) or 2))
    recover_after = max(1, int(schedule.get("recover_after", 2) or 2))
    for fingerprint, change in current.items():
        alarm = existing.get(fingerprint)
        if alarm is None:
            alarm = asdict(AssuranceAlarm(
                alarm_id=_id("alarm"), workspace_id=ws, schedule_id=str(schedule.get("schedule_id", "")),
                baseline_id=str(schedule.get("baseline_id", "")), fingerprint=fingerprint,
                asset_id=str(change.get("asset_id", "")), fact_key=str(change.get("key", "")),
                severity=str(change.get("severity", "warning")),
            ))
        alarm["consecutive_hits"] = int(alarm.get("consecutive_hits", 0) or 0) + 1
        alarm["consecutive_clears"] = 0
        alarm["state"] = "open" if alarm["consecutive_hits"] >= confirm_after else "pending"
        alarm["last_seen_at"] = now_iso(); alarm["latest_change"] = change
        ref = str(change.get("evidence_ref", ""))
        alarm["evidence_refs"] = list(dict.fromkeys([*(alarm.get("evidence_refs") or []), *([ref] if ref else [])]))[-20:]
        store.save(ws, "alarms", str(alarm["alarm_id"]), alarm)
    for fingerprint, alarm in existing.items():
        if fingerprint in current:
            continue
        alarm["consecutive_clears"] = int(alarm.get("consecutive_clears", 0) or 0) + 1
        if alarm["consecutive_clears"] >= recover_after:
            alarm["state"] = "resolved"; alarm["resolved_at"] = now_iso()
        store.save(ws, "alarms", str(alarm["alarm_id"]), alarm)
    return sum(1 for item in list_alarms(ws, "open") if item.get("schedule_id") == schedule.get("schedule_id"))


def update_schedule(workspace_id: str, schedule_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ws = _ws(workspace_id); item = store.get(ws, "schedules", schedule_id)
    if item is None: raise ValueError("schedule_not_found")
    if "enabled" in updates:
        if not isinstance(updates["enabled"], bool):
            raise TypeError("schedule_enabled_must_be_boolean")
        item["enabled"] = updates["enabled"]
    if "interval_minutes" in updates:
        item["interval_minutes"] = max(5, min(int(updates["interval_minutes"]), 43200))
        item["next_run_at"] = _next_run(item["interval_minutes"])
    for field in ("confirm_after", "recover_after"):
        if field in updates:
            item[field] = max(1, min(int(updates[field]), 10))
    item["updated_at"] = now_iso()
    return store.save(ws, "schedules", schedule_id, item)


def _parse_dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _fail_schedule(ws: str, item: dict[str, Any], error: str) -> None:
    try:
        interval = max(5, min(int(item.get("interval_minutes", 60)), 43200))
    except (TypeError, ValueError):
        interval = 60
    item["state"] = "idle"
    item["error"] = error
    item["last_status"] = "failed"
    item["run_count"] = int(item.get("run_count", 0) or 0) + 1
    item["consecutive_failures"] = int(item.get("consecutive_failures", 0) or 0) + 1
    item["last_run_at"] = now_iso()
    item["next_run_at"] = _next_run(interval)
    item["updated_at"] = now_iso()
    store.save(ws, "schedules", str(item.get("schedule_id", "")), item)


def _run_schedule(ws: str, item: dict[str, Any]) -> None:
    schedule_id = str(item.get("schedule_id", ""))
    task_id = str(item.get("last_task_id", ""))
    if item.get("state") == "collecting" and task_id:
        task = inspection_service.get_task(ws, task_id, record_poll=False)
        if task is None:
            _fail_schedule(ws, item, "inspection_task_missing")
            return
        if task.status not in _TERMINAL:
            return
        if task.status in {"succeeded", "partial"}:
            drift = check_baseline(ws, str(item.get("baseline_id", "")), task_id)
            item["last_drift_id"] = drift["drift_id"]
            item["last_artifact_ids"] = _task_artifact_ids(task)
            item["error"] = ""
            item["last_status"] = str(drift.get("status", ""))
            item["open_alarm_count"] = _update_schedule_alarms(ws, item, drift)
            alarm_evidence = [
                change for change in drift.get("changes", [])
                if change.get("severity") in {"critical", "warning"}
                and change.get("resource_type") not in {"", "device"}
            ]
            if item["open_alarm_count"] and alarm_evidence:
                from .llm_analysis import explain
                item["last_analysis"] = explain(
                    "continuous_assurance", _llm_named_evidence(ws, alarm_evidence),
                    f"持续检查已打开 {item['open_alarm_count']} 条告警，请归纳异常关联和处置优先级。",
                )
            else:
                item["last_analysis"] = {"status": "skipped", "error": "no_confirmed_open_alarm"}
            item["consecutive_failures"] = 0 if task.status == "succeeded" else int(item.get("consecutive_failures", 0) or 0) + 1
        else:
            item["error"] = f"inspection_{task.status}"
            item["last_status"] = str(task.status)
            item["consecutive_failures"] = int(item.get("consecutive_failures", 0) or 0) + 1
        item["run_count"] = int(item.get("run_count", 0) or 0) + 1
        item["state"] = "idle"; item["last_run_at"] = now_iso()
        item["next_run_at"] = _next_run(int(item.get("interval_minutes", 60)))
        item["updated_at"] = now_iso(); store.save(ws, "schedules", schedule_id, item)
        return
    due = _parse_dt(str(item.get("next_run_at", "")))
    if due and due > datetime.now(timezone.utc): return
    task = inspection_service.start_background_task(
        workspace_id=ws, profile_id="general", scope=item.get("scope") or {},
        created_by=f"assurance:schedule:{schedule_id}", max_concurrency=3,
    )
    item["last_task_id"] = task.task_id; item["state"] = "collecting"
    item["error"] = task.error; item["updated_at"] = now_iso()
    store.save(ws, "schedules", schedule_id, item)


def run_schedule_now(workspace_id: str, schedule_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    item = store.get(ws, "schedules", schedule_id)
    if item is None:
        raise ValueError("schedule_not_found")
    if item.get("state") == "collecting":
        _run_schedule(ws, item)
        return store.get(ws, "schedules", schedule_id) or item
    item["next_run_at"] = now_iso()
    store.save(ws, "schedules", schedule_id, item)
    _run_schedule(ws, item)
    return store.get(ws, "schedules", schedule_id) or item


def run_due_schedules() -> None:
    for ws in list_workspace_ids():
        try:
            # Prevent two backend workers from claiming the same due schedule.
            # The critical section is short: inspection starts asynchronously.
            with IndexLock(ws, timeout=2.0):
                for item in list_schedules(ws):
                    if item.get("enabled") or item.get("state") == "collecting":
                        try:
                            _run_schedule(ws, item)
                        except Exception:
                            _LOG.exception(
                                "assurance schedule failed: workspace=%s schedule=%s",
                                ws, item.get("schedule_id", ""),
                            )
                            _fail_schedule(ws, item, "assurance_schedule_failed")
        except Exception:
            _LOG.exception("assurance schedule scan failed for workspace %s", ws)
            continue


def refresh_active_checks() -> None:
    for ws in list_workspace_ids():
        for item in store.list_records(ws, "checks", limit=100):
            if item.get("status") != "collecting":
                continue
            try:
                refresh_baseline_check(ws, str(item.get("check_id", "")))
            except Exception:
                _LOG.exception(
                    "assurance check refresh failed: workspace=%s check=%s",
                    ws, item.get("check_id", ""),
                )


def refresh_active_operations() -> None:
    for ws in list_workspace_ids():
        for item in store.list_records(ws, "operations", limit=200):
            if item.get("status") != "collecting":
                continue
            try:
                refresh_assurance_operation(ws, str(item.get("operation_id", "")))
            except Exception:
                _LOG.exception("assurance operation refresh failed: workspace=%s operation=%s", ws, item.get("operation_id", ""))


def start_scheduler(poll_seconds: int = 15) -> None:
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED: return
        _SCHEDULER_STARTED = True
    def loop() -> None:
        while True:
            try:
                run_due_schedules()
                refresh_active_operations()
            except Exception:
                _LOG.exception("assurance scheduler iteration failed")
            time.sleep(max(5, poll_seconds))
    threading.Thread(target=loop, name="assurance-scheduler", daemon=True).start()


def get_overview(workspace_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    baselines = list_baselines(ws); drifts = list_drifts(ws); incidents = list_incidents(ws)
    changes = list_change_plans(ws); schedules = list_schedules(ws)
    alarms = list_alarms(ws)
    operations = list_assurance_operations(ws)
    topology = get_topology(ws)
    latest = drifts[0] if drifts else None
    open_incidents = sum(1 for item in incidents if item.get("status") not in {"resolved", "closed"})
    schedule_errors = sum(1 for item in schedules if item.get("error"))
    blocked_changes = sum(1 for item in changes if item.get("status") == "blocked")
    needs_attention = bool(
        open_incidents or schedule_errors or blocked_changes
        or any(item.get("state") == "open" for item in alarms)
    )
    return {
        "workspace_id": ws,
        "counts": {
            "baselines": len(baselines), "drifts": len(drifts),
            "active_operations": sum(1 for item in operations if item.get("status") == "collecting"),
            "open_incidents": open_incidents,
            "change_plans": len(changes), "enabled_schedules": sum(1 for item in schedules if item.get("enabled")),
            "schedule_errors": schedule_errors, "blocked_changes": blocked_changes,
            "open_alarms": sum(1 for item in alarms if item.get("state") == "open"),
            "topology_nodes": len(topology.get("nodes", [])), "topology_edges": len(topology.get("edges", [])),
            "topology_evidence_claims": len(topology.get("evidence_claims", [])),
        },
        "latest_drift": latest,
        "health": "attention" if needs_attention else "stable",
    }


def get_snapshot(workspace_id: str) -> dict[str, Any]:
    """Return the complete assurance read model in one consistent response."""
    ws = _ws(workspace_id)
    return {
        "workspace_id": ws,
        "overview": get_overview(ws),
        "baselines": list_baselines(ws),
        "drifts": list_drifts(ws),
        "topology": get_topology(ws),
        "incidents": list_incidents(ws),
        "changes": list_change_plans(ws),
        "schedules": list_schedules(ws),
        "alarms": list_alarms(ws),
        "operations": list_assurance_operations(ws),
        "generated_at": now_iso(),
    }


def clear_assurance_records(workspace_id: str, *, confirm: bool = False) -> dict[str, Any]:
    """Reset the assurance read model without deleting source evidence."""
    ws = _ws(workspace_id)
    if confirm is not True:
        raise ValueError("confirm_required")
    active_operations = [item for item in list_assurance_operations(ws) if item.get("status") == "collecting"]
    if active_operations:
        raise ValueError("assurance_records_not_ready_active_tasks")
    removed = store.clear_all(ws)
    return {
        "workspace_id": ws,
        "deleted": sum(removed.values()),
        "deleted_by_kind": removed,
        "preserved": ["cmdb_assets", "inspection_tasks", "artifacts", "sessions", "reports"],
    }
