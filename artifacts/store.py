# artifacts/store.py
"""Artifact store — save/read/list/delete/promote with policy, redaction, index.

artifact_id = art_<uuid[:16]> (unique per object, not content-based).
sha256 = content fingerprint (for dedup reference, not for identity).
source_path validated against allowed directories only.
"""

import json, hashlib, os, re, time, shutil, uuid
from pathlib import Path
from typing import Optional

from artifacts.schemas import ArtifactRecord, ArtifactIndex, RunArtifactIndex
from artifacts.redaction import redact_artifact_content, contains_secret, redact_metadata
from artifacts.classifier import classify_file

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

# Allowed source directories for source_path reads
ALLOWED_SOURCE_DIRS = ["runtime/uploads", "runtime/temp",
                        "artifacts/quarantine", "artifacts/temp", "shared"]

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _get_max_size() -> int:
    """Resolve max artifact size from env or default."""
    try:
        mb = int(os.environ.get("NETWORK_AGENT_MAX_UPLOAD_MB", "0"))
        if mb > 0:
            return mb * 1024 * 1024
    except ValueError:
        pass
    return MAX_FILE_SIZE


def _get_ws_root():
    try:
        from workspace.manager import WS_ROOT as w
        return w
    except Exception:
        return WS_ROOT


def _safe_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', name or "artifact")[:120]


def _new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:16]}"


def _index_path(ws_id: str) -> Path:
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
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


def _validate_source_path(source_path: str, workspace_id: str = "") -> bool:
    """Strict path boundary check using resolve().relative_to()."""
    if not source_path:
        return True

    # Absolute vs relative
    try:
        resolved = Path(source_path).resolve()
    except Exception:
        return False

    # Reject known dangerous paths
    banned = ["/etc/", "/var/", "/tmp/", "config/LLM", ".git/", "memory/data/"]
    p_str = str(resolved)
    for bp in banned:
        if bp in p_str:
            return False

    # Build allowed parents
    allowed_parents = []
    root_path = ROOT.resolve()
    ws_root = _get_ws_root().resolve()

    allowed_parents.append(root_path / "runtime" / "uploads")
    allowed_parents.append(root_path / "runtime" / "temp")
    allowed_parents.extend([
        root_path / "shared" / "knowledge",
        root_path / "shared" / "templates",
        root_path / "shared" / "vendor_docs",
        root_path / "shared" / "samples",
    ])
    if workspace_id:
        ws = ws_root / workspace_id
        allowed_parents.extend([
            ws / "artifacts" / "quarantine",
            ws / "artifacts" / "temp",
        ])

    for parent in allowed_parents:
        try:
            resolved.relative_to(parent.resolve())
            return True
        except ValueError:
            continue
    return False


# ═══════════════ PUBLIC API ═══════════════

def save_artifact(workspace_id: str, content: str = "", source_path: str = "",
                  artifact_type: str = "", title: str = "", scope: str = "workspace",
                  sensitivity: str = "", run_id: str = "", module: str = "",
                  skill: str = "", capability_id: str = "", metadata: dict = None,
                  tags: list = None, source: str = "module_output") -> Optional[ArtifactRecord]:
    """Save an artifact. Returns ArtifactRecord or None if blocked by policy."""
    from workspace.manager import ensure_workspace
    ensure_workspace(workspace_id)

    # Read from source_path with security validation
    if source_path and not content:
        if not _validate_source_path(source_path, workspace_id):
            return None
        sp = Path(source_path)
        if not sp.is_file():
            return None
        # Size guard BEFORE read_text()
        max_size = _get_max_size()
        file_size = sp.stat().st_size
        if file_size > max_size:
            return None
        content = sp.read_text()
        artifact_type = artifact_type or "unknown"

    if not content:
        return None

    # Content branch size guard (text content)
    max_size = _get_max_size()
    if len(content.encode("utf-8")) > max_size:
        return None

    # Security check: reject or redact secret content
    if contains_secret(content):
        if sensitivity == "secret":
            content = redact_artifact_content(content)
        else:
            return None

    # Classify
    cls = classify_file(source_path, content)
    artifact_type = artifact_type or cls["artifact_type"]
    sensitivity = sensitivity or cls["sensitivity"]

    # Unique artifact_id (not content-based)
    art_id = _new_artifact_id()
    sha = hashlib.sha256(content.encode()).hexdigest()
    size = len(content.encode())

    # Determine subdirectory
    type_dir = _type_dir(artifact_type)
    art_dir = _get_ws_root() / workspace_id / "artifacts" / type_dir
    art_dir.mkdir(parents=True, exist_ok=True)

    # Safe filename
    base = _safe_name(title or artifact_type)
    ext = cls["file_ext"] or "txt"
    fname = f"{base}_{art_id}.{ext}"
    fpath = art_dir / fname

    fpath.write_text(content)

    # Build record
    title = title or f"{artifact_type}: {art_id}"
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

    # Write metadata
    meta_path = art_dir / f"{art_id}.meta.json"
    meta_path.write_text(json.dumps(rec.as_dict(), indent=2, ensure_ascii=False))

    # Update index
    idx = _load_index(workspace_id)
    if art_id not in idx.artifact_ids:
        idx.artifact_ids.append(art_id)
    _save_index(idx)

    # Update run artifact index
    if run_id:
        _update_run_index(workspace_id, run_id, art_id, artifact_type, title)

    return rec


