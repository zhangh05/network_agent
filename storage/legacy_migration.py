# storage/legacy_migration.py
"""Safe legacy data migration into FileStore.

Supports:
- files/upload/* → import_user_upload
- files/agent/<content> → write_agent_output/import_user_upload
- files/agent/<id>.meta.json → index/artifacts.jsonl backfill
- <pcap>.meta.json sidecar → pcap_session/pcap_connections artifacts

All operations are read-only in dry_run mode.
Apply mode creates FileRecord/ArtifactRecord/ReferenceIndex.
Original files are NEVER deleted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from storage.paths import workspace_root, get_workspace_root
from storage.schemas import FileRecord, FileReference


def _safe_name_for_kind(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name or "unnamed")[:80]


def _guess_kind(filename: str) -> tuple:
    n = filename.lower()
    if n.endswith((".pcap", ".pcapng")):
        return "pcap", True
    if n.endswith(".pdf"):
        return "pdf", True
    if n.endswith(".docx"):
        return "docx", True
    if n.endswith(".xlsx"):
        return "xlsx", True
    if n.endswith(".pptx"):
        return "pptx", True
    if n.endswith((".zip", ".tar", ".gz", ".7z")):
        return "zip", True
    if n.endswith((".cfg", ".conf", ".txt", ".log")):
        return "config", False
    if n.endswith(".md"):
        return "markdown", False
    if n.endswith(".json"):
        return "json", False
    if n.endswith((".yaml", ".yml")):
        return "yaml", False
    return "text", False


# ── Scan ─────────────────────────────────────────────────────────────

def scan_workspace_legacy_paths(workspace_id: str) -> dict[str, Any]:
    """Return legacy files found in workspace without modifying anything."""
    ws = workspace_root(workspace_id)

    legacy_upload = []
    legacy_agent_content = []
    legacy_artifact_meta = []
    legacy_pcap_sidecar = []

    # files/upload/*
    upload_dir = ws / "files" / "upload"
    if upload_dir.is_dir():
        for f in upload_dir.iterdir():
            if f.is_file():
                legacy_upload.append({
                    "path": str(f.relative_to(ws)),
                    "abs_path": str(f),
                    "name": f.name,
                    "size": f.stat().st_size,
                })

    # files/agent/*
    agent_dir = ws / "files" / "agent"
    if agent_dir.is_dir():
        for f in agent_dir.iterdir():
            if not f.is_file():
                continue
            rel = str(f.relative_to(ws))
            if f.name.endswith(".meta.json"):
                legacy_artifact_meta.append({
                    "path": rel, "abs_path": str(f), "name": f.name,
                })
            elif f.name in ("artifacts_index.json", "run_artifacts.json") or f.name.endswith(".index.json"):
                continue  # skip index files
            else:
                legacy_agent_content.append({
                    "path": rel, "abs_path": str(f), "name": f.name,
                    "size": f.stat().st_size,
                })

    # PCAP sidecar *.meta.json (at any level in workspace)
    for mf in ws.rglob("*.meta.json"):
        if "files/agent/" in str(mf) or "files/upload" in str(mf.parent):
            continue  # already covered by artifact meta scan
        if mf.parent != ws / "files" / "agent":
            legacy_pcap_sidecar.append({
                "path": str(mf.relative_to(ws)),
                "abs_path": str(mf),
                "name": mf.name,
            })

    return {
        "workspace_id": workspace_id,
        "legacy_upload_files": legacy_upload,
        "legacy_agent_content_files": legacy_agent_content,
        "legacy_artifact_meta_files": legacy_artifact_meta,
        "legacy_pcap_sidecar_files": legacy_pcap_sidecar,
        "warnings": [],
    }


# ── Migrate ───────────────────────────────────────────────────────────

def _already_indexed(workspace_id: str, rel_path: str) -> bool:
    """Check if a file at rel_path already has a FileRecord."""
    try:
        from storage.file_store import list_files
        existing = list_files(workspace_id, lifecycle="")
        return any(r.get("path") == rel_path for r in existing)
    except Exception:
        return False


def migrate_workspace_legacy_paths(
    workspace_id: str, *, dry_run: bool = True
) -> dict[str, Any]:
    """Migrate legacy files into FileStore.

    dry_run=True: report planned actions, no writes.
    dry_run=False: create records. Original files preserved.
    """
    scan = scan_workspace_legacy_paths(workspace_id)
    planned: list[dict] = []
    migrated: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    # ── upload files ──
    for uf in scan["legacy_upload_files"]:
        if _already_indexed(workspace_id, uf["path"]):
            skipped.append(uf)
            continue
        kind, binary = _guess_kind(uf["name"])
        lt = "config_input" if kind == "config" else ("pcap_input" if kind == "pcap" else "user_upload")
        action = {
            "type": "import_user_upload",
            "legacy_path": uf["path"],
            "logical_type": lt,
            "file_kind": kind,
            "binary": binary,
            "source": "legacy_migration",
        }
        planned.append(action)
        if not dry_run:
            try:
                from storage.file_store import import_user_upload
                rec = import_user_upload(
                    workspace_id=workspace_id,
                    file_source=uf["abs_path"],
                    original_name=uf["name"],
                    logical_type=lt,
                    file_kind=kind,
                    binary=binary,
                    source="legacy_migration",
                    metadata={
                        "migrated_from": "files/upload",
                        "legacy_path": uf["path"],
                        "legacy_migration": True,
                    },
                )
                migrated.append({**action, "file_id": rec.file_id})
            except Exception as exc:
                errors.append({**action, "error": str(exc)[:200]})
        else:
            migrated.append(action)  # in dry_run, planned = migrated

    # ── agent content files ──
    for af in scan["legacy_agent_content_files"]:
        if _already_indexed(workspace_id, af["path"]):
            skipped.append(af)
            continue
        kind, binary = _guess_kind(af["name"])
        ext = kind if kind != "config" else "txt"
        action = {
            "type": "write_agent_output",
            "legacy_path": af["path"],
            "file_kind": kind,
            "logical_type": "artifact_output",
            "source": "legacy_migration",
        }
        planned.append(action)
        if not dry_run:
            try:
                path = workspace_root(workspace_id) / af["path"]
                if binary:
                    from storage.file_store import import_user_upload
                    rec = import_user_upload(
                        workspace_id=workspace_id,
                        file_source=str(path),
                        original_name=af["name"],
                        logical_type="artifact_output",
                        file_kind=kind,
                        binary=True,
                        source="legacy_migration",
                        metadata={
                            "migrated_from": "files/agent",
                            "legacy_path": af["path"],
                            "legacy_migration": True,
                        },
                    )
                else:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    from storage.file_store import write_agent_output
                    rec = write_agent_output(
                        workspace_id=workspace_id,
                        content=content,
                        logical_type="artifact_output",
                        file_kind=ext,
                        title=af["name"],
                        ext=ext,
                        source="legacy_migration",
                        metadata={
                            "migrated_from": "files/agent",
                            "legacy_path": af["path"],
                            "legacy_migration": True,
                        },
                    )
                migrated.append({**action, "file_id": rec.file_id})
            except Exception as exc:
                errors.append({**action, "error": str(exc)[:200]})
        else:
            migrated.append(action)

    # ── artifact meta → index/artifacts.jsonl ──
    for am in scan["legacy_artifact_meta_files"]:
        action = {
            "type": "migrate_artifact_meta",
            "legacy_path": am["path"],
            "source": "legacy_migration",
        }
        planned.append(action)
        if not dry_run:
            try:
                meta_path = Path(am["abs_path"])
                data = json.loads(meta_path.read_text())
                idx_path = workspace_root(workspace_id) / "index" / "artifacts.jsonl"
                idx_path.parent.mkdir(parents=True, exist_ok=True)
                data["_migrated_from"] = am["path"]
                data["_legacy_migration"] = True
                with open(idx_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
                migrated.append({**action, "artifact_id": data.get("artifact_id", "")})
            except Exception as exc:
                errors.append({**action, "error": str(exc)[:200]})
        else:
            migrated.append(action)

    # ── PCAP sidecar → artifacts ──
    for ps in scan["legacy_pcap_sidecar_files"]:
        action = {
            "type": "migrate_pcap_sidecar",
            "legacy_path": ps["path"],
            "source": "legacy_migration",
        }
        planned.append(action)
        if not dry_run:
            try:
                sidecar = Path(ps["abs_path"])
                meta = json.loads(sidecar.read_text())
                from artifacts.store import save_artifact
                from storage.reference_index import add_reference
                sid = meta.get("session_id", sidecar.stem)

                session_art = save_artifact(
                    workspace_id=workspace_id,
                    content=json.dumps(meta, ensure_ascii=False, indent=2),
                    artifact_type="pcap_session",
                    title=f"Migrated PCAP session: {sid}",
                    metadata={
                        "migrated_from": "pcap_sidecar",
                        "legacy_path": ps["path"],
                        "legacy_migration": True,
                        "pcap_session_id": sid,
                    },
                )
                if meta.get("connections"):
                    conn_art = save_artifact(
                        workspace_id=workspace_id,
                        content=json.dumps(meta["connections"], ensure_ascii=False, indent=2),
                        artifact_type="pcap_connections",
                        title=f"Migrated PCAP connections: {sid}",
                        metadata={
                            "migrated_from": "pcap_sidecar",
                            "legacy_path": ps["path"],
                            "legacy_migration": True,
                            "pcap_session_id": sid,
                        },
                    )

                # ReferenceIndex: link pcap file if available
                if meta.get("filepath"):
                    pcap_path = meta["filepath"]
                    try:
                        from storage.file_store import list_files
                        matching = [r for r in list_files(workspace_id) if pcap_path in r.get("path", "")]
                        for m in matching:
                            add_reference(workspace_id, m["file_id"], "pcap_session", sid, "source")
                    except Exception:
                        pass

                migrated.append({
                    **action,
                    "session_artifact_id": session_art.artifact_id if session_art else "",
                })
            except Exception as exc:
                errors.append({**action, "error": str(exc)[:200]})
        else:
            migrated.append(action)

    return {
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "planned": planned,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
    }


def migrate_all_workspaces(*, dry_run: bool = True) -> list[dict[str, Any]]:
    """Run migration for all known workspaces."""
    root = get_workspace_root()
    results = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if d.is_dir() and re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", d.name):
                results.append(migrate_workspace_legacy_paths(d.name, dry_run=dry_run))
    return results
