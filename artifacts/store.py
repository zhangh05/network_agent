# artifacts/store.py
"""Artifact store — save/read/list/delete/promote artifacts with policy, redaction, index."""

import json, hashlib, os, re, time, shutil
from pathlib import Path
from typing import Optional

from artifacts.schemas import ArtifactRecord, ArtifactIndex, RunArtifactIndex
from artifacts.redaction import redact_artifact_content, contains_secret, redact_metadata
from artifacts.classifier import classify_file

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def _get_ws_root():
    try:
        from workspace.manager import WS_ROOT as w
        return w
    except Exception:
        return WS_ROOT


def _safe_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', name or "artifact")[:120]


def _artifact_dir(ws_id: str, artifact_type: str = "") -> Path:
    ws = _get_ws_root() / ws_id
    if artifact_type:
        return ws / "artifacts" / artifact_type
    return ws / "artifacts"


def _index_path(ws_id: str) -> Path:
    return _get_ws_root() / ws_id / "indexes" / "artifacts.index.json"


def _load_index(ws_id: str) -> ArtifactIndex:
    p = _index_path(ws_id)
    if p.is_file():
        try:
            d = json.loads(p.read_text())
            return ArtifactIndex(workspace_id=ws_id, artifact_ids=d.get("artifact_ids", []),
                                artifact_count=d.get("artifact_count", 0),
                                updated_at=d.get("updated_at", ""))
        except Exception:
            pass
    return ArtifactIndex(workspace_id=ws_id)


