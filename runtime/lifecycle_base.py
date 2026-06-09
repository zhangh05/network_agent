# runtime/lifecycle_base.py
"""Shared utilities for Retention and Archive — eliminates code duplication.

Both retention.py and archive.py share:
  - Path safety check (_is_safe_path)
  - Active artifact/reference detection (_get_active_refs)
  - Directory scanning with age/count filtering
  - Audit record writing

This module provides the common building blocks.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def is_safe_path(path: Path, ws_dir: Path) -> bool:
    """Verify path is within workspace — uses relative_to(), NOT string startswith.

    Prevents path traversal, symlink escape, and cross-workspace access.
    """
    try:
        resolved = path.resolve()
        ws_resolved = ws_dir.resolve()
        resolved.relative_to(ws_resolved)
        return True
    except (ValueError, OSError):
        return False


def get_active_refs(ws_dir: Path) -> set:
    """Get artifact/job IDs referenced by workspace state and recent runs.

    These IDs are protected — never pruned or archived.
    Combines refs from:
      - workspace state.json (current_run_id, current_artifacts, etc.)
      - recent run records (artifact_refs)
    """
    active = set()

    # From workspace state
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
        except Exception:
            pass

    # From recent runs
    runs_dir = ws_dir / "runs"
    if runs_dir.is_dir():
        for rf in list(runs_dir.iterdir())[:100]:
            if rf.suffix != ".json":
                continue
            try:
                record = json.loads(rf.read_text())
                art_refs = record.get("artifact_refs", [])
                if isinstance(art_refs, list):
                    for ref in art_refs:
                        aid = ref.get("artifact_id", ref) if isinstance(ref, dict) else str(ref)
                        if aid:
                            active.add(aid)
            except Exception:
                pass

    return active


def scan_directory(ws_dir: Path, subdir: str, max_age_days: int = 0,
                   max_count: int = 0, active_refs: Optional[set] = None,
                   check_is_file: bool = True) -> dict:
    """Scan a workspace subdirectory for candidates based on age and count.

    Args:
        ws_dir: Workspace root directory.
        subdir: Subdirectory name (e.g., "runs", "traces", "jobs").
        max_age_days: Maximum age in days before a file is a candidate. 0 = no age filter.
        max_count: Keep at most this many newest files; older ones become candidates. 0 = no count filter.
        active_refs: Set of IDs that should be protected from pruning.
        check_is_file: If True, skip non-file entries.

    Returns:
        Dict with keys: 'candidates' (list of names), 'blocked' (list of dicts).
    """
    target_dir = ws_dir / subdir
    if not target_dir.is_dir():
        return {"candidates": [], "blocked": []}

    now = time.time()
    candidates = []
    blocked = []
    active_refs = active_refs or set()

    # Sort by mtime (oldest first) for consistent count-based pruning
    entries = sorted(target_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    expired = []

    for entry in entries:
        if check_is_file and not entry.is_file():
            continue
        if not is_safe_path(entry, ws_dir):
            blocked.append({"path": entry.name, "reason": "path_outside_workspace"})
            continue
        # Active ref protection
        if entry.stem in active_refs:
            blocked.append({"path": entry.name, "reason": "active_ref"})
            continue

        # Age-based filter
        if max_age_days > 0:
            age_days = (now - entry.stat().st_mtime) / 86400
            if age_days > max_age_days:
                expired.append(entry.name)

    # Count-based filter (keep newest max_count)
    if max_count > 0 and len(entries) > max_count:
        for entry in entries[:-max_count]:
            if entry.name not in expired:
                expired.append(entry.name)

    candidates = list(dict.fromkeys(expired))  # dedupe preserving order
    return {"candidates": candidates, "blocked": blocked}


def write_audit(audit_dir: Path, record_type: str, workspace_id: str,
                dry_run: bool, policy: dict, candidate_counts: dict,
                result_counts: dict, warnings: list, blocked_count: int = 0) -> str:
    """Write an audit record to the workspace's runtime_audits directory.

    Args:
        audit_dir: Path to runtime_audits directory.
        record_type: "retention" or "archive".
        workspace_id: Workspace identifier.
        dry_run: Whether this was a dry run.
        policy: The policy used.
        candidate_counts: Counts of candidates by type.
        result_counts: Counts of deleted/moved items by type.
        warnings: List of warning strings.
        blocked_count: Number of blocked items.

    Returns:
        The audit_id.
    """
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_id = f"{record_type}_{uuid.uuid4().hex[:12]}"
    record = {
        "audit_id": audit_id,
        "type": record_type,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "confirmed": not dry_run,
        "policy": policy,
        "candidate_counts": candidate_counts,
        "result_counts": result_counts,
        "blocked_count": blocked_count,
        "warnings": warnings[:20],
    }
    (audit_dir / f"{audit_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
    return audit_id
