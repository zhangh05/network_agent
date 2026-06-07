# runtime/archive.py
"""Runtime Archive — safe, dry-run-first archival of expired run/trace/job/temp data.

Moves candidates from active directories to workspace/archives/YYYY-MM/.
Default is dry-run only. Real archive requires confirm=True.
Never archives active refs, workspace state references, or workspace-external files.
"""

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


@dataclass
class ArchivePolicy:
    runs_older_than_days: int = 30
    runs_keep_latest: int = 500
    traces_older_than_days: int = 30
    traces_keep_latest: int = 1000
    jobs_older_than_days: int = 30
    jobs_statuses: tuple = ("succeeded", "failed", "cancelled")
    temp_older_than_days: int = 7
    archive_temp_artifacts: bool = True
    archive_quarantine_artifacts: bool = True
    archive_active_refs: bool = False
    archive_reports: bool = False

    def as_dict(self) -> dict:
        return {
            "runs_older_than_days": self.runs_older_than_days,
            "runs_keep_latest": self.runs_keep_latest,
            "traces_older_than_days": self.traces_older_than_days,
            "traces_keep_latest": self.traces_keep_latest,
            "jobs_older_than_days": self.jobs_older_than_days,
            "temp_older_than_days": self.temp_older_than_days,
            "archive_temp_artifacts": self.archive_temp_artifacts,
            "archive_quarantine_artifacts": self.archive_quarantine_artifacts,
            "archive_active_refs": self.archive_active_refs,
            "archive_reports": self.archive_reports,
        }


@dataclass
class ArchivePreview:
    dry_run: bool = True
    workspace_id: str = ""
    policy: dict = field(default_factory=dict)
    candidate_counts: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)
    blocked_items: list = field(default_factory=list)
    moved_counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "workspace_id": self.workspace_id,
            "policy": self.policy,
            "candidate_counts": self.candidate_counts,
            "candidates": self.candidates[:50],
            "blocked_items": self.blocked_items[:20],
            "moved_counts": self.moved_counts,
            "warnings": self.warnings,
        }


def default_archive_policy() -> ArchivePolicy:
    return ArchivePolicy()


def _is_safe_path(path: Path, ws_dir: Path) -> bool:
    try:
        resolved = path.resolve()
        ws_resolved = ws_dir.resolve()
        return str(resolved).startswith(str(ws_resolved))
    except Exception:
        return False


def _get_active_refs(ws_dir: Path) -> set:
    """Get IDs referenced by workspace state — these are protected."""
    active = set()
    state_file = ws_dir / "state.json"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text())
            for key in ("current_run_id", "current_job_id", "current_artifacts",
                        "last_input_artifacts", "last_output_artifacts",
                        "last_report_artifacts", "current_report_artifact_id",
                        "current_topology_artifact_id"):
                val = state.get(key)
                if isinstance(val, str):
                    active.add(val)
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, str):
                            active.add(v)
                        elif isinstance(v, dict):
                            active.add(v.get("artifact_id", ""))
            # Also protect any artifact referenced by recent runs
            runs_dir = ws_dir / "runs"
            if runs_dir.is_dir():
                for rf in list(runs_dir.iterdir())[:100]:
                    try:
                        record = json.loads(rf.read_text()) if rf.suffix == ".json" else {}
                        for art_ref in record.get("artifact_refs", []):
                            aid = art_ref.get("artifact_id", "") if isinstance(art_ref, dict) else str(art_ref)
                            if aid:
                                active.add(aid)
                    except Exception:
                        pass
        except Exception:
            pass
    return active


