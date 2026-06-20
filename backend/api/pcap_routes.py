"""Pcap analysis API — upload, parse, filter, TCP seq alignment.

Backend route layer — delegates to agent.modules.pcap.core for all logic.
"""

import json
import hashlib
from pathlib import Path
from flask import request, jsonify

from agent.modules.pcap.core import (
    PCAP_SESSIONS,
    get_connection_groups,
    filter_by_5tuple,
    load_session_from_file,
    parse_pcap,
    safe_name,
    session_meta_path,
    tcp_stream_align,
)
from agent.modules.knowledge.ingestion import _ws_root


def _ensure_pcap_file_record(session_id: str, filename: str, filepath: str, total_pkts: int, groups: list, ws_id: str) -> str:
    """Create a file record for this pcap in the unified files system. Returns file_id."""
    from backend.api.files_routes import _source_dir, _now_iso
    file_id = f"f_{session_id}"
    record_dir = _source_dir(ws_id, "upload") / file_id
    record_dir.mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    rec = {
        "file_id": file_id, "type": "pcap",
        "title": filename, "filename": filename,
        "mime_type": "application/vnd.tcpdump.pcap",
        "size": Path(filepath).stat().st_size,
        "tags": [], "workspace_id": ws_id,
        "source": "upload", "indexed": False,
        "parent_id": None,
        "metadata": {
            "session_id": session_id,
            "filepath": filepath,
            "total_packets": total_pkts,
            "connection_count": len(groups),
        },
        "created_at": now, "updated_at": now,
    }
    (record_dir / "record.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return file_id


def register_pcap_routes(app):
    """Register pcap analysis API routes."""

    @app.route("/api/pcap/parse", methods=["POST"])
    def api_pcap_parse():
        ws_id = request.form.get("workspace_id", "default")
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no file"}), 400
        uploaded = request.files["file"]
        if not uploaded.filename:
            return jsonify({"ok": False, "error": "empty filename"}), 400

        safe = safe_name(uploaded.filename)
        up_dir = _ws_root() / ws_id / "files" / "upload"
        up_dir.mkdir(parents=True, exist_ok=True)
        target = up_dir / safe
        uploaded.save(str(target))

        packets = parse_pcap(str(target))
        if not packets:
            return jsonify({"ok": False, "error": "无法解析 pcap 文件"}), 400

        groups = get_connection_groups(packets)
        session_id = hashlib.md5(open(str(target), "rb").read(1024)).hexdigest()[:12]
        PCAP_SESSIONS[session_id] = {"filepath": str(target), "packets": packets, "groups": groups}

        meta = {
            "session_id": session_id, "filepath": str(target),
            "filename": safe, "total_packets": len(packets), "connections": groups,
        }
        session_meta_path(str(target)).write_text(json.dumps(meta, ensure_ascii=False))

        display_name = uploaded.filename or safe
        file_id = _ensure_pcap_file_record(session_id, display_name, str(target), len(packets), groups, ws_id)

        return jsonify({
            "ok": True, "session_id": session_id, "file_id": file_id,
            "filename": safe, "total_packets": len(packets),
            "connections": groups,
            "summary": f"共 {len(packets)} 个报文, {len(groups)} 条连接",
        })

    @app.route("/api/pcap/session/<session_id>", methods=["GET"])
    def api_pcap_session(session_id):
        session = PCAP_SESSIONS.get(session_id) or load_session_from_file(session_id)
        if not session:
            import os
            for ws_dir in _ws_root().iterdir():
                if not ws_dir.is_dir() or ws_dir.name.startswith("_"):
                    continue
                for src_name in ("upload", "agent"):
                    up = ws_dir / "files" / src_name
                    if not up.exists():
                        continue
                    for fname in os.listdir(str(up)):
                        if not fname.endswith(".meta.json"):
                            continue
                        try:
                            meta = json.loads((up / fname).read_text())
                            if meta.get("session_id") == session_id:
                                return jsonify({"ok": True, **meta})
                        except Exception:
                            continue
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify({
            "ok": True, "session_id": session_id,
            "filename": Path(session["filepath"]).name,
            "total_packets": len(session["packets"]),
            "connections": session.get("groups", []),
        })

    @app.route("/api/pcap/filter", methods=["POST"])
    def api_pcap_filter():
        data = request.get_json(force=True)
        session_id = data.get("session_id", "")
        session = PCAP_SESSIONS.get(session_id) or load_session_from_file(session_id)
        if not session:
            return jsonify({"ok": False, "error": "session not found"}), 404
        filtered = filter_by_5tuple(
            session["packets"], data.get("src", ""), data.get("sport", 0),
            data.get("dst", ""), data.get("dport", 0),
        )
        session["filtered"] = filtered
        return jsonify({
            "ok": True, "count": len(filtered),
            "packets": filtered[:500], "truncated": len(filtered) > 500,
        })

    @app.route("/api/pcap/align", methods=["POST"])
    def api_pcap_align():
        data = request.get_json(force=True)
        session_id = data.get("session_id", "")
        session = PCAP_SESSIONS.get(session_id) or load_session_from_file(session_id)
        if not session:
            return jsonify({"ok": False, "error": "session not found"}), 404
        packets = session.get("packets", [])
        if all(k in data for k in ("src", "sport", "dst", "dport")):
            filtered = filter_by_5tuple(
                packets, data.get("src", ""), data.get("sport", 0),
                data.get("dst", ""), data.get("dport", 0),
            )
        else:
            filtered = session.get("filtered", packets)
        result = tcp_stream_align(filtered)
        return jsonify({"ok": True, **result})
