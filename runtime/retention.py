# runtime/retention.py
"""Runtime retention and prune — safe, dry-run-first data lifecycle management.

Principles:
  - Default is dry-run only — never delete without explicit flag.
  - Active artifacts and referenced outputs are never pruned.
  - Workspace boundaries are absolute — no path traversal.
  - All operations are auditable with structured output.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

# Default policy (all in days or counts)
DEFAULT_POLICY = {
    "runs": {"max_age_days": 30, "max_count": 500},
    "traces": {"max_age_days": 30, "max_count": 1000},
    "jobs": {"max_age_days": 30},
    "artifacts": {"temp_max_age_days": 7},
    "reports": {"auto_prune": False},  # reports are never auto-pruned
}


@dataclass
class RetentionPolicy:
    """Retention policy for a workspace."""
    runs_max_age_days: int = 30
    runs_max_count: int = 500
    traces_max_age_days: int = 30
    traces_max_count: int = 1000
    jobs_max_age_days: int = 30
    artifacts_temp_max_age_days: int = 7
    prune_reports: bool = False

    def as_dict(self) -> dict:
        return {
            "runs_max_age_days": self.runs_max_age_days,
            "runs_max_count": self.runs_max_count,
            "traces_max_age_days": self.traces_max_age_days,
            "traces_max_count": self.traces_max_count,
            "jobs_max_age_days": self.jobs_max_age_days,
            "artifacts_temp_max_age_days": self.artifacts_temp_max_age_days,
            "prune_reports": self.prune_reports,
        }


@dataclass
class RetentionPreview:
    """Result of a retention preview (dry-run)."""
    dry_run: bool = True
    workspace_id: str = ""
    policy: dict = field(default_factory=dict)
    candidate_counts: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)
    blocked_items: list = field(default_factory=list)
    deleted_counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "workspace_id": self.workspace_id,
            "policy": self.policy,
            "candidate_counts": self.candidate_counts,
            "candidates": self.candidates[:50],
            "blocked_items": self.blocked_items[:20],
            "deleted_counts": self.deleted_counts,
            "warnings": self.warnings,
        }


def default_retention_policy() -> RetentionPolicy:
    return RetentionPolicy()


def _is_safe_path(path: Path, ws_dir: Path) -> bool:
    """Verify path is within workspace — uses relative_to(), NOT string startswith."""
    try:
        resolved = path.resolve()
        ws_resolved = ws_dir.resolve()
        resolved.relative_to(ws_resolved)
        return True
    except (ValueError, OSError):
        return False


def _get_active_artifact_ids(ws_dir: Path) -> set:
    """Get artifact IDs referenced by recent runs — these are protected."""
    active = set()
    runs_dir = ws_dir / "runs"
    if runs_dir.is_dir():
        for rf in runs_dir.iterdir():
            if rf.suffix != ".json":
                continue
            try:
                record = json.loads(rf.read_text())
                art_refs = record.get("artifact_refs", [])
                if isinstance(art_refs, list):
                    for ref in art_refs:
                        aid = ref.get("artifact_id", ref) if isinstance(ref, dict) else str(ref)
                        active.add(aid)
            except Exception:
                pass
    return active


def preview_retention(workspace_id: str = "default",
                      policy: RetentionPolicy = None) -> RetentionPreview:
    """Preview what would be pruned. NEVER deletes. Always safe."""
    policy = policy or default_retention_policy()
    ws_dir = WS_ROOT / workspace_id
    preview = RetentionPreview(
        dry_run=True,
        workspace_id=workspace_id,
        policy=policy.as_dict(),
    )

    if not ws_dir.exists():
        preview.warnings.append(f"Workspace '{workspace_id}' not found")
        return preview

    active_artifacts = _get_active_artifact_ids(ws_dir)
    now = time.time()
    candidates = []
    blocked = []

    # Scan runs
    runs_dir = ws_dir / "runs"
    if runs_dir.is_dir():
        run_files = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        expired = []
        for rf in run_files:
            if not _is_safe_path(rf, ws_dir):
                blocked.append({"path": rf.name, "reason": "path_not_in_workspace"})
                continue
            age_days = (now - rf.stat().st_mtime) / 86400
            if age_days > policy.runs_max_age_days:
                expired.append(rf.name)

        # Keep last runs_max_count, prune the rest
        if len(run_files) > policy.runs_max_count:
            to_prune = run_files[:-policy.runs_max_count]
            for rf in to_prune:
                if rf not in [Path(runs_dir) / e for e in expired]:
                    expired.append(rf.name)

        for name in expired:
            candidates.append({"type": "run", "name": name})

    preview.candidate_counts["runs"] = len([c for c in candidates if c["type"] == "run"])

    # Scan traces
    trace_dir = ws_dir / "traces"
    if trace_dir.is_dir():
        trace_files = sorted(trace_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        for tf in trace_files:
            if not _is_safe_path(tf, ws_dir):
                blocked.append({"path": tf.name, "reason": "path_not_in_workspace"})
                continue
            age_days = (now - tf.stat().st_mtime) / 86400
            if age_days > policy.traces_max_age_days:
                candidates.append({"type": "trace", "name": tf.name})
    preview.candidate_counts["traces"] = len([c for c in candidates if c["type"] == "trace"])

    # Scan jobs
    jobs_dir = ws_dir / "jobs"
    if jobs_dir.is_dir():
        for jf in jobs_dir.iterdir():
            if not _is_safe_path(jf, ws_dir):
                blocked.append({"path": jf.name, "reason": "path_not_in_workspace"})
                continue
            age_days = (now - jf.stat().st_mtime) / 86400
            if age_days > policy.jobs_max_age_days:
                candidates.append({"type": "job", "name": jf.name})
    preview.candidate_counts["jobs"] = len([c for c in candidates if c["type"] == "job"])

    # Scan artifacts (only temp lifecycle, not active)
    art_dir = ws_dir / "artifacts"
    if art_dir.is_dir():
        for af in art_dir.iterdir():
            if not _is_safe_path(af, ws_dir):
                blocked.append({"path": af.name, "reason": "path_not_in_workspace"})
                continue
            age_days = (now - af.stat().st_mtime) / 86400
            try:
                record = json.loads(af.read_text()) if af.suffix == ".json" else {}
                lifecycle = record.get("lifecycle", record.get("scope", ""))
                art_id = record.get("artifact_id", af.stem)
            except Exception:
                lifecycle = "unknown"
                art_id = af.stem

            # Protected: active artifacts or non-temp lifecycle
            if art_id in active_artifacts:
                blocked.append({"path": af.name, "reason": "active_artifact", "artifact_id": art_id[:20]})
                continue
            if lifecycle not in ("temp", "quarantine"):
                continue

            if age_days > policy.artifacts_temp_max_age_days:
                candidates.append({"type": "artifact", "name": af.name})
    preview.candidate_counts["artifacts"] = len([c for c in candidates if c["type"] == "artifact"])

    preview.candidates = candidates
    preview.blocked_items = blocked
    preview.deleted_counts = {}  # dry-run: nothing deleted
    return preview


def apply_retention(workspace_id: str = "default",
                    policy: RetentionPolicy = None,
                    dry_run: bool = True,
                    confirm: bool = False) -> RetentionPreview:
    """Apply retention. Requires confirm=True for actual deletion.

    Args:
        dry_run: If True (default), preview only, nothing deleted.
        confirm: Must be True when dry_run=False. Safety guard.
    """
    preview = preview_retention(workspace_id, policy)
    preview.dry_run = dry_run

    if dry_run:
        preview.warnings.append("DRY RUN — no files were deleted. Use dry_run=False + confirm=True to apply.")
        return preview

    if not confirm:
        preview.warnings.append("BLOCKED: confirm=True is required when dry_run=False.")
        return preview

    # Actually delete
    ws_dir = WS_ROOT / workspace_id
    deleted = {"runs": 0, "traces": 0, "jobs": 0, "artifacts": 0}

    for candidate in preview.candidates:
        path = None
        ctype = candidate["type"]
        name = candidate["name"]
        try:
            if ctype == "run":
                path = ws_dir / "runs" / name
            elif ctype == "trace":
                path = ws_dir / "traces" / name
            elif ctype == "job":
                path = ws_dir / "jobs" / name
            elif ctype == "artifact":
                path = ws_dir / "artifacts" / name
            if path and path.exists() and _is_safe_path(path, ws_dir):
                path.unlink()
                deleted[ctype] = deleted.get(ctype, 0) + 1
        except Exception as e:
            preview.warnings.append(f"Failed to delete {name}: {str(e)[:100]}")

    preview.deleted_counts = deleted
    # Write audit record
    _write_audit(preview, workspace_id)
    return preview


def _write_audit(preview: RetentionPreview, workspace_id: str):
    """Write a retention audit record."""
    import uuid
    audit_dir = WS_ROOT / workspace_id / "runtime_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_id = uuid.uuid4().hex[:12]
    record = {
        "audit_id": audit_id,
        "created_at": __import__("datetime").datetime.now().isoformat(),
        "workspace_id": workspace_id,
        "dry_run": preview.dry_run,
        "confirmed": not preview.dry_run,
        "policy": preview.policy,
        "candidate_counts": preview.candidate_counts,
        "deleted_counts": preview.deleted_counts,
        "blocked_count": len(preview.blocked_items),
        "blocked_reasons": [b.get("reason", "") for b in preview.blocked_items[:20]],
        "warnings": preview.warnings[:20],
    }
    (audit_dir / f"{audit_id}.json").write_text(
        __import__("json").dumps(record, indent=2, ensure_ascii=False)
    )


def get_audits(workspace_id: str = "default") -> list:
    """List retention audit records."""
    audit_dir = WS_ROOT / workspace_id / "runtime_audits"
    if not audit_dir.is_dir():
        return []
    audits = []
    for af in sorted(audit_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if af.suffix == ".json":
            try:
                audits.append(json.loads(af.read_text()))
            except Exception:
                pass
    return audits[:50]


def get_audit(workspace_id: str, audit_id: str) -> dict:
    """Get a specific retention audit record."""
    audit_path = WS_ROOT / workspace_id / "runtime_audits" / f"{audit_id}.json"
    if audit_path.is_file():
        try:
            return json.loads(audit_path.read_text())
        except Exception:
            pass
    return {}