def preview_archive_candidates(workspace_id: str = "default",
                               policy: ArchivePolicy = None) -> ArchivePreview:
    """Preview archive candidates. NEVER moves files."""
    policy = policy or default_archive_policy()
    ws_dir = WS_ROOT / workspace_id
    preview = ArchivePreview(
        dry_run=True,
        workspace_id=workspace_id,
        policy=policy.as_dict(),
    )

    if not ws_dir.exists():
        preview.warnings.append(f"Workspace '{workspace_id}' not found")
        return preview

    now = time.time()
    active_refs = _get_active_refs(ws_dir)
    candidates = []
    blocked = []

    # ═══ Runs ═══
    runs_dir = ws_dir / "runs"
    if runs_dir.is_dir():
        run_files = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        expired = []
        for rf in run_files:
            if not rf.is_file():
                continue
            if not _is_safe_path(rf, ws_dir):
                blocked.append({"path": rf.name, "reason": "path_outside_workspace"})
                continue
            if rf.stem in active_refs:
                blocked.append({"path": rf.name, "reason": "active_ref"})
                continue
            age_days = (now - rf.stat().st_mtime) / 86400
            if age_days > policy.runs_older_than_days:
                expired.append(rf.name)
        if len(run_files) > policy.runs_keep_latest:
            for rf in run_files[:-policy.runs_keep_latest]:
                if rf.name not in expired:
                    expired.append(rf.name)
        for name in expired:
            candidates.append({"type": "run", "name": name})

    # ═══ Traces ═══
    traces_dir = ws_dir / "traces"
    if traces_dir.is_dir():
        for tf in sorted(traces_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if not tf.is_file():
                continue
            if not _is_safe_path(tf, ws_dir):
                blocked.append({"path": tf.name, "reason": "path_outside_workspace"})
                continue
            age_days = (now - tf.stat().st_mtime) / 86400
            if age_days > policy.traces_older_than_days:
                candidates.append({"type": "trace", "name": tf.name})

    # ═══ Jobs ═══
    jobs_dir = ws_dir / "jobs"
    if jobs_dir.is_dir():
        for jf in jobs_dir.iterdir():
            if not jf.is_file():
                continue
            if not _is_safe_path(jf, ws_dir):
                blocked.append({"path": jf.name, "reason": "path_outside_workspace"})
                continue
            if jf.stem in active_refs:
                blocked.append({"path": jf.name, "reason": "active_ref"})
                continue
            try:
                record = json.loads(jf.read_text()) if jf.suffix == ".json" else {}
                job_status = record.get("status", "")
            except Exception:
                job_status = "unknown"
            if job_status not in policy.jobs_statuses:
                blocked.append({"path": jf.name, "reason": f"job_status:{job_status}"})
                continue
            age_days = (now - jf.stat().st_mtime) / 86400
            if age_days > policy.jobs_older_than_days:
                candidates.append({"type": "job", "name": jf.name})

    # ═══ Temp ═══
    temp_dir = ws_dir / "temp"
    if temp_dir.is_dir():
        for tf in temp_dir.iterdir():
            if not tf.is_file():
                continue
            if not _is_safe_path(tf, ws_dir):
                blocked.append({"path": tf.name, "reason": "path_outside_workspace"})
                continue
            age_days = (now - tf.stat().st_mtime) / 86400
            if age_days > policy.temp_older_than_days:
                candidates.append({"type": "temp", "name": tf.name})

    # ═══ Artifacts (temp/quarantine only) ═══
    art_dir = ws_dir / "artifacts"
    if art_dir.is_dir() and (policy.archive_temp_artifacts or policy.archive_quarantine_artifacts):
        for af in art_dir.iterdir():
            if not af.is_file():
                continue
            if not _is_safe_path(af, ws_dir):
                blocked.append({"path": af.name, "reason": "path_outside_workspace"})
                continue
            try:
                record = json.loads(af.read_text()) if af.suffix == ".json" else {}
                lifecycle = record.get("lifecycle", record.get("scope", ""))
                art_id = record.get("artifact_id", af.stem)
            except Exception:
                continue
            if art_id in active_refs:
                blocked.append({"path": af.name, "reason": "active_ref"})
                continue
            if lifecycle == "temp" and policy.archive_temp_artifacts:
                age_days = (now - af.stat().st_mtime) / 86400
                if age_days > policy.temp_older_than_days:
                    candidates.append({"type": "artifact", "name": af.name})
            elif lifecycle == "quarantine" and policy.archive_quarantine_artifacts:
                candidates.append({"type": "artifact", "name": af.name})

    counts = {}
    for c in candidates:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    preview.candidate_counts = counts
    preview.candidates = candidates
    preview.blocked_items = blocked
    preview.moved_counts = {}
    return preview


def apply_archive(workspace_id: str = "default",
                  policy: ArchivePolicy = None,
                  dry_run: bool = True,
                  confirm: bool = False) -> ArchivePreview:
    """Apply archive. Requires confirm=True for actual file movement."""
    preview = preview_archive_candidates(workspace_id, policy)

    if dry_run:
        preview.dry_run = True
        preview.warnings.append("DRY RUN — no files were moved. Use dry_run=False + confirm=True to apply.")
        return preview

    if not confirm:
        preview.warnings.append("BLOCKED: confirm=True is required when dry_run=False.")
        return preview

    # Actually archive
    ws_dir = WS_ROOT / workspace_id
    month_key = time.strftime("%Y-%m")
    archive_root = ws_dir / "archives" / month_key
    moved = {}

    for candidate in preview.candidates:
        ctype = candidate["type"]
        name = candidate["name"]
        src = None
        dst = None
        if ctype == "run":
            src = ws_dir / "runs" / name
            dst = archive_root / "runs" / name
        elif ctype == "trace":
            src = ws_dir / "traces" / name
            dst = archive_root / "traces" / name
        elif ctype == "job":
            src = ws_dir / "jobs" / name
            dst = archive_root / "jobs" / name
        elif ctype == "temp":
            src = ws_dir / "temp" / name
            dst = archive_root / "temp" / name
        elif ctype == "artifact":
            src = ws_dir / "artifacts" / name
            dst = archive_root / "artifacts" / name
        if src and src.exists() and _is_safe_path(src, ws_dir):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved[ctype] = moved.get(ctype, 0) + 1
            except Exception as e:
                preview.warnings.append(f"Failed to move {name}: {str(e)[:100]}")
        else:
            preview.warnings.append(f"Skipping {name}: source missing or unsafe")

    preview.moved_counts = moved
    preview.dry_run = False
    _write_archive_audit(preview, workspace_id)
    return preview


def _write_archive_audit(preview: ArchivePreview, workspace_id: str):
    audit_dir = WS_ROOT / workspace_id / "runtime_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_id = uuid.uuid4().hex[:12]
    record = {
        "audit_id": f"archive_{audit_id}",
        "type": "archive",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace_id": workspace_id,
        "dry_run": preview.dry_run,
        "confirmed": not preview.dry_run,
        "policy": preview.policy,
        "candidate_counts": preview.candidate_counts,
        "moved_counts": preview.moved_counts,
        "blocked_count": len(preview.blocked_items),
        "warnings": preview.warnings[:20],
    }
    (audit_dir / f"archive_{audit_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )


def get_archive_audits(workspace_id: str = "default") -> list:
    """List archive audit records."""
    audit_dir = WS_ROOT / workspace_id / "runtime_audits"
    if not audit_dir.is_dir():
        return []
    audits = []
    for af in sorted(audit_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if af.name.startswith("archive_") and af.suffix == ".json":
            try:
                audits.append(json.loads(af.read_text()))
            except Exception:
                pass
    return audits[:50]


def get_archive_audit(workspace_id: str, audit_id: str) -> dict:
    """Get a specific archive audit record."""
    audit_path = WS_ROOT / workspace_id / "runtime_audits" / f"{audit_id}.json"
    if audit_path.is_file():
        try:
            return json.loads(audit_path.read_text())
        except Exception:
            pass
    return {}
