# artifacts/store.py
"""Artifact store — save/read/list/delete/promote with policy, redaction, index.

artifact_id = art_<uuid[:16]> (unique per object, not content-based).
sha256 = content fingerprint (for dedup reference, not for identity).
source_path validated against allowed directories only.

Current runtime storage model:
- artifact metadata is written atomically by this store
- artifact content is stored through storage.file_store
  the projection event
- artifact metadata is stored in workspaces/<ws>/index/artifacts.jsonl as a
  read model carrying ssot_event_id
"""

import json, hashlib, os, re, time, shutil, uuid, threading
from pathlib import Path
from typing import Optional

from artifacts.schemas import ArtifactRecord, ArtifactIndex, RunArtifactIndex
from artifacts.redaction import redact_artifact_content, contains_secret, redact_metadata
from artifacts.classifier import classify_file
from storage.schemas import FileRecord
import logging
from agent.runtime.utils import now_iso

# Per-workspace locks for artifact record writes (read-modify-write protection)
_AREC_LOCKS: dict[str, threading.Lock] = {}
_AREC_LOCKS_GUARD = threading.Lock()
_LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

# Allowed source directories for source_path reads. Removed storage directories
# are intentionally not allowed for runtime reads.
ALLOWED_SOURCE_DIRS = [
    "files/data",
    "files/tmp",
    "shared",
]

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


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
    # Allow ASCII, Chinese (CJK), digits, and safe punctuation in filenames.
    return re.sub(r'[^a-zA-Z0-9_.\-\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df\U0002a700-\U0002ebef]', '_', name or "artifact")[:120]


def _new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:16]}"


def _index_path(ws_id: str) -> Path:
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    return _get_ws_root() / ws_id / "sys" / "artifacts.index.json"


def _artifact_records_path(ws_id: str) -> Path:
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    return _get_ws_root() / ws_id / "index" / "artifacts.jsonl"


def _read_artifact_record_dicts(ws_id: str) -> list[dict]:
    p = _artifact_records_path(ws_id)
    if not p.is_file():
        return []
    records: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _artifact_record_from_dict(data: dict) -> ArtifactRecord:
    return ArtifactRecord(**{
        k: v for k, v in data.items() if k in ArtifactRecord.__dataclass_fields__
    })


def _load_index(ws_id: str) -> ArtifactIndex:
    p = _index_path(ws_id)
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return ArtifactIndex(workspace_id=ws_id, artifact_ids=d.get("artifact_ids", []),
                                artifact_count=d.get("artifact_count", 0),
                                updated_at=d.get("updated_at", ""))
        except Exception:
            _LOG.warning("artifacts.store: silent exception", exc_info=True)

    # Fallback to the metadata JSONL if the lightweight sys index is absent.
    records = _read_artifact_record_dicts(ws_id)
    if records:
        ids = [r.get("artifact_id", "") for r in records if r.get("artifact_id")]
        return ArtifactIndex(workspace_id=ws_id, artifact_ids=ids,
                             artifact_count=len(ids), updated_at="")
    return ArtifactIndex(workspace_id=ws_id)


