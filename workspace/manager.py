"""Workspace manager — CRUD for workspaces, state, runs, and artifact counts."""

import json
import logging
import time
from typing import Optional
from pathlib import Path

from agent.runtime.utils import now_iso
from workspace.ids import validate_workspace_id, is_valid_workspace_id
from workspace.atomic_io import atomic_write_text, atomic_write_json, safe_read_json

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"
_LOG = logging.getLogger(__name__)

def ensure_workspace(ws_id: str = "default") -> str:
    """Ensure workspace dirs exist. Creates sys/workspace.yaml + sys/state.json if missing."""
    ws_id = validate_workspace_id(ws_id)
    ws = WS_ROOT / ws_id
    # Create all required subdirectories
    for d in [
        "runs",
        "sessions",
        "sys",
    ]:
        (ws / d).mkdir(parents=True, exist_ok=True)

    # Create FileStore, ArtifactStore, ContextStore, and RunStore directories.
    try:
        from storage.paths import ensure_workspace_storage_dirs
        ensure_workspace_storage_dirs(ws_id)
    except Exception:
        _LOG.warning("ensure_workspace_storage_dirs failed for ws=%s", ws_id, exc_info=True)

    # workspace.yaml
    yaml_path = ws / "sys" / "workspace.yaml"
    if not yaml_path.exists():
        try:
            yaml_text = (
                f"id: {ws_id}\n"
                f"name: {ws_id}\n"
                f"created: {time.time()}\n"
            )
            yaml_path.write_text(yaml_text, encoding="utf-8")
        except Exception:
            _LOG.warning("failed to write workspace.yaml for ws=%s", ws_id, exc_info=True)

    # state.json
    state_path = ws / "sys" / "state.json"
    if not state_path.exists():
        try:
            default_state = {
                "workspace_id": ws_id,
                "name": ws_id,
                "last_run_id": "",
                "last_intent": "",
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
            state_text = json.dumps(default_state, indent=2, ensure_ascii=False)
            state_path.write_text(state_text, encoding="utf-8")
        except Exception:
            _LOG.warning("failed to write state.json for ws=%s", ws_id, exc_info=True)

    return ws_id


def get_workspace_state(ws_id: str = "default") -> dict:
    """Get workspace state. Returns empty dict if not found."""
    ws_id = validate_workspace_id(ws_id)
    try:
        state = json.loads((WS_ROOT / ws_id / "sys" / "state.json").read_text(encoding="utf-8"))
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
            safe_patch[k] = v[:500] + "...[truncated]"
        else:
            safe_patch[k] = v

    s.update(safe_patch)
    s["updated_at"] = now_iso()
    s["runs_count"] = _count_runs(ws_id)

    try:
        state_text = json.dumps(s, indent=2, ensure_ascii=False)
        atomic_write_text(WS_ROOT / ws_id / "sys" / "state.json", state_text)
    except Exception:
        _LOG.warning("failed to persist state for ws=%s", ws_id, exc_info=True)
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
        yaml_path = new_path / "sys" / "workspace.yaml"
        if yaml_path.is_file():
            lines = yaml_path.read_text(encoding="utf-8").splitlines()
            updated = []
            for line in lines:
                if line.startswith("id: "):
                    updated.append(f"id: {new_id}")
                elif line.startswith("name: "):
                    updated.append(f"name: {new_id}")
                else:
                    updated.append(line)
            try:
                yaml_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
            except Exception:
                pass
        # Update state.json
        state_path = new_path / "sys" / "state.json"
        if state_path.is_file():
            try:
                s = json.loads(state_path.read_text(encoding="utf-8"))
                s["workspace_id"] = new_id
                s["name"] = new_id
                state_path.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
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


def batch_delete_workspaces(ws_ids: list) -> dict:
    """Delete multiple workspaces. Returns per-item results."""
    import shutil
    deleted = []
    failed = []
    for ws_id in ws_ids:
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            failed.append({"id": ws_id, "error": "invalid workspace id"})
            continue
        if ws_id == "default":
            failed.append({"id": ws_id, "error": "cannot delete default workspace"})
            continue
        ws_path = WS_ROOT / ws_id
        if not ws_path.is_dir():
            failed.append({"id": ws_id, "error": "workspace not found"})
            continue
        try:
            shutil.rmtree(ws_path)
            deleted.append(ws_id)
        except Exception as e:
            failed.append({"id": ws_id, "error": str(e)})
    return {"ok": True, "deleted": deleted, "failed": failed, "total": len(ws_ids)}


def get_workspace_runs(ws_id: str = "default") -> list:
    """Get all run records for a workspace."""
    ws_id = ensure_workspace(ws_id)
    runs_dir = WS_ROOT / ws_id / "runs"
    runs = []
    if runs_dir.is_dir():
        for f in sorted(runs_dir.glob("*.json"), reverse=True):
            if not _is_run_record_file(f):
                continue
            try:
                runs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                _LOG.debug("corrupt run file: %s", f, exc_info=True)
    return runs


def get_run(run_id: str, ws_id: str = "default") -> Optional[dict]:
    """Get a single run record by ID."""
    ws_id = validate_workspace_id(ws_id)
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _LOG.debug("corrupt run file: %s", path, exc_info=True)
    return None


# ─── Internal helpers ───

def _count_runs(ws_id: str) -> int:
    """Count actual run JSON files."""
    ws_id = validate_workspace_id(ws_id)
    runs_dir = WS_ROOT / ws_id / "runs"
    if runs_dir.is_dir():
        return len([p for p in runs_dir.glob("*.json") if _is_run_record_file(p)])
    return 0


def _is_run_record_file(path: Path) -> bool:
    name = path.name
    if not name.endswith(".json"):
        return False
    return not (
        name.endswith(".trace.json")
    )


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
    """Count artifact records from the artifact index."""
    ws_id = validate_workspace_id(ws_id)
    try:
        from artifacts.store import list_artifacts
        return len(list_artifacts(ws_id, include_deleted=False))
    except Exception:
        return 0


def _count_knowledge_sources(ws_id: str) -> int:
    """Count knowledge sources from ContextStore."""
    ws_id = validate_workspace_id(ws_id)
    try:
        from core.context.context_store import get_context_store
        store = get_context_store(ws_id)
        return store.count(item_type="knowledge_source")
    except Exception:
        return 0


def _count_memory(ws_id: str) -> int:
    """Count memory records from ContextStore."""
    ws_id = validate_workspace_id(ws_id)
    try:
        from core.context.context_store import get_context_store
        store = get_context_store(ws_id)
        return store.count(item_type="memory_hit")
    except Exception:
        return 0


def _workspace_display_name(ws_id: str) -> str:
    yaml_path = WS_ROOT / ws_id / "sys" / "workspace.yaml"
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
    yaml_path = WS_ROOT / ws_id / "sys" / "workspace.yaml"
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