def get_artifact(workspace_id: str, artifact_id: str) -> Optional[ArtifactRecord]:
    """Get artifact by exact ID (not sha256)."""
    from workspace.ids import validate_workspace_id
    workspace_id = validate_workspace_id(workspace_id)
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
    # Fallback: if path is empty (old artifacts), try relative_path
    if (not path or not path.is_file()) and rec.relative_path:
        fallback = _get_ws_root() / workspace_id / "artifacts" / rec.relative_path
        if fallback.is_file():
            path = fallback
    if path and path.is_file():
        return path.read_text()
    return None


def list_artifacts(workspace_id: str, run_id: str = None, artifact_type: str = None,
                   scope: str = None, sensitivity: str = None,
                   include_deleted: bool = False, limit: int = 100) -> list:
    idx = _load_index(workspace_id)
    results = []
    for aid in idx.artifact_ids:
        rec = get_artifact(workspace_id, aid)
        if not rec: continue
        if not include_deleted and rec.lifecycle == "deleted": continue
        if run_id and rec.run_id != run_id: continue
        if artifact_type and rec.artifact_type != artifact_type: continue
        if scope and rec.scope != scope: continue
        if sensitivity and rec.sensitivity != sensitivity: continue
        results.append(sanitize_record(rec, include_metadata=True))
        if len(results) >= limit: break
    return results


def delete_artifact(workspace_id: str, artifact_id: str) -> bool:
    rec = get_artifact(workspace_id, artifact_id)
    if not rec: return False
    rec.lifecycle = "deleted"
    rec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta_path = _get_ws_root() / workspace_id / "artifacts" / _type_dir(rec.artifact_type) / f"{artifact_id}.meta.json"
    meta_path.write_text(json.dumps(sanitize_record(rec), indent=2, ensure_ascii=False))
    # Also remove from knowledge index
    _remove_from_knowledge_index(workspace_id, artifact_id)
    return True


def _remove_from_knowledge_index(workspace_id: str, artifact_id: str):
    """Remove knowledge source entries for a deleted artifact."""
    try:
        from knowledge.store import _sources_path, _chunks_path, _read_jsonl, _write_jsonl
        from workspace.ids import validate_workspace_id
        validate_workspace_id(workspace_id)

        # Remove from sources
        spath = _sources_path(workspace_id)
        if spath.exists():
            sources = _read_jsonl(spath)
            remaining = [s for s in sources if s.get("artifact_id") != artifact_id]
            if len(remaining) < len(sources):
                _write_jsonl(spath, remaining)

        # Remove from chunks
        cpath = _chunks_path(workspace_id)
        if cpath.exists():
            chunks = _read_jsonl(cpath)
            remaining = [c for c in chunks if c.get("artifact_id") != artifact_id]
            if len(remaining) < len(chunks):
                _write_jsonl(cpath, remaining)
    except Exception:
        pass  # Best-effort cleanup, don't block deletion


