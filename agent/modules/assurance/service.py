"""Network Assurance service.

The service composes existing CMDB and inspection evidence. It never stores
credentials or raw device output and never deploys configuration.
"""

from __future__ import annotations

import hashlib
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
from agent.runtime.utils import now_iso
from storage.index import IndexLock
from storage.paths import get_workspace_root
from workspace.ids import validate_workspace_id

from . import store
from .models import (
    AssuranceBaseline,
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
        for key, value in _flatten(f"{base}.metric", getattr(device, "parsed_metrics", {}) or {}):
            facts.append(asdict(NormalizedFact(
                key=key, value=value, asset_id=asset_id, category="metric",
                evidence_ref=evidence, observed_at=observed_at,
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
                )))
    return facts


def capture_snapshot(workspace_id: str, inspection_task_id: str = "", scope: dict[str, Any] | None = None) -> dict[str, Any]:
    ws = _ws(workspace_id)
    task = _resolve_task(ws, inspection_task_id, scope)
    snapshot = StateSnapshot(
        snapshot_id=_id("snap"), workspace_id=ws, scope=_task_scope(task),
        inspection_task_id=task.task_id, source_status=str(task.status), facts=_facts_from_task(task),
        asset_count=len(getattr(task, "devices", {}) or {}),
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
    baseline = AssuranceBaseline(
        baseline_id=_id("base"), workspace_id=ws, name=str(name).strip()[:120],
        scope=snapshot["scope"], snapshot_id=snapshot["snapshot_id"],
        source_task_id=snapshot["inspection_task_id"], fact_count=len(snapshot["facts"]),
    )
    return store.save(ws, "baselines", baseline.baseline_id, baseline)


def list_baselines(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "baselines")


def start_baseline_check(workspace_id: str, baseline_id: str) -> dict[str, Any]:
    """Start a fresh inspection for a baseline instead of reusing old evidence."""
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None:
        raise ValueError("baseline_not_found")
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


def refresh_baseline_check(workspace_id: str, check_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    with _CHECK_LOCK:
        check = store.get(ws, "checks", check_id)
        if check is None:
            raise ValueError("baseline_check_not_found")
        if check.get("status") != "collecting":
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
                check.update(
                    status=task_status,
                    error=str(task.error or f"inspection_{task_status}"),
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
        if row.get("status") == "collecting" else row
        for row in rows
    ]


def _change_severity(key: str, kind: str) -> str:
    if key.endswith(".status") or kind in {"added", "removed"}:
        return "critical" if kind == "changed" else "warning"
    if key.endswith(".ok") or ".metric." in key:
        return "warning"
    return "info"


def check_baseline(workspace_id: str, baseline_id: str, inspection_task_id: str = "") -> dict[str, Any]:
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None:
        raise ValueError("baseline_not_found")
    reference = store.get(ws, "snapshots", str(baseline.get("snapshot_id", "")))
    if reference is None:
        raise ValueError("baseline_snapshot_not_found")
    current = capture_snapshot(ws, inspection_task_id, baseline.get("scope") or {})
    before = {item["key"]: item for item in reference.get("facts", [])}
    after = {item["key"]: item for item in current.get("facts", [])}
    changes: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old is None:
            kind = "added"
        elif new is None and current.get("source_status") != "partial":
            kind = "removed"
        elif new is None:
            continue
        elif old.get("value") != new.get("value"):
            kind = "changed"
        else:
            continue
        changes.append({
            "key": key, "kind": kind,
            "asset_id": (new or old or {}).get("asset_id", ""),
            "before": old.get("value") if old else None,
            "after": new.get("value") if new else None,
            "severity": _change_severity(key, kind),
            "evidence_ref": (new or old or {}).get("evidence_ref", ""),
        })
    summary = {level: sum(1 for change in changes if change["severity"] == level) for level in ("critical", "warning", "info")}
    meaningful_change = bool(summary["critical"] or summary["warning"])
    drift = DriftRecord(
        drift_id=_id("drift"), workspace_id=ws, baseline_id=baseline_id,
        snapshot_id=current["snapshot_id"], source_task_id=current["inspection_task_id"],
        status=("partial" if current.get("source_status") == "partial" else "drifted" if meaningful_change else "compliant"),
        changes=changes, summary=summary,
        incomplete=current.get("source_status") == "partial",
    )
    return store.save(ws, "drifts", drift.drift_id, drift)


def list_drifts(workspace_id: str, baseline_id: str = "") -> list[dict[str, Any]]:
    rows = store.list_records(_ws(workspace_id), "drifts", limit=200)
    return [row for row in rows if not baseline_id or row.get("baseline_id") == baseline_id]


def _inspection_text(task: Any, asset_id: str) -> str:
    device = (getattr(task, "devices", {}) or {}).get(asset_id)
    if device is None:
        return ""
    return "\n".join(str(getattr(result, "output_snippet", "") or "") for result in (getattr(device, "command_results", []) or []))


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
    } for item in assets]
    by_id = {node["asset_id"]: node for node in nodes if node["asset_id"]}
    edges: dict[str, dict[str, Any]] = {}
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
    if task is not None:
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
                    edges.setdefault(key, {"edge_id": key, "source": source, "target": target, "type": "observed_neighbor", "confidence": "observed", "evidence_ref": f"inspection:{task.task_id}"})
    topology = TopologySnapshot(
        topology_id=_id("topo"), workspace_id=ws, nodes=nodes,
        edges=list(edges.values()), source_task_id=getattr(task, "task_id", "") if task else "",
    )
    saved = store.save(ws, "topologies", topology.topology_id, topology)
    store.prune(ws, "topologies", "topology_id", keep=20)
    return saved


def get_topology(workspace_id: str) -> dict[str, Any]:
    rows = store.list_records(_ws(workspace_id), "topologies", limit=1)
    return rows[0] if rows else build_topology(workspace_id)


def impact_analysis(workspace_id: str, asset_ids: list[str], depth: int = 2) -> dict[str, Any]:
    if not isinstance(asset_ids, list):
        raise TypeError("asset_ids_must_be_array")
    topology = get_topology(workspace_id)
    depth = max(1, min(int(depth or 2), 6))
    adjacency: dict[str, set[str]] = {}
    for edge in topology.get("edges", []):
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    starts = list(dict.fromkeys(str(item).strip() for item in asset_ids if str(item).strip()))
    nodes = {str(item.get("asset_id", "")): item for item in topology.get("nodes", [])}
    if not starts:
        raise ValueError("impact_asset_required")
    missing = [item for item in starts if item not in nodes]
    if missing:
        raise ValueError(f"impact_asset_not_found:{','.join(missing)}")
    seen = set(starts)
    frontier = set(starts)
    layers: list[list[str]] = []
    for _ in range(depth):
        next_layer = {neighbor for node in frontier for neighbor in adjacency.get(node, set()) if neighbor not in seen}
        if not next_layer:
            break
        layers.append(sorted(next_layer)); seen.update(next_layer); frontier = next_layer
    return {
        "source_assets": starts,
        "affected_assets": [nodes[item] for item in sorted(seen - set(starts)) if item in nodes],
        "layers": layers,
        "edge_count": len(topology.get("edges", [])),
        "confidence": "evidence_based" if topology.get("edges") else "unverified",
    }


_OPERATION_KINDS = {"topology_refresh", "impact", "incident", "change_pre", "change_post"}


def _operation_scope(ws: str, kind: str, ref_id: str, asset_ids: list[str],
                     scope: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    selected = list(dict.fromkeys(str(item).strip() for item in asset_ids if str(item).strip()))
    if kind == "incident":
        incident = store.get(ws, "incidents", ref_id)
        if incident is None:
            raise ValueError("incident_not_found")
        selected = selected or list(incident.get("affected_assets") or [])
        scope = scope or incident.get("scope") or {}
    elif kind in {"change_pre", "change_post"}:
        change = store.get(ws, "changes", ref_id)
        if change is None:
            raise ValueError("change_not_found")
        selected = list(change.get("asset_ids") or [])
    elif kind == "impact" and not selected:
        raise ValueError("impact_asset_required")
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
                              depth: int = 2) -> dict[str, Any]:
    ws = _ws(workspace_id)
    kind = str(kind or "").strip()
    if kind not in _OPERATION_KINDS:
        raise ValueError("invalid_assurance_operation_kind")
    if asset_ids is not None and not isinstance(asset_ids, list):
        raise TypeError("asset_ids_must_be_array")
    resolved_scope, selected = _operation_scope(ws, kind, ref_id, asset_ids or [], scope)
    impact_depth = max(1, min(int(depth), 5))
    for row in store.list_records(ws, "operations", limit=200):
        same_request = row.get("kind") == kind and row.get("ref_id") == ref_id
        if kind == "impact":
            existing_result = dict(row.get("result") or {})
            same_request = same_request and (
                list(existing_result.get("source_assets") or []) == selected
                and int(existing_result.get("depth", 2) or 2) == impact_depth
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
        result=({"source_assets": selected, "depth": impact_depth} if kind == "impact"
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
    old_facts = {item["key"]: item for item in before.get("facts", [])}
    new_facts = {item["key"]: item for item in after.get("facts", [])}
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old_facts) | set(new_facts)):
        old, new = old_facts.get(key), new_facts.get(key)
        if old is None:
            kind = "added"
        elif new is None and after.get("source_status") != "partial":
            kind = "removed"
        elif new is None:
            continue
        elif old.get("value") != new.get("value"):
            kind = "changed"
        else:
            continue
        changes.append({
            "key": key, "kind": kind, "asset_id": (new or old or {}).get("asset_id", ""),
            "before": old.get("value") if old else None,
            "after": new.get("value") if new else None,
            "severity": _change_severity(key, kind),
            "evidence_ref": (new or old or {}).get("evidence_ref", ""),
        })
    return changes


def _incident_result(ws: str, operation: dict[str, Any], task: Any) -> dict[str, Any]:
    incident = store.get(ws, "incidents", str(operation.get("ref_id", ""))) or {}
    hypotheses: list[dict[str, Any]] = []
    evidence_refs: set[str] = set()
    affected: set[str] = set(incident.get("affected_assets") or [])
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
    incident.update(
        hypotheses=hypotheses[:20], evidence_refs=sorted(evidence_refs),
        affected_assets=sorted(affected), inspection_task_id=task.task_id,
        status="monitoring", severity="critical" if any(getattr(d, "status", "") == "failed" for d in (getattr(task, "devices", {}) or {}).values()) else "warning",
        conclusion=("采集发现需要处理的失败检查项。" if any(h["confidence"] == "confirmed" for h in hypotheses) else "当前采集未复现明确故障。"),
        next_actions=["查看已确认的设备证据", "处理异常后重新发起调查验证"], updated_at=now_iso(),
    )
    store.save(ws, "incidents", str(incident.get("incident_id", "")), incident)
    return {"incident_id": incident.get("incident_id"), "hypotheses": hypotheses[:20], "affected_assets": sorted(affected)}


def _finish_change_operation(ws: str, operation: dict[str, Any], task: Any) -> dict[str, Any]:
    change_id = str(operation.get("ref_id", ""))
    plan = store.get(ws, "changes", change_id)
    if plan is None:
        raise ValueError("change_not_found")
    snapshot = capture_snapshot(ws, task.task_id)
    if operation.get("kind") == "change_pre":
        ready = task.status == "succeeded"
        plan.update(pre_snapshot_id=snapshot["snapshot_id"], status="ready_for_change" if ready else "blocked",
                    validation={"precheck_status": task.status, "precheck_task_id": task.task_id}, updated_at=now_iso())
        result = {"snapshot_id": snapshot["snapshot_id"], "ready_for_change": ready}
    else:
        before = store.get(ws, "snapshots", str(plan.get("pre_snapshot_id", "")))
        if before is None:
            raise ValueError("change_precheck_required")
        changes = _snapshot_changes(before, snapshot)
        summary = {level: sum(1 for item in changes if item["severity"] == level) for level in ("critical", "warning", "info")}
        passed = task.status == "succeeded" and not summary["critical"] and not summary["warning"]
        plan.update(
            post_snapshot_id=snapshot["snapshot_id"], status="verified" if passed else "rollback_required",
            validation={**dict(plan.get("validation") or {}), "postcheck_status": task.status,
                        "postcheck_task_id": task.task_id, "passed": passed, "summary": summary,
                        "changes": changes[:100], "validated_at": now_iso()}, updated_at=now_iso(),
        )
        result = {"snapshot_id": snapshot["snapshot_id"], "passed": passed, "summary": summary, "changes": changes[:100]}
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
                operation["phase"] = "analyzing_evidence"
                kind = str(operation.get("kind", ""))
                if kind == "topology_refresh":
                    operation["result"] = {"topology": build_topology(ws, task.task_id)}
                elif kind == "impact":
                    topology = build_topology(ws, task.task_id)
                    pending_result = dict(operation.get("result") or {})
                    operation["result"] = {
                        "topology_id": topology["topology_id"],
                        **impact_analysis(
                            ws,
                            list(pending_result.get("source_assets") or []),
                            int(pending_result.get("depth", 2) or 2),
                        ),
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


def create_change_plan(workspace_id: str, title: str, summary: str, asset_ids: list[str]) -> dict[str, Any]:
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
    )
    return store.save(ws, "changes", plan.change_id, plan)


def list_change_plans(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "changes", limit=200)


def validate_change_plan(workspace_id: str, change_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id); plan = store.get(ws, "changes", change_id)
    if plan is None: raise ValueError("change_not_found")
    assets = {item.get("asset_id"): item for item in cmdb_service.list_assets(ws)}
    missing = [item for item in plan.get("asset_ids", []) if item not in assets]
    impact = impact_analysis(ws, list(plan.get("asset_ids", [])))
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
                    scope: dict[str, Any] | None = None) -> dict[str, Any]:
    ws = _ws(workspace_id)
    baseline = store.get(ws, "baselines", baseline_id)
    if baseline is None: raise ValueError("baseline_not_found")
    interval = max(5, min(int(interval_minutes or 60), 43200))
    schedule = AssuranceSchedule(
        schedule_id=_id("sched"), workspace_id=ws, name=str(name or "持续保障").strip()[:120],
        baseline_id=baseline_id, scope=_scope_dict(scope or baseline.get("scope")), interval_minutes=interval,
        next_run_at=_next_run(interval),
    )
    return store.save(ws, "schedules", schedule.schedule_id, schedule)


