# agent/modules/pcap/service.py
"""PCAP analysis module service.

Business logic for PCAP parsing, session management, filtering, and TCP alignment.
All core logic lives in agent.modules.pcap.core — no backend route dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.modules.pcap.core import (
    PCAP_SESSIONS,
    filter_by_5tuple,
    get_connection_groups,
    parse_pcap,
    pcap_session_id_for,
    tcp_stream_align,
)


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


def parse_pcap_file(workspace_id: str, filepath: str = "", file_id: str = "") -> dict:
    """Parse a workspace PCAP file and create/refresh a PCAP session."""
    path = None
    source_file_id = file_id or ""

    if file_id:
        try:
            from storage.file_store import resolve_file_path as _resolve
            path = _resolve(workspace_id, file_id)
        except Exception as exc:
            return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                    "summary": str(exc)[:200], "errors": ["invalid_file_id"]}
    elif filepath:
        try:
            path = resolve_workspace_path(workspace_id, filepath)
        except Exception as exc:
            return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                    "summary": str(exc)[:200], "errors": ["invalid_filepath"]}
    else:
        return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                "summary": "需要提供 file_id 或 filepath。", "errors": ["missing_filepath"]}

    if not path.exists() or not path.is_file():
        return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                "summary": f"PCAP 文件不存在：{filepath or file_id}", "errors": ["file_not_found"]}

    packets = parse_pcap(str(path))
    if not packets:
        return {
            "ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
            "summary": "无法解析 PCAP 文件，可能文件不存在、格式不支持或 scapy 不可用。",
            "errors": ["pcap_parse_failed"],
        }
    groups = get_connection_groups(packets)
    sid = pcap_session_id_for(path)
    PCAP_SESSIONS[sid] = {"filepath": str(path), "packets": packets, "groups": groups}
    meta = {
        "session_id": sid, "filepath": str(path), "filename": path.name,
        "total_packets": len(packets), "connections": groups,
    }
    # Save result artifacts (non-fatal)
    artifacts = []
    try:
        from artifacts.store import save_artifact
        session_art = save_artifact(
            workspace_id=workspace_id, content=json.dumps(meta, ensure_ascii=False, indent=2),
            artifact_type="pcap_session", title=f"PCAP session: {path.name}",
            scope="workspace", sensitivity="internal",
            metadata={"source_file_id": source_file_id, "pcap_session_id": sid, "storage_managed": True},
        )
        if session_art:
            artifacts.append({"artifact_id": session_art.artifact_id, "file_id": session_art.file_id,
                              "artifact_type": "pcap_session"})
        conn_art = save_artifact(
            workspace_id=workspace_id, content=json.dumps(groups, ensure_ascii=False, indent=2),
            artifact_type="pcap_connections", title=f"PCAP connections: {path.name}",
            scope="workspace", sensitivity="internal",
            metadata={"source_file_id": source_file_id, "pcap_session_id": sid, "storage_managed": True},
        )
        if conn_art:
            artifacts.append({"artifact_id": conn_art.artifact_id, "file_id": conn_art.file_id,
                              "artifact_type": "pcap_connections"})
    except Exception:
        pass

    # ReferenceIndex: link source file to pcap session (non-fatal)
    if source_file_id:
        try:
            from storage.reference_index import add_reference
            add_reference(workspace_id, source_file_id, "pcap_session", sid, "source")
        except Exception:
            pass

    result = {"ok": True, "tool_id": "pcap.analysis.run", "status": "succeeded",
              "summary": f"共解析 {len(packets)} 个报文，识别 {len(groups)} 条连接。", **meta}
    if artifacts:
        result["artifacts"] = artifacts
    return result


def get_pcap_session(session_id: str) -> dict:
    """Retrieve an existing PCAP session."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    return {
        "ok": True, "tool_id": "pcap.analysis.run", "status": "succeeded",
        "summary": f"PCAP session 有 {len(session.get('packets', []))} 个报文。",
        "session_id": session_id, "filename": Path(session["filepath"]).name,
        "total_packets": len(session.get("packets", [])),
        "connections": session.get("groups", []),
    }


def filter_pcap_session(session_id: str, src: str = "", sport: int = 0,
                         dst: str = "", dport: int = 0) -> dict:
    """Filter PCAP session packets by 5-tuple."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    filtered = filter_by_5tuple(session.get("packets", []), src, sport, dst, dport)
    session["filtered"] = filtered
    return {
        "ok": True, "tool_id": "pcap.analysis.run", "status": "succeeded",
        "summary": f"匹配到 {len(filtered)} 个报文。",
        "count": len(filtered), "packets": filtered[:500], "truncated": len(filtered) > 500,
    }


def align_pcap_tcp(session_id: str, src: str = "", sport: int = 0,
                    dst: str = "", dport: int = 0,
                    use_filter: bool = False) -> dict:
    """TCP sequence number / ACK alignment analysis."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])
    if use_filter:
        packets = filter_by_5tuple(packets, src, sport, dst, dport)
    else:
        packets = session.get("filtered", packets)
    result = tcp_stream_align(packets)
    return {
        "ok": True, "tool_id": "pcap.analysis.run", "status": "succeeded",
        "summary": f"完成 TCP 序列对齐，发现 {len(result.get('anomalies', []))} 个异常。",
        **result,
    }


def run_pcap_analysis(
    action: str, *, workspace_id: str = "default", filepath: str = "",
    file_id: str = "", session_id: str = "", src: str = "", sport: int = 0,
    dst: str = "", dport: int = 0, use_filter: bool = False, **kwargs,
) -> dict:
    """Unified PCAP analysis dispatcher."""
    action = (action or "").strip()
    if action == "parse":
        return parse_pcap_file(workspace_id, filepath=filepath, file_id=file_id)
    if action == "session":
        return get_pcap_session(session_id)
    if action == "filter":
        return filter_pcap_session(session_id, src=src, sport=sport, dst=dst, dport=dport)
    if action == "align":
        return align_pcap_tcp(session_id, src=src, sport=sport, dst=dst, dport=dport, use_filter=use_filter)
    return {
        "ok": False, "tool_id": "pcap.analysis.run", "status": "failed",
        "summary": f"unsupported pcap action: {action}", "errors": ["unsupported_action"],
    }