def _save_index(idx: ArtifactIndex):
    p = _index_path(idx.workspace_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    idx.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    idx.artifact_count = len(idx.artifact_ids)
    p.write_text(json.dumps(idx.as_dict(), indent=2, ensure_ascii=False))


# ═══════════════ PUBLIC API ═══════════════

def save_artifact(workspace_id: str, content: str = "", source_path: str = "",
                  artifact_type: str = "", title: str = "", scope: str = "workspace",
                  sensitivity: str = "", run_id: str = "", module: str = "",
                  skill: str = "", capability_id: str = "", metadata: dict = None,
                  tags: list = None, source: str = "module_output") -> Optional[ArtifactRecord]:
    """Save an artifact. Returns ArtifactRecord or None if blocked by policy."""
    from workspace.manager import ensure_workspace
    ensure_workspace(workspace_id)

    # Read content from source_path if provided
    if source_path and not content:
        sp = Path(source_path)
        if sp.is_file():
            content = sp.read_text()
            artifact_type = artifact_type or "unknown"

    if not content:
        return None

    # Security check: reject or redact secret content
    if contains_secret(content):
        if sensitivity == "secret":
            content = redact_artifact_content(content)
        else:
            return None  # reject secret content unless explicitly labeled

    # Classify
    cls = classify_file(source_path, content)
    artifact_type = artifact_type or cls["artifact_type"]
    sensitivity = sensitivity or cls["sensitivity"]

    # Create artifact ID
    art_id = artifact_id = hashlib.sha256(content.encode()).hexdigest()[:16]
    sha = hashlib.sha256(content.encode()).hexdigest()
    size = len(content.encode())

    # Determine subdirectory based on artifact_type
    type_dir = _type_dir(artifact_type)
    art_dir = _get_ws_root() / workspace_id / "artifacts" / type_dir
    art_dir.mkdir(parents=True, exist_ok=True)

    # Safe filename
    base = _safe_name(title or artifact_type)
    ext = cls["file_ext"] or "txt"
    fname = f"{base}.{ext}"
    # Uniqueify if exists
    fpath = art_dir / fname
    if fpath.exists():
        fname = f"{base}_{art_id[:8]}.{ext}"
        fpath = art_dir / fname

    fpath.write_text(content)

    # Build record
    title = title or f"{artifact_type}: {art_id[:8]}"
    rec = ArtifactRecord(
        artifact_id=art_id, workspace_id=workspace_id, run_id=run_id,
        module=module, skill=skill, capability_id=capability_id,
        artifact_type=artifact_type, title=title,
        scope=scope, sensitivity=sensitivity, lifecycle="active",
        path=str(fpath), relative_path=f"{type_dir}/{fname}",
        mime_type=cls["mime_type"], file_ext=cls["file_ext"],
        size_bytes=size, sha256=sha, source=source,
        metadata=redact_metadata(metadata or {}),
        tags=tags or cls["tags"],
        redaction_applied=cls["contains_secret"],
    )

    # Write record metadata
    meta_path = art_dir / f"{art_id}.meta.json"
    meta_path.write_text(json.dumps(rec.as_dict(), indent=2, ensure_ascii=False))

    # Update index
    idx = _load_index(workspace_id)
    if art_id not in idx.artifact_ids:
        idx.artifact_ids.append(art_id)
    _save_index(idx)

    # Update run artifact index
    if run_id:
        _update_run_index(workspace_id, run_id, art_id, artifact_type, cls)

    # Update workspace state artifact counts
    try:
        from workspace.manager import update_workspace_state
        update_workspace_state(workspace_id, {"artifact_counts": idx.artifact_count})
    except Exception:
        pass

    return rec


def get_artifact(workspace_id: str, artifact_id: str) -> Optional[ArtifactRecord]:
    """Get artifact metadata (no content)."""
    for type_dir in _all_type_dirs():
        meta = _get_ws_root() / workspace_id / "artifacts" / type_dir / f"{artifact_id}.meta.json"
        if meta.is_file():
            try:
                data = json.loads(meta.read_text())
                return ArtifactRecord(**{
                    k: v for k, v in data.items() if k in ArtifactRecord.__dataclass_fields__
                })
            except Exception:
                pass
    return None


def read_artifact_content(workspace_id: str, artifact_id: str,
                          allow_sensitive: bool = False) -> Optional[str]:
    """Read artifact file content. Secret always blocked."""
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return None
    if rec.sensitivity == "secret":
        return None
    if rec.sensitivity == "sensitive" and not allow_sensitive:
        return None
    if rec.lifecycle == "deleted":
        return None

    path = Path(rec.path) if rec.path else None
    if path and path.is_file():
        content = path.read_text()
        if rec.redaction_applied:
            content = redact_artifact_content(content)
        return content
    return None


def list_artifacts(workspace_id: str, run_id: str = None, artifact_type: str = None,
                   scope: str = None, sensitivity: str = None,
                   include_deleted: bool = False, limit: int = 100) -> list:
    """List artifacts with optional filters."""
    idx = _load_index(workspace_id)
    results = []
    for aid in idx.artifact_ids:
        rec = get_artifact(workspace_id, aid)
        if not rec:
            continue
        if not include_deleted and rec.lifecycle == "deleted":
            continue
        if run_id and rec.run_id != run_id:
            continue
        if artifact_type and rec.artifact_type != artifact_type:
            continue
        if scope and rec.scope != scope:
            continue
        if sensitivity and rec.sensitivity != sensitivity:
            continue
        results.append(rec.as_dict())
        if len(results) >= limit:
            break
    return results


def delete_artifact(workspace_id: str, artifact_id: str) -> bool:
    """Soft-delete (lifecycle=deleted)."""
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return False
    rec.lifecycle = "deleted"
    rec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    type_dir = _type_dir(rec.artifact_type)
    meta_path = _get_ws_root() / workspace_id / "artifacts" / type_dir / f"{artifact_id}.meta.json"
    meta_path.write_text(json.dumps(rec.as_dict(), indent=2, ensure_ascii=False))
    return True


def promote_artifact(workspace_id: str, artifact_id: str, target_scope: str) -> Optional[ArtifactRecord]:
    """Promote artifact to higher scope."""
    if target_scope not in ("workspace", "shared", "global"):
        return None
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return None
    if rec.sensitivity == "secret" and target_scope == "shared":
        return None
    if rec.sensitivity == "sensitive" and target_scope == "shared" and not rec.metadata.get("_explicit_allow_sensitive_share"):
        return None

    rec.scope = target_scope
    rec.lifecycle = "promoted"
    rec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    type_dir = _type_dir(rec.artifact_type)
    meta_path = _get_ws_root() / workspace_id / "artifacts" / type_dir / f"{artifact_id}.meta.json"
    meta_path.write_text(json.dumps(rec.as_dict(), indent=2, ensure_ascii=False))
    return rec


def summarize_artifact_content(workspace_id: str, artifact_id: str) -> dict:
    """Return summary of artifact (no full content)."""
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return {}
    return {
        "artifact_id": rec.artifact_id,
        "artifact_type": rec.artifact_type,
        "title": rec.title,
        "summary": rec.summary,
        "size_bytes": rec.size_bytes,
        "line_count": rec.metadata.get("line_count", 0) if rec.metadata else 0,
        "sensitivity": rec.sensitivity,
        "created_at": rec.created_at,
    }


def get_run_artifacts(workspace_id: str, run_id: str) -> dict:
    """Get artifact refs for a specific run."""
    run_dir = _get_ws_root() / workspace_id / "runs"
    path = run_dir / f"{run_id}.artifacts.json"
    if not path.is_file():
        return {"workspace_id": workspace_id, "run_id": run_id,
                "input_artifacts": [], "output_artifacts": [], "report_artifacts": [], "temp_artifacts": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _update_run_index(ws_id, run_id, art_id, artifact_type, cls_info):
    """Update run artifact index."""
    idx = get_run_artifacts(ws_id, run_id)
    art_info = {"artifact_id": art_id, "artifact_type": artifact_type, "title": cls_info.get("title", "")}

    if artifact_type in ("input_config", "template", "sample"):
        idx.setdefault("input_artifacts", []).append(art_info)
    elif artifact_type in ("output_config",):
        idx.setdefault("output_artifacts", []).append(art_info)
    elif artifact_type in ("report", "inspection_result", "topology_json", "topology_image"):
        idx.setdefault("report_artifacts", []).append(art_info)
    else:
        idx.setdefault("temp_artifacts", []).append(art_info)

    run_dir = _get_ws_root() / ws_id / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{run_id}.artifacts.json").write_text(json.dumps(idx, indent=2, ensure_ascii=False))


def _type_dir(artifact_type: str) -> str:
    m = {
        "input_config": "inputs", "output_config": "outputs",
        "report": "reports", "topology_json": "topology",
        "topology_image": "topology", "inspection_log": "outputs",
        "inspection_result": "reports", "knowledge_doc": "knowledge",
        "knowledge_index": "knowledge", "template": "inputs",
        "sample": "inputs", "trace_export": "reports",
        "temp": "temp", "unknown": "quarantine",
    }
    return m.get(artifact_type, "quarantine")


def _all_type_dirs() -> list:
    return ["inputs", "outputs", "reports", "topology", "knowledge", "temp", "quarantine"]