def list_schedules(workspace_id: str) -> list[dict[str, Any]]:
    return store.list_records(_ws(workspace_id), "schedules", limit=200)


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
    root = get_workspace_root()
    if not root.is_dir(): return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            ws = _ws(path.name)
        except (TypeError, ValueError):
            continue
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
    root = get_workspace_root()
    if not root.is_dir():
        return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            ws = _ws(path.name)
        except (TypeError, ValueError):
            continue
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
    root = get_workspace_root()
    if not root.is_dir():
        return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            ws = _ws(path.name)
        except (TypeError, ValueError):
            continue
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
                refresh_active_checks()
                refresh_active_operations()
            except Exception:
                _LOG.exception("assurance scheduler iteration failed")
            time.sleep(max(5, poll_seconds))
    threading.Thread(target=loop, name="assurance-scheduler", daemon=True).start()


def get_overview(workspace_id: str) -> dict[str, Any]:
    ws = _ws(workspace_id)
    baselines = list_baselines(ws); drifts = list_drifts(ws); incidents = list_incidents(ws)
    changes = list_change_plans(ws); schedules = list_schedules(ws)
    checks = list_baseline_checks(ws); operations = list_assurance_operations(ws)
    topology = get_topology(ws)
    latest = drifts[0] if drifts else None
    open_incidents = sum(1 for item in incidents if item.get("status") not in {"resolved", "closed"})
    schedule_errors = sum(1 for item in schedules if item.get("error"))
    blocked_changes = sum(1 for item in changes if item.get("status") == "blocked")
    needs_attention = bool(
        (latest and latest.get("status") in {"drifted", "partial"})
        or open_incidents or schedule_errors or blocked_changes
    )
    return {
        "workspace_id": ws,
        "counts": {
            "baselines": len(baselines), "drifts": len(drifts),
            "active_checks": sum(1 for item in checks if item.get("status") == "collecting"),
            "active_operations": sum(1 for item in operations if item.get("status") == "collecting"),
            "open_incidents": open_incidents,
            "change_plans": len(changes), "enabled_schedules": sum(1 for item in schedules if item.get("enabled")),
            "schedule_errors": schedule_errors, "blocked_changes": blocked_changes,
            "topology_nodes": len(topology.get("nodes", [])), "topology_edges": len(topology.get("edges", [])),
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
        "checks": list_baseline_checks(ws),
        "drifts": list_drifts(ws),
        "topology": get_topology(ws),
        "incidents": list_incidents(ws),
        "changes": list_change_plans(ws),
        "schedules": list_schedules(ws),
        "operations": list_assurance_operations(ws),
        "generated_at": now_iso(),
    }


def clear_assurance_records(workspace_id: str, *, confirm: bool = False) -> dict[str, Any]:
    """Reset the assurance read model without deleting source evidence."""
    ws = _ws(workspace_id)
    if confirm is not True:
        raise ValueError("confirm_required")
    active_checks = [item for item in list_baseline_checks(ws) if item.get("status") == "collecting"]
    active_operations = [item for item in list_assurance_operations(ws) if item.get("status") == "collecting"]
    if active_checks or active_operations:
        raise ValueError("assurance_records_not_ready_active_tasks")
    removed = store.clear_all(ws)
    return {
        "workspace_id": ws,
        "deleted": sum(removed.values()),
        "deleted_by_kind": removed,
        "preserved": ["cmdb_assets", "inspection_tasks", "artifacts", "sessions", "reports"],
    }
