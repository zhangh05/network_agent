"""Artifact store — save input/output/reports to workspace."""

import json, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

def save_artifact(ws_id, run_id, artifact_type, content, title="", sensitivity="internal"):
    from workspace.manager import ensure_workspace
    ensure_workspace(ws_id)
    art_id = f"{artifact_type}_{int(time.time())}"
    art_dir = WS_ROOT / ws_id / "artifacts" / artifact_type
    art_dir.mkdir(parents=True, exist_ok=True)
    art_path = art_dir / f"{art_id}.json" if isinstance(content, dict) else art_dir / f"{art_id}.txt"
    if isinstance(content, (dict, list)):
        art_path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
    else:
        art_path.write_text(str(content))
    meta = {"artifact_id": art_id, "workspace_id": ws_id, "run_id": run_id,
            "artifact_type": artifact_type, "path": str(art_path.relative_to(WS_ROOT / ws_id)),
            "title": title, "summary": str(content)[:200] if isinstance(content,str) else title,
            "sensitivity": sensitivity, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (art_dir / f"{art_id}_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return art_id

def get_artifact(ws_id, artifact_id):
    for art_type in ["inputs","outputs","reports","temp"]:
        art_dir = WS_ROOT / ws_id / "artifacts" / art_type
        meta_path = art_dir / f"{artifact_id}_meta.json"
        data_path = art_dir / f"{artifact_id}.json"
        if not data_path.is_file():
            data_path = art_dir / f"{artifact_id}.txt"
        if meta_path.is_file():
            return {"meta": json.loads(meta_path.read_text()),
                    "data": json.loads(data_path.read_text()) if data_path.suffix==".json" and data_path.is_file() else (data_path.read_text() if data_path.is_file() else "")}
    return None

def list_artifacts(ws_id, run_id=None, artifact_type=None):
    results = []
    ensure = Path(__file__).resolve().parent
    for art_type in ([artifact_type] if artifact_type else ["inputs","outputs","reports","temp"]):
        art_dir = WS_ROOT / ws_id / "artifacts" / art_type
        if not art_dir.is_dir(): continue
        for f in sorted(art_dir.glob("*_meta.json"), reverse=True):
            try:
                meta = json.loads(f.read_text())
                if run_id and meta.get("run_id") != run_id: continue
                results.append(meta)
            except: pass
    return results

def ensure():
    from workspace.manager import ensure_workspace as _e; _e()
