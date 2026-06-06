"""Workspace manager — CRUD for workspaces."""

import json, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

def ensure_workspace(ws_id="default"):
    ws = WS_ROOT / ws_id
    for d in ["runs", "artifacts/inputs", "artifacts/outputs", "artifacts/reports", "artifacts/temp"]:
        (ws / d).mkdir(parents=True, exist_ok=True)
    yaml_path = ws / "workspace.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(f"id: {ws_id}\nname: {ws_id}\ncreated: {time.time()}\nactive_module: config_translation\n")
    state_path = ws / "state.json"
    if not state_path.exists():
        state_path.write_text(json.dumps({"workspace_id": ws_id, "last_run_id": "", "last_intent": "", "updated_at": ""}))
    return ws_id

def get_workspace_state(ws_id="default"):
    ensure_workspace(ws_id)
    try:
        return json.loads((WS_ROOT / ws_id / "state.json").read_text())
    except: return {}

def update_workspace_state(ws_id, patch):
    ensure_workspace(ws_id)
    s = get_workspace_state(ws_id)
    s.update(patch)
    s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (WS_ROOT / ws_id / "state.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))

def list_workspaces():
    ws = []
    if WS_ROOT.is_dir():
        for d in sorted(WS_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                ws.append({"workspace_id": d.name, "runs": len(list((d/"runs").glob("*.json"))) if (d/"runs").is_dir() else 0})
    return ws

def get_workspace_runs(ws_id="default"):
    ensure_workspace(ws_id)
    runs_dir = WS_ROOT / ws_id / "runs"
    runs = []
    if runs_dir.is_dir():
        for f in sorted(runs_dir.glob("*.json"), reverse=True):
            try: runs.append(json.loads(f.read_text()))
            except: pass
    return runs

def get_run(run_id, ws_id="default"):
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.json"
    if path.is_file():
        return json.loads(path.read_text())
    return None
