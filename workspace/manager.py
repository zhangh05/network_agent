"""Workspace manager — CRUD for workspaces, state, runs, and artifact counts."""

import json
import os
import time
from typing import Optional
from pathlib import Path

from workspace.ids import validate_workspace_id, is_valid_workspace_id

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
    ws_id = validate_workspace_id(ws_id)
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
    """List all workspaces with frontend-friendly metadata and real counts."""
    ensure_workspace("default")
    workspaces = []
    if WS_ROOT.is_dir():
        dirs = [d for d in WS_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")]
        dirs.sort(key=lambda d: (0 if d.name == "default" else 1, _is_test_workspace(d.name), d.name))
        for d in dirs:
            if d.is_dir() and not d.name.startswith("."):
                # Skip non-workspace directories (e.g. _runtime/)
                if not is_valid_workspace_id(d.name):
                    continue
                runs_count = _count_runs(d.name)
                artifacts_count = _count_artifacts(d.name)
                knowledge_source_count = _count_knowledge_sources(d.name)
                workspaces.append({
                    "workspace_id": d.name,
                    "name": _workspace_display_name(d.name),
                    "created_at": _workspace_created_at(d.name),
                    "is_default": d.name == "default",
                    "runs_count": runs_count,
                    "artifacts_count": artifacts_count,
                    "memory_count": _count_memory(d.name),
                    "stats": {
                        "session_count": _count_sessions(d.name),
                        "artifact_count": artifacts_count,
                        "knowledge_source_count": knowledge_source_count,
                    },
                })
    return workspaces


def rename_workspace(old_id: str, new_id: str) -> dict:
    """Rename a workspace directory. Returns result dict."""
    old_id = validate_workspace_id(old_id)
    new_id = validate_workspace_id(new_id)
    old_path = WS_ROOT / old_id
    new_path = WS_ROOT / new_id
    if not old_path.is_dir():
        return {"ok": False, "error": "workspace not found"}
    if new_path.exists():
        return {"ok": False, "error": "target workspace already exists"}
    try:
        old_path.rename(new_path)
        # Update workspace.yaml
        yaml_path = new_path / "workspace.yaml"
        if yaml_path.is_file():
            lines = yaml_path.read_text().splitlines()
            updated = []
            for line in lines:
                if line.startswith("id: "):
                    updated.append(f"id: {new_id}")
                elif line.startswith("name: "):
                    updated.append(f"name: {new_id}")
                else:
                    updated.append(line)
            yaml_path.write_text("\n".join(updated) + "\n")
        # Update state.json
        state_path = new_path / "state.json"
        if state_path.is_file():
            s = json.loads(state_path.read_text())
            s["workspace_id"] = new_id
            s["name"] = new_id
            state_path.write_text(json.dumps(s, indent=2, ensure_ascii=False))
        return {"ok": True, "workspace_id": new_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_workspace(ws_id: str) -> dict:
    """Delete a workspace directory. Returns result dict."""
    ws_id = validate_workspace_id(ws_id)
    ws_path = WS_ROOT / ws_id
    if not ws_path.is_dir():
        return {"ok": False, "error": "workspace not found"}
    if ws_id == "default":
        return {"ok": False, "error": "cannot delete default workspace"}
    try:
        import shutil
        shutil.rmtree(ws_path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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


def _count_sessions(ws_id: str) -> int:
    """Count active session records when session storage exists."""
    ws_id = validate_workspace_id(ws_id)
    sessions_dir = WS_ROOT / ws_id / "sessions"
    if not sessions_dir.is_dir():
        return 0
    count = 0
    for path in sessions_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status", "active") == "active":
            count += 1
    return count


def _count_artifacts(ws_id: str) -> int:
    """Count artifact files across all artifact subdirs."""
    ws_id = validate_workspace_id(ws_id)
    artifacts_dir = WS_ROOT / ws_id / "artifacts"
    if not artifacts_dir.is_dir():
        return 0
    count = 0
    for sub in ["inputs", "outputs", "reports", "topology", "knowledge", "temp", "quarantine"]:
        sd = artifacts_dir / sub
        if sd.is_dir():
            count += len(list(sd.glob("*")))
    return count


def _count_knowledge_sources(ws_id: str) -> int:
    """Count knowledge sources from the knowledge store."""
    ws_id = validate_workspace_id(ws_id)
    sources = WS_ROOT / ws_id / "indexes" / "knowledge" / "sources.jsonl"
    if not sources.is_file():
        return 0
    count = 0
    try:
        for line in sources.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
    except Exception:
        return 0
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


def _workspace_display_name(ws_id: str) -> str:
    yaml_path = WS_ROOT / ws_id / "workspace.yaml"
    if yaml_path.is_file():
        try:
            for line in yaml_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip("'\"")
                    return name or ws_id
        except Exception:
            pass
    return ws_id


def _workspace_created_at(ws_id: str) -> str:
    yaml_path = WS_ROOT / ws_id / "workspace.yaml"
    if yaml_path.is_file():
        try:
            for line in yaml_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("created:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return ""


def _is_test_workspace(ws_id: str) -> int:
    test_markers = ("test", "e2e", "api_contract", "closure_", "ws_")
    return 1 if any(marker in ws_id for marker in test_markers) else 0
