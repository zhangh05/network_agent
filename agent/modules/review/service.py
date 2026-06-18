# agent/modules/review/service.py
"""Manual review flow service (v0.9).

Two service functions:
  - list_review_items(workspace_id, artifact_id)
  - update_review_item(workspace_id, artifact_id, item_id, status, user_note)

Storage layout:
  {ws_root}/{workspace_id}/reviews/{artifact_id}.json
  {
    "workspace_id": "...",
    "artifact_id": "...",
    "updated_at": "iso8601",
    "items": {
        "<item_id>": {"status": "accepted|ignored|modified|pending",
                       "user_note": "...",
                       "updated_at": "iso8601"}
    }
  }

The original artifact is NEVER written to. The capability is the
sidecar only. translated_config is preserved verbatim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


VALID_STATUSES = {"pending", "accepted", "ignored", "modified"}


def init_review_sidecar(
    workspace_id: str,
    artifact_id: str,
    manual_review_items: list,
) -> dict:
    """Create/overwrite the review sidecar with initial items.

    Called at translation time so review.item.list works immediately.
    Each item starts as "pending".  Existing sidecar data is preserved
    for items that already have a status set.
    """
    if not workspace_id or not artifact_id:
        return {"ok": False, "summary": "workspace_id and artifact_id required"}
    try:
        # Preserve existing statuses if sidecar already exists
        existing = _load_sidecar(workspace_id, artifact_id)
        existing_items = existing.get("items", {}) or {}
        new_items = {}
        for idx, it in enumerate(manual_review_items or []):
            if not isinstance(it, dict):
                continue
            item_id = str(it.get("item_id") or it.get("id") or f"item_{idx}")
            if item_id in existing_items:
                new_items[item_id] = existing_items[item_id]
            else:
                new_items[item_id] = {
                    "status": "pending",
                    "user_note": "",
                    "updated_at": _now_iso(),
                }
        _save_sidecar(workspace_id, artifact_id, {
            "workspace_id": workspace_id,
            "artifact_id": artifact_id,
            "items": new_items,
        })
        return {"ok": True, "summary": f"Initialized {len(new_items)} review items for {artifact_id}"}
    except Exception as e:
        return {"ok": False, "summary": f"init_review_sidecar failed: {e!r}"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ws_root() -> Path:
    """Workspace root. Mirrors artifacts.store._get_ws_root() but
    respects monkey-patches (e.g. harness/conftest.py) by reading the
    workspace.manager.WS_ROOT at call time, not import time.
    """
    try:
        import workspace.manager as wm
        return wm.WS_ROOT
    except Exception:
        from artifacts.store import _get_ws_root
        return _get_ws_root()


def _sidecar_path(workspace_id: str, artifact_id: str) -> Path:
    # Validate artifact_id to prevent path traversal
    safe_id = _validate_artifact_id(artifact_id)
    return _ws_root() / workspace_id / "sys/reviews" / f"{safe_id}.json"


def _validate_artifact_id(artifact_id: str) -> str:
    """Ensure artifact_id is safe for use in file paths."""
    clean = str(artifact_id).strip()
    if not clean or len(clean) > 128 or ".." in clean or "/" in clean or "\\" in clean:
        raise ValueError(f"invalid artifact_id: {artifact_id!r}")
    return clean


def _load_sidecar(workspace_id: str, artifact_id: str) -> dict:
    p = _sidecar_path(workspace_id, artifact_id)
    if not p.exists():
        return {"workspace_id": workspace_id, "artifact_id": artifact_id,
                "items": {}, "updated_at": _now_iso()}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"workspace_id": workspace_id, "artifact_id": artifact_id,
                    "items": {}, "updated_at": _now_iso()}
        data.setdefault("items", {})
        return data
    except Exception:
        return {"workspace_id": workspace_id, "artifact_id": artifact_id,
                "items": {}, "updated_at": _now_iso()}


def _save_sidecar(workspace_id: str, artifact_id: str, data: dict) -> None:
    p = _sidecar_path(workspace_id, artifact_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_artifact_meta_items(workspace_id: str, artifact_id: str) -> list:
    """Read manual_review_items from the artifact's own metadata.

    Returns the list as it was saved at translation time. This is the
    source of truth for the *set* of items; the sidecar is the
    source of truth for per-item *status / user_note*.
    """
    from artifacts.store import get_artifact
    rec = get_artifact(workspace_id, artifact_id)
    if rec is None:
        return []
    md = rec.metadata or {}
    items = md.get("manual_review_items") or []
    if isinstance(items, list):
        return items
    return []


def list_review_items(workspace_id: str, artifact_id: str) -> dict:
    """List manual_review_items with current status / user_note."""
    if not workspace_id or not artifact_id:
        return {
            "ok": False,
            "summary": "workspace_id and artifact_id are required",
            "items": [],
            "errors": ["missing_inputs"],
        }
    from artifacts.store import get_artifact
    rec = get_artifact(workspace_id, artifact_id)
    if rec is None:
        return {
            "ok": False,
            "summary": f"Artifact not found: {artifact_id}",
            "items": [],
            "errors": ["artifact_not_found"],
        }
    base_items = _get_artifact_meta_items(workspace_id, artifact_id)
    sidecar = _load_sidecar(workspace_id, artifact_id)
    side_items = sidecar.get("items", {}) or {}
    merged = []
    for idx, it in enumerate(base_items):
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("item_id") or it.get("id") or f"item_{idx}")
        rev = side_items.get(item_id, {})
        merged.append({
            "item_id": item_id,
            "artifact_id": artifact_id,
            "severity": it.get("severity", ""),
            "category": it.get("category", ""),
            "line_no": it.get("line_no"),
            "source_text": it.get("source_text", ""),
            "translated_text": it.get("translated_text", ""),
            "reason": it.get("reason", ""),
            "recommendation": it.get("recommendation", ""),
            "status": rev.get("status", "pending"),
            "user_note": rev.get("user_note", ""),
            "updated_at": rev.get("updated_at", ""),
        })
    return {
        "ok": True,
        "summary": f"Listed {len(merged)} review item(s) for {artifact_id}",
        "artifact_id": artifact_id,
        "items": merged,
        "count": len(merged),
        "errors": [],
        "warnings": [],
        "metadata": {
            "workspace_id": workspace_id,
            "artifact_id": artifact_id,
        },
    }


def update_review_item(
    workspace_id: str,
    artifact_id: str,
    item_id: str,
    status: str,
    user_note: str = "",
) -> dict:
    """Update one review item's status and user_note in the sidecar.

    Does NOT modify the original artifact or its translated_config.
    Does NOT generate a deployable_config.
    """
    if not workspace_id or not artifact_id or not item_id:
        return {
            "ok": False,
            "summary": "workspace_id, artifact_id, item_id are required",
            "errors": ["missing_inputs"],
        }
    if status not in VALID_STATUSES:
        return {
            "ok": False,
            "summary": f"invalid status: {status}; must be one of {sorted(VALID_STATUSES)}",
            "errors": ["invalid_status"],
        }
    from artifacts.store import get_artifact
    rec = get_artifact(workspace_id, artifact_id)
    if rec is None:
        return {
            "ok": False,
            "summary": f"Artifact not found: {artifact_id}",
            "errors": ["artifact_not_found"],
        }
    base_items = _get_artifact_meta_items(workspace_id, artifact_id)
    # Verify item_id actually exists in the artifact
    valid_ids = set()
    for idx, it in enumerate(base_items):
        if isinstance(it, dict):
            valid_ids.add(str(it.get("item_id") or it.get("id") or f"item_{idx}"))
    if item_id not in valid_ids:
        return {
            "ok": False,
            "summary": f"item_id not in artifact's manual_review_items: {item_id}",
            "errors": ["item_not_found"],
            "valid_item_ids": sorted(valid_ids),
        }
    # Load + update sidecar
    sidecar = _load_sidecar(workspace_id, artifact_id)
    sidecar.setdefault("items", {})
    sidecar["items"][item_id] = {
        "status": status,
        "user_note": str(user_note or ""),
        "updated_at": _now_iso(),
    }
    _save_sidecar(workspace_id, artifact_id, sidecar)
    return {
        "ok": True,
        "summary": f"Updated review item {item_id} -> status={status}",
        "artifact_id": artifact_id,
        "item_id": item_id,
        "status": status,
        "user_note": str(user_note or ""),
        "updated_at": sidecar["items"][item_id]["updated_at"],
        "errors": [],
        "warnings": [],
        "metadata": {
            "workspace_id": workspace_id,
            "original_artifact_modified": False,
            "deployable_config_produced": False,
        },
    }


# ── v0.8.2 — ModuleResult projection ──

def to_module_result(result: dict) -> "ModuleResult":
    """Project a v0.9 review result dict into a standard ModuleResult."""
    from agent.protocol.module_result import ModuleResult
    if not isinstance(result, dict):
        return ModuleResult.failure(
            summary="review service returned non-dict result",
            errors=["invalid_result_shape"],
        )
    ok = bool(result.get("ok", False))
    data = {
        k: v for k, v in result.items()
        if k not in ("errors", "warnings", "metadata", "summary", "ok", "items")
    }
    if ok:
        return ModuleResult.success(
            summary=str(result.get("summary", "")),
            data=data,
            artifacts=[],
            warnings=list(result.get("warnings") or []),
            metadata=dict(result.get("metadata") or {}),
        )
    return ModuleResult.failure(
        summary=str(result.get("summary", "")),
        errors=list(result.get("errors") or ["unknown_error"]),
        warnings=list(result.get("warnings") or []),
        data=data,
        metadata=dict(result.get("metadata") or {}),
    )
