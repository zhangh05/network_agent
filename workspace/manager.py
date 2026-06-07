"""Workspace manager — CRUD for workspaces, state, runs, and artifact counts."""

import json
import os
import time
from typing import Optional
from pathlib import Path

from workspace.ids import validate_workspace_id

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def ensure_workspace(ws_id: str = "default") -> str:
    """Ensure workspace dirs exist. Creates workspace.yaml + state.json if missing."""
    ws_id = validate_workspace_id(ws_id)
    ws = WS_ROOT / ws_id
    # Create all required subdirectories
    for d in [
        "runs",
        "sessions",
        "artifacts/inputs", "artifacts/outputs", "artifacts/reports",
        "artifacts/topology", "artifacts/knowledge", "artifacts/temp",
        "artifacts/quarantine",
        "indexes",
    ]:
        (ws / d).mkdir(parents=True, exist_ok=True)

    # workspace.yaml
    yaml_path = ws / "workspace.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(
            f"id: {ws_id}\n"
            f"name: {ws_id}\n"
            f"created: {time.time()}\n"
            f"active_module: config_translation\n"
        )

    # state.json
    state_path = ws / "state.json"
    if not state_path.exists():
        default_state = {
            "workspace_id": ws_id,
            "name": ws_id,
            "active_module": "config_translation",
            "last_run_id": "",
            "last_intent": "",
            "last_active_module": "",
            "last_result_summary": "",
            "last_result_counts": {},
            "last_manual_review_samples": [],
            "last_unsupported_samples": [],
            "last_audit_summary": {},
            "current_files": [],
            "current_artifacts": [],
            "llm_metadata": {},
            "runs_count": 0,
            "memory_count": 0,
            "artifacts_count": 0,
            "updated_at": "",
        }
        state_path.write_text(json.dumps(default_state, indent=2, ensure_ascii=False))

    return ws_id


def get_workspace_state(ws_id: str = "default") -> dict:
    """Get workspace state. Returns empty dict if not found."""
    ws_id = ensure_workspace(ws_id)
    try:
        state = json.loads((WS_ROOT / ws_id / "state.json").read_text())
        # Enrich with live counts
        state["runs_count"] = _count_runs(ws_id)
        state["memory_count"] = _count_memory(ws_id)
        state["artifacts_count"] = _count_artifacts(ws_id)
        return state
    except Exception:
        return {}


def update_workspace_state(ws_id: str, patch: dict) -> dict:
    """Update workspace state with a patch dict. Returns updated state."""
    ws_id = ensure_workspace(ws_id)
    s = get_workspace_state(ws_id)

    # Merge patch — never store full configs
    safe_patch = {}
    for k, v in patch.items():
        if isinstance(v, str) and len(v) > 500 and k not in ("last_result_summary",):
            # Truncate large strings (except summary)
            safe_patch[k] = v[:500]
        else:
            safe_patch[k] = v

    s.update(safe_patch)
    s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    s["runs_count"] = _count_runs(ws_id)

    (WS_ROOT / ws_id / "state.json").write_text(
        json.dumps(s, indent=2, ensure_ascii=False)
    )
    return s


def list_workspaces() -> list:
    """List all workspaces with real counts."""
    workspaces = []
    if WS_ROOT.is_dir():
        for d in sorted(WS_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                workspaces.append({
                    "workspace_id": d.name,
                    "runs_count": _count_runs(d.name),
                    "artifacts_count": _count_artifacts(d.name),
                    "memory_count": _count_memory(d.name),
                })
    return workspaces


def get_workspace_runs(ws_id: str = "default") -> list:
    """Get all run records for a workspace."""
    ws_id = ensure_workspace(ws_id)
    runs_dir = WS_ROOT / ws_id / "runs"
    runs = []
    if runs_dir.is_dir():
        for f in sorted(runs_dir.glob("*.json"), reverse=True):
            if f.name.endswith(".trace.json"):
                continue
            try:
                runs.append(json.loads(f.read_text()))
            except Exception:
                pass
    return runs


def get_run(run_id: str, ws_id: str = "default") -> Optional[dict]:
    """Get a single run record by ID."""
    ws_id = validate_workspace_id(ws_id)
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


# ─── Internal helpers ───

def _count_runs(ws_id: str) -> int:
    """Count actual run JSON files."""
    ws_id = validate_workspace_id(ws_id)
    runs_dir = WS_ROOT / ws_id / "runs"
    if runs_dir.is_dir():
        return len([p for p in runs_dir.glob("*.json") if not p.name.endswith(".trace.json")])
    return 0


def _count_artifacts(ws_id: str) -> int:
    """Count artifact files across all artifact subdirs."""
    ws_id = validate_workspace_id(ws_id)
    artifacts_dir = WS_ROOT / ws_id / "artifacts"
    if not artifacts_dir.is_dir():
        return 0
    count = 0
    for sub in ["inputs", "outputs", "reports", "temp"]:
        sd = artifacts_dir / sub
        if sd.is_dir():
            count += len(list(sd.glob("*")))
    return count


def _count_memory(ws_id: str) -> int:
    """Count memory records for a project."""
    ws_id = validate_workspace_id(ws_id)
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        return store.count(project_id=ws_id)
    except Exception:
        return 0