def _save_index(idx: ArtifactIndex):
    p = _index_path(idx.workspace_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    idx.updated_at = now_iso()
    idx.artifact_count = len(idx.artifact_ids)
    p.write_text(json.dumps(idx.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def _record_meta_dict(rec: ArtifactRecord) -> dict:
    data = rec.as_dict()
    # Keep complete storage-critical metadata in the JSONL record even if the
    # public schema summary omits some fields.
    data.update({
        "path": rec.path,
        "relative_path": rec.relative_path,
        "description": rec.description,
        "mime_type": rec.mime_type,
        "file_ext": rec.file_ext,
        "size_bytes": rec.size_bytes,
        "sha256": rec.sha256,
        "file_id": rec.file_id,
        "created_by": rec.created_by,
        "metadata": rec.metadata,
        "derived_from": rec.derived_from,
        "references": rec.references,
    })
    return data


def _save_artifact_record(rec: ArtifactRecord) -> None:
    """Upsert one ArtifactRecord into index/artifacts.jsonl."""
    from workspace.ids import validate_workspace_id

    ws_id = validate_workspace_id(rec.workspace_id)
    p = _artifact_records_path(ws_id)
    p.parent.mkdir(parents=True, exist_ok=True)

    with _AREC_LOCKS_GUARD:
        lock = _AREC_LOCKS.get(ws_id)
        if lock is None:
            lock = threading.Lock()
            _AREC_LOCKS[ws_id] = lock

    with lock:
        records = [
            r for r in _read_artifact_record_dicts(ws_id)
            if r.get("artifact_id") != rec.artifact_id
        ]
        records.append(_record_meta_dict(rec))
        p.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records) + "\n",
            encoding="utf-8",
        )


def _logical_type_for_artifact(artifact_type: str) -> str:
    """Map artifact_type to a storage logical_type for FileRecord tracking."""
    mapping = {
        "translated_config": "translated_config",
        "output_config": "translated_config",
        "report": "report",
        "pcap_session": "pcap_session",
        "pcap_connections": "pcap_connections",
        "pcap_result": "pcap_result",
        "message_large_content": "message_large_content",
    }
    return mapping.get((artifact_type or "").strip(), "artifact_output")


def _validate_source_path(source_path: str, workspace_id: str = "") -> bool:
    """Strict path boundary check using resolve().relative_to()."""
    if not source_path:
        return True

    try:
        resolved = Path(source_path).resolve()
    except Exception:
        return False

    banned = ["/etc/", "/var/", "/tmp/", "config/LLM", ".git/", "memory/data/"]
    p_str = str(resolved)
    for bp in banned:
        if bp in p_str:
            return False

    allowed_parents = []
    root_path = ROOT.resolve()
    ws_root = _get_ws_root().resolve()

    allowed_parents.extend([
        root_path / "runtime" / "uploads",
        root_path / "shared" / "knowledge",
        root_path / "shared" / "templates",
        root_path / "shared" / "vendor_docs",
        root_path / "shared" / "samples",
    ])
    allowed_parents.append(ws_root / "runtime" / "uploads")
    if workspace_id:
        ws = ws_root / workspace_id
        for rel in ALLOWED_SOURCE_DIRS:
            if rel.startswith("shared"):
                continue
            allowed_parents.append(ws / rel)

    for parent in allowed_parents:
        try:
            resolved.relative_to(parent.resolve())
            return True
        except ValueError:
            continue
    return False


def _normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip()).lower()


def _is_generic_report_title(title: str) -> bool:
    return _normalized_title(title) in {"", "report", "报告"}


def _report_day(rec: ArtifactRecord) -> str:
    created_at = str(getattr(rec, "created_at", "") or "")
    return created_at[:10] if len(created_at) >= 10 else ""


def _derive_report_title(content: str, fallback: str) -> str:
    """Use the first markdown H1 as the report title when callers pass 'report'."""
    if not _is_generic_report_title(fallback):
        return fallback
    for line in (content or "").splitlines()[:20]:
        line = line.strip()
        if line.startswith("# "):
            candidate = line[2:].strip()
            if candidate:
                return candidate[:120]
    return fallback


def _report_display_key(rec: ArtifactRecord, named_days: set[str]) -> tuple | None:
    """Return a stable UI key for report list dedupe.

    The store keeps every artifact immutable; this key only controls list
    presentation so intermediate LLM-generated drafts do not flood the
    Artifact Center.
    """
    if rec.artifact_type != "report":
        return ("artifact", rec.artifact_id)

    metadata = rec.metadata if isinstance(rec.metadata, dict) else {}
    task_id = str(metadata.get("inspection_task_id") or "")
    report_format = str(metadata.get("report_format") or metadata.get("format") or rec.file_ext or "")
    if task_id:
        return ("report", "inspection_task", task_id, report_format)

    day = _report_day(rec)
    title = _normalized_title(rec.title)
    if _is_generic_report_title(rec.title):
        if day in named_days:
            return None
        return ("report", "generic_day", day)
    return ("report", "title_day", title, day)


def _dedupe_artifacts_for_listing(records: list[ArtifactRecord]) -> list[ArtifactRecord]:
    named_days = {
        _report_day(rec)
        for rec in records
        if rec.artifact_type == "report" and not _is_generic_report_title(rec.title)
    }
    latest_by_key: dict[tuple, ArtifactRecord] = {}
    key_by_artifact_id: dict[str, tuple] = {}

    for rec in records:
        key = _report_display_key(rec, named_days)
        if key is None:
            continue
        latest_by_key[key] = rec
        key_by_artifact_id[rec.artifact_id] = key

    deduped_reversed: list[ArtifactRecord] = []
    emitted: set[tuple] = set()
    for rec in reversed(records):
        key = key_by_artifact_id.get(rec.artifact_id)
        if key is None or key in emitted:
            continue
        if latest_by_key.get(key) is rec:
            deduped_reversed.append(rec)
            emitted.add(key)
    return list(reversed(deduped_reversed))


