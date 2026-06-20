# agent/modules/pcap/service.py
"""PCAP analysis module service.

Business logic for PCAP parsing, session management, filtering, and TCP alignment.
Tool handlers in canonical_registry.py call this service instead of embedding logic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def resolve_workspace_path(workspace_id: str, filepath: str) -> Path:
    """Resolve a workspace-relative filepath with path traversal protection."""
    from agent.modules.knowledge.ingestion import _ws_root

    root = (_ws_root() / (workspace_id or "default")).resolve()
    candidate = Path(filepath)
    if not candidate.is_absolute():
        candidate = root / filepath
    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("filepath must stay inside the workspace")
    return resolved


def pcap_session_id_for(path) -> str:
    """Generate a deterministic session ID from the first 1024 bytes of a file."""
    with open(str(path), "rb") as fh:
        return hashlib.md5(fh.read(1024)).hexdigest()[:12]


def parse_pcap_file(workspace_id: str, filepath: str) -> dict:
    """Parse a workspace PCAP file and create/refresh a PCAP session."""
    from backend.api.pcap_routes import (
        _PCAP_SESSIONS,
        _get_connection_groups,
        _parse_pcap,
        _session_meta_path,
    )

    if not filepath:
        return {
            "ok": False,
            "tool_id": "network.pcap.parse",
            "status": "failed",
            "summary": "需要提供 workspace 内的 PCAP 文件路径。",
            "errors": ["missing_filepath"],
        }
    try:
        path = resolve_workspace_path(workspace_id, filepath)
    except Exception as exc:
        return {
            "ok": False,
            "tool_id": "network.pcap.parse",
            "status": "failed",
            "summary": str(exc)[:200],
            "errors": ["invalid_filepath"],
        }
    if not path.exists() or not path.is_file():
        return {
            "ok": False,
            "tool_id": "network.pcap.parse",
            "status": "failed",
            "summary": f"PCAP 文件不存在：{filepath}",
            "errors": ["file_not_found"],
        }
    packets = _parse_pcap(str(path))
    if not packets:
        return {
            "ok": False,
            "tool_id": "network.pcap.parse",
            "status": "failed",
            "summary": "无法解析 PCAP 文件，可能文件不存在、格式不支持或 scapy 不可用。",
            "errors": ["pcap_parse_failed"],
        }
    groups = _get_connection_groups(packets)
    session_id = pcap_session_id_for(path)
    _PCAP_SESSIONS[session_id] = {"filepath": str(path), "packets": packets, "groups": groups}
    meta = {
        "session_id": session_id,
        "filepath": str(path),
        "filename": path.name,
        "total_packets": len(packets),
        "connections": groups,
    }
    _session_meta_path(str(path)).write_text(json.dumps(meta, ensure_ascii=False))
    return {"ok": True, "tool_id": "network.pcap.parse", "status": "succeeded",
            "summary": f"共解析 {len(packets)} 个报文，识别 {len(groups)} 条连接。", **meta}


def get_pcap_session(session_id: str) -> dict:
    """Retrieve an existing PCAP session."""
    from backend.api.pcap_routes import _PCAP_SESSIONS, _load_session_from_file

    session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
    if not session:
        return {"ok": False, "tool_id": "network.pcap.session", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    return {
        "ok": True,
        "tool_id": "network.pcap.session",
        "status": "succeeded",
        "summary": f"PCAP session 有 {len(session.get('packets', []))} 个报文。",
        "session_id": session_id,
        "filename": Path(session["filepath"]).name,
        "total_packets": len(session.get("packets", [])),
        "connections": session.get("groups", []),
    }


def filter_pcap_session(session_id: str, src: str = "", sport: int = 0,
                         dst: str = "", dport: int = 0) -> dict:
    """Filter PCAP session packets by 5-tuple."""
    from backend.api.pcap_routes import _PCAP_SESSIONS, _filter_by_5tuple, _load_session_from_file

    session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
    if not session:
        return {"ok": False, "tool_id": "network.pcap.filter", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    filtered = _filter_by_5tuple(session.get("packets", []), src, sport, dst, dport)
    session["filtered"] = filtered
    return {
        "ok": True,
        "tool_id": "network.pcap.filter",
        "status": "succeeded",
        "summary": f"匹配到 {len(filtered)} 个报文。",
        "count": len(filtered),
        "packets": filtered[:500],
        "truncated": len(filtered) > 500,
    }


def align_pcap_tcp(session_id: str, src: str = "", sport: int = 0,
                    dst: str = "", dport: int = 0,
                    use_filter: bool = False) -> dict:
    """TCP sequence number / ACK alignment analysis."""
    from backend.api.pcap_routes import (
        _PCAP_SESSIONS,
        _filter_by_5tuple,
        _load_session_from_file,
        _tcp_stream_align,
    )

    session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
    if not session:
        return {"ok": False, "tool_id": "network.pcap.align", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])
    if use_filter:
        packets = _filter_by_5tuple(packets, src, sport, dst, dport)
    else:
        packets = session.get("filtered", packets)
    result = _tcp_stream_align(packets)
    return {
        "ok": True,
        "tool_id": "network.pcap.align",
        "status": "succeeded",
        "summary": f"完成 TCP 序列对齐，发现 {len(result.get('anomalies', []))} 个异常。",
        **result,
    }