def promote_artifact(workspace_id: str, artifact_id: str, target_scope: str) -> Optional[ArtifactRecord]:
    if target_scope not in ("workspace", "shared", "global"): return None
    rec = get_artifact(workspace_id, artifact_id)
    if not rec: return None
    if rec.sensitivity == "secret" and target_scope == "shared": return None
    if rec.sensitivity == "sensitive" and target_scope == "shared" \
            and not rec.metadata.get("_explicit_allow_sensitive_share"): return None
    rec.scope = target_scope
    rec.lifecycle = "promoted"
    rec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta_path = _get_ws_root() / workspace_id / "artifacts" / _type_dir(rec.artifact_type) / f"{artifact_id}.meta.json"
    meta_path.write_text(json.dumps(sanitize_record(rec), indent=2, ensure_ascii=False))
    return rec


def summarize_artifact_content(workspace_id: str, artifact_id: str) -> dict:
    rec = get_artifact(workspace_id, artifact_id)
    if not rec: return {}
    return {"artifact_id": rec.artifact_id, "artifact_type": rec.artifact_type,
            "title": rec.title, "size_bytes": rec.size_bytes,
            "sensitivity": rec.sensitivity, "summary": rec.summary,
            "created_at": rec.created_at, "sha256_short": rec.sha256[:12] if rec.sha256 else ""}


def get_run_artifacts(workspace_id: str, run_id: str) -> dict:
    from workspace.ids import validate_workspace_id
    workspace_id = validate_workspace_id(workspace_id)
    p = _get_ws_root() / workspace_id / "runs" / f"{run_id}.artifacts.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"workspace_id": workspace_id, "run_id": run_id,
            "input_artifacts": [], "output_artifacts": [], "report_artifacts": [], "temp_artifacts": []}


def sanitize_record(rec: ArtifactRecord, include_metadata: bool = False) -> dict:
    """Return safe dict for API — no absolute path, metadata redacted."""
    if not isinstance(rec, ArtifactRecord):
        return rec
    d = {
        "artifact_id": rec.artifact_id, "workspace_id": rec.workspace_id,
        "run_id": rec.run_id, "module": rec.module, "skill": rec.skill,
        "capability_id": rec.capability_id, "artifact_type": rec.artifact_type,
        "title": rec.title, "summary": rec.summary,
        "scope": rec.scope, "sensitivity": rec.sensitivity,
        "lifecycle": rec.lifecycle, "relative_path": rec.relative_path,
        "mime_type": rec.mime_type, "file_ext": rec.file_ext,
        "size_bytes": rec.size_bytes, "sha256_short": rec.sha256[:12] if rec.sha256 else "",
        "source": rec.source, "created_at": rec.created_at, "updated_at": rec.updated_at,
        "tags": rec.tags, "redaction_applied": rec.redaction_applied,
    }
    if include_metadata:
        d["metadata"] = redact_metadata(rec.metadata or {})
    return d


# ── helpers ──

def _update_run_index(ws_id, run_id, art_id, artifact_type, title):
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    idx = get_run_artifacts(ws_id, run_id)
    info = {"artifact_id": art_id, "artifact_type": artifact_type, "title": title}
    if artifact_type in ("input_config", "template", "sample"):
        idx.setdefault("input_artifacts", []).append(info)
    elif artifact_type in ("output_config",):
        idx.setdefault("output_artifacts", []).append(info)
    elif artifact_type in ("report", "inspection_result", "topology_json", "topology_image"):
        idx.setdefault("report_artifacts", []).append(info)
    else:
        idx.setdefault("temp_artifacts", []).append(info)
    run_dir = _get_ws_root() / ws_id / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{run_id}.artifacts.json").write_text(json.dumps(idx, indent=2, ensure_ascii=False))


def _type_dir(artifact_type: str) -> str:
    m = {"input_config": "inputs", "output_config": "outputs", "report": "reports",
         "topology_json": "topology", "topology_image": "topology",
         "inspection_log": "outputs", "inspection_result": "reports",
         "knowledge_doc": "knowledge", "knowledge_index": "knowledge",
         "template": "inputs", "sample": "inputs", "trace_export": "reports",
         "temp": "temp", "unknown": "quarantine"}
    return m.get(artifact_type, "quarantine")


def _all_type_dirs() -> list:
    return ["inputs", "outputs", "reports", "topology", "knowledge", "temp", "quarantine"]