# ═══════════════ PUBLIC API ═══════════════

def save_artifact(workspace_id: str, content: str = "", source_path: str = "",
                  artifact_type: str = "", title: str = "", scope: str = "workspace",
                  sensitivity: str = "", run_id: str = "", session_id: str = "", module: str = "",
                  skill: str = "", capability_id: str = "", metadata: dict = None,
                  tags: list = None, source: str = "module_output",
                  file_id: str = "") -> Optional[ArtifactRecord]:
    """Save an artifact. Returns ArtifactRecord or None if blocked by policy."""
    from workspace.manager import ensure_workspace
    ensure_workspace(workspace_id)

    if source_path and not content:
        if not _validate_source_path(source_path, workspace_id):
            return None
        sp = Path(source_path)
        if not sp.is_file():
            return None
        max_size = _get_max_size()
        file_size = sp.stat().st_size
        if file_size > max_size:
            return None
        content = sp.read_text(encoding="utf-8")
        artifact_type = artifact_type or "unknown"

    if not content:
        return None

    max_size = _get_max_size()
    if len(content.encode("utf-8")) > max_size:
        return None

    content_had_secret = contains_secret(content)
    if content_had_secret:
        if sensitivity == "secret":
            content = redact_artifact_content(content)
        else:
            # v3.10: surface the rejection — earlier versions
            # silently returned None which left the operator
            # wondering where the artifact went. We still reject
            # (saving a secret to a non-secret slot would be a
            # data leak) but log the event so the caller can
            # fix the call.
            _LOG.warning(
                "artifacts.store: content contains a secret but "
                "sensitivity=%r — refusing to save without explicit "
                "'secret' marker. Caller should re-issue with "
                "sensitivity='secret' so the redactor runs.",
                sensitivity,
            )
            return None

    cls = classify_file(source_path, content)
    artifact_type = artifact_type or cls["artifact_type"]
    sensitivity = sensitivity or cls["sensitivity"]
    if artifact_type == "report":
        title = _derive_report_title(content, title)

    art_id = _new_artifact_id()
    ext = cls["file_ext"] or "txt"
    logical_type = _logical_type_for_artifact(artifact_type)
    file_kind = cls["file_ext"] or ext or "text"

    try:
        from storage.file_store import get_file_record, write_agent_output
        existing = get_file_record(workspace_id, file_id) if file_id and not content_had_secret else None
        if existing and existing.get("lifecycle", "active") == "active":
            file_rec = FileRecord(**{
                key: value for key, value in existing.items()
                if key in FileRecord.__dataclass_fields__
            })
            from storage import index as file_index
            file_index.update_file_record(workspace_id, file_id, {
                "metadata": {
                    **existing.get("metadata", {}),
                    "artifact_id": art_id,
                    "artifact_type": artifact_type,
                    "storage_managed": True,
                },
            })
        else:
            file_rec = write_agent_output(
                workspace_id=workspace_id,
                content=content,
                logical_type=logical_type,
                file_kind=file_kind,
                title=title or artifact_type or art_id,
                ext=ext,
                source=source,
                run_id=run_id,
                sensitivity=sensitivity,
                metadata={
                    "artifact_id": art_id,
                    "artifact_type": artifact_type,
                    "storage_managed": True,
                },
            )
    except Exception:
        # If FileStore fails, artifact creation fails.
        return None

    ws = _get_ws_root() / workspace_id
    fpath = (ws / file_rec.path).resolve()
    fname = file_rec.path
    title = title or f"{artifact_type}: {art_id}"
    rec = ArtifactRecord(
        artifact_id=art_id, workspace_id=workspace_id, session_id=session_id, run_id=run_id,
        module=module, skill=skill, capability_id=capability_id,
        artifact_type=artifact_type, title=title,
        scope=scope, sensitivity=sensitivity, lifecycle="active",
        path=str(fpath), relative_path=fname,
        mime_type=cls["mime_type"], file_ext=cls["file_ext"],
        size_bytes=file_rec.size_bytes, sha256=file_rec.sha256, source=source,
        file_id=file_rec.file_id,
        metadata=redact_metadata(metadata or {}),
        tags=tags or cls["tags"],
        redaction_applied=cls["contains_secret"],
    )

    _save_artifact_record(rec)

    idx = _load_index(workspace_id)
    if art_id not in idx.artifact_ids:
        idx.artifact_ids.append(art_id)
    _save_index(idx)

    if run_id:
        _update_run_index(workspace_id, run_id, art_id, artifact_type, title)

    try:
        from storage.reference_index import add_reference
        if rec.file_id:
            add_reference(workspace_id, rec.file_id, "artifact", art_id, "output",
                          metadata={"artifact_type": artifact_type, "run_id": run_id})
        src_file = (metadata or {}).get("source_file_id")
        if src_file:
            add_reference(workspace_id, src_file, "artifact", art_id, "source",
                          metadata={"artifact_type": artifact_type, "run_id": run_id})
    except Exception:
        _LOG.warning("artifacts.store: silent exception", exc_info=True)

    from storage.events import publish
    publish(workspace_id, "artifact", "created", art_id)

    return rec


def get_artifact(workspace_id: str, artifact_id: str) -> Optional[ArtifactRecord]:
    """Get artifact by exact ID (not sha256)."""
    from workspace.ids import validate_workspace_id
    workspace_id = validate_workspace_id(workspace_id)
    for data in reversed(_read_artifact_record_dicts(workspace_id)):
        if data.get("artifact_id") == artifact_id:
            try:
                return _artifact_record_from_dict(data)
            except Exception:
                return None
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

    file_id = getattr(rec, "file_id", "") or (rec.metadata or {}).get("file_id", "")
    if file_id:
        try:
            from storage.file_store import read_file_content
            return read_file_content(workspace_id, file_id)
        except Exception:
            _LOG.warning("artifacts.store: silent exception", exc_info=True)

    return None


def list_artifacts(workspace_id: str, run_id: str = None, artifact_type: str = None,
                   scope: str = None, sensitivity: str = None,
                   include_deleted: bool = False, limit: int = 100) -> list:
    idx = _load_index(workspace_id)
    records: list[ArtifactRecord] = []
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
        records.append(rec)

    results = []
    for rec in _dedupe_artifacts_for_listing(records):
        results.append(sanitize_record(rec, include_metadata=True))
        if len(results) >= limit:
            break
    return results


def update_artifact_tags(workspace_id: str, artifact_id: str, tags: list) -> bool:
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return False
    rec.tags = list(tags or [])
    rec.updated_at = now_iso()
    _save_artifact_record(rec)
    from storage.events import publish
    publish(workspace_id, "artifact", "updated", artifact_id)
    return True


def delete_artifact(workspace_id: str, artifact_id: str, hard: bool = False) -> bool:
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return False
    rec.lifecycle = "deleted"
    rec.updated_at = now_iso()
    _save_artifact_record(rec)
    _remove_from_knowledge_index(workspace_id, artifact_id)
    if rec.file_id:
        from storage.file_store import purge_file, soft_delete_file
        (purge_file if hard else soft_delete_file)(workspace_id, rec.file_id)
    from storage.events import publish
    publish(workspace_id, "artifact", "deleted", artifact_id)
    return True


def _remove_from_knowledge_index(workspace_id: str, artifact_id: str):
    """Remove knowledge source entries for a deleted artifact."""
    try:
        from agent.modules.knowledge.service import delete_source, list_sources
        from workspace.ids import validate_workspace_id
        validate_workspace_id(workspace_id)
        result = list_sources(
            workspace_id, include_disabled=True, include_deleted=True,
        )
        for source in result.get("sources", []):
            metadata = source.get("metadata") or {}
            if metadata.get("artifact_id") == artifact_id:
                delete_source(workspace_id, source.get("source_id", ""))
    except Exception:
        pass  # Best-effort cleanup, don't block deletion


def promote_artifact(workspace_id: str, artifact_id: str, target_scope: str) -> Optional[ArtifactRecord]:
    if target_scope not in ("workspace", "shared", "global"):
        return None
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return None
    if rec.sensitivity == "secret" and target_scope == "shared":
        return None
    if rec.sensitivity == "sensitive" and target_scope == "shared" \
            and not rec.metadata.get("_explicit_allow_sensitive_share"):
        return None
    rec.scope = target_scope
    rec.lifecycle = "promoted"
    rec.updated_at = now_iso()
    _save_artifact_record(rec)
    from storage.events import publish
    publish(workspace_id, "artifact", "updated", artifact_id)
    return rec


def summarize_artifact_content(workspace_id: str, artifact_id: str) -> dict:
    rec = get_artifact(workspace_id, artifact_id)
    if not rec:
        return {}
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
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _LOG.warning("artifacts.store: silent exception", exc_info=True)
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
        "file_id": rec.file_id,
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
    (run_dir / f"{run_id}.artifacts.json").write_text(
        json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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
