# agent/modules/pcap/service.py
"""PCAP analysis module service.

Business logic for PCAP parsing, session management, filtering, and TCP alignment.
All core logic lives in agent.modules.pcap.core — no backend route dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.runtime.utils import now_iso
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
    from workspace.ids import validate_workspace_id

    workspace_id = validate_workspace_id(workspace_id)
    root = (_ws_root() / workspace_id).resolve()
    candidate = Path(filepath)
    if not candidate.is_absolute():
        candidate = root / filepath
    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("filepath must stay inside the workspace")
    return resolved


def parse_pcap_file(workspace_id: str, filepath: str = "", file_id: str = "",
                    run_id: str = "", session_id: str = "") -> dict:
    """Parse a workspace PCAP file and create/refresh a PCAP session."""
    path = None
    source_file_id = file_id or ""

    if file_id:
        try:
            from storage.file_store import resolve_file_path as _resolve
            path = _resolve(workspace_id, file_id)
        except Exception as exc:
            return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                    "summary": str(exc)[:200], "errors": ["invalid_file_id"]}
    elif filepath:
        try:
            path = resolve_workspace_path(workspace_id, filepath)
        except Exception as exc:
            return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                    "summary": str(exc)[:200], "errors": ["invalid_filepath"]}
    else:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "需要提供 file_id 或 filepath。", "errors": ["missing_filepath"]}

    if not path.exists() or not path.is_file():
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": f"PCAP 文件不存在：{filepath or file_id}", "errors": ["file_not_found"]}

    packets = parse_pcap(str(path))
    if not packets:
        return {
            "ok": False, "tool_id": "pcap.manage", "status": "failed",
            "summary": "无法解析 PCAP 文件，可能文件不存在、格式不支持或 scapy 不可用。",
            "errors": ["pcap_parse_failed"],
        }
    groups = get_connection_groups(packets)
    sid = pcap_session_id_for(path)
    PCAP_SESSIONS[sid] = {"filepath": str(path), "packets": packets, "groups": groups}
    protocol_counts = _protocol_counts(groups)
    meta = {
        "session_id": sid, "filepath": str(path), "filename": path.name,
        "total_packets": len(packets), "protocol_counts": protocol_counts, "connections": groups,
    }
    # Persist session to index for recovery after memory reset
    try:
        from storage.paths import workspace_root
        idx_dir = workspace_root(workspace_id) / "index"
        idx_dir.mkdir(parents=True, exist_ok=True)
        idx_path = idx_dir / "pcap_sessions.jsonl"
        record = {"session_id": sid, "filepath": str(path), "filename": path.name,
                  "total_packets": len(packets), "connection_count": len(groups),
                  "protocol_counts": protocol_counts, "connections": groups}
        with open(idx_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

    # Save result artifacts (non-fatal)
    artifacts = []
    try:
        from artifacts.store import save_artifact
        session_art = save_artifact(
            workspace_id=workspace_id, content=json.dumps(meta, ensure_ascii=False, indent=2),
            artifact_type="pcap_session", title=f"PCAP session: {path.name}",
            scope="workspace", sensitivity="internal", run_id=run_id, session_id=session_id,
            metadata={"source_file_id": source_file_id, "pcap_session_id": sid, "storage_managed": True},
        )
        if session_art:
            artifacts.append({"artifact_id": session_art.artifact_id, "file_id": session_art.file_id,
                              "artifact_type": "pcap_session"})
        conn_art = save_artifact(
            workspace_id=workspace_id, content=json.dumps(groups, ensure_ascii=False, indent=2),
            artifact_type="pcap_connections", title=f"PCAP connections: {path.name}",
            scope="workspace", sensitivity="internal", run_id=run_id, session_id=session_id,
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

    result = {"ok": True, "tool_id": "pcap.manage", "status": "succeeded",
              "summary": f"共解析 {len(packets)} 个报文，识别 {len(groups)} 条连接。", **meta}
    if artifacts:
        result["artifacts"] = artifacts
    return result


def delete_pcap_session(session_id: str, workspace_id: str = "") -> dict:
    """Physically remove a PCAP session from memory and persistent index."""
    # Remove from in-memory cache
    PCAP_SESSIONS.pop(session_id, None)

    # Physically remove from index (rewrite JSONL without the session)
    try:
        from storage.paths import workspace_root
        import json
        idx_path = workspace_root(workspace_id) / "index" / "pcap_sessions.jsonl"
        if idx_path.exists():
            lines = idx_path.read_text().strip().split("\n")
            kept = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                if rec.get("session_id") == session_id:
                    continue
                kept.append(line)
            idx_path.write_text("\n".join(kept) + ("\n" if kept else ""))
    except Exception:
        pass

    return {"ok": True, "session_id": session_id}


def list_pcap_sessions(workspace_id: str = "", limit: int = 20) -> list[dict]:
    """List recent PCAP sessions from the persistent index."""
    try:
        from storage.paths import workspace_root
        import json
        idx_path = workspace_root(workspace_id) / "index" / "pcap_sessions.jsonl"
        if not idx_path.exists():
            return []
        sessions: list[dict] = []
        seen = set()
        deleted = set()
        for line in reversed(idx_path.read_text(encoding="utf-8").strip().split("\n")):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                sid = rec.get("session_id", "")
                if not sid:
                    continue
                # Skip tombstoned sessions
                if rec.get("deleted"):
                    deleted.add(sid)
                    continue
                if sid not in seen and sid not in deleted:
                    seen.add(sid)
                    sessions.append({
                        "session_id": sid,
                        "filename": rec.get("filename", ""),
                        "total_packets": rec.get("total_packets", 0),
                        "connection_count": rec.get("connection_count", 0),
                        "protocol_counts": rec.get("protocol_counts", _protocol_counts(rec.get("connections", []))),
                        "connections": rec.get("connections", []),
                    })
                if len(sessions) >= limit:
                    break
            except json.JSONDecodeError:
                continue
        return sessions
    except Exception:
        return []


def get_pcap_session(session_id: str, workspace_id: str = "") -> dict:
    """Retrieve an existing PCAP session."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        # Try recovering from persisted index
        try:
            import json
            from storage.paths import workspace_root
            idx_path = workspace_root(workspace_id) / "index" / "pcap_sessions.jsonl"
            if idx_path.exists():
                for line in idx_path.read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec.get("session_id") == session_id:
                        filepath = rec.get("filepath", "")
                        packets = parse_pcap(filepath) if filepath else []
                        groups = get_connection_groups(packets) if packets else rec.get("connections", [])
                        if packets:
                            PCAP_SESSIONS[session_id] = {
                                "filepath": filepath,
                                "packets": packets,
                                "groups": groups,
                            }
                        return {
                            "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
                            "summary": f"PCAP session 有 {rec.get('total_packets', 0)} 个报文 (从 index 恢复)。",
                            "session_id": session_id, "filename": rec.get("filename", ""),
                            "total_packets": len(packets) if packets else rec.get("total_packets", 0),
                            "protocol_counts": _protocol_counts(groups),
                            "connections": groups,
                        }
        except Exception:
            pass
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"PCAP session 有 {len(session.get('packets', []))} 个报文。",
        "session_id": session_id, "filename": Path(session["filepath"]).name,
        "total_packets": len(session.get("packets", [])),
        "protocol_counts": _protocol_counts(session.get("groups", [])),
        "connections": session.get("groups", []),
    }


def _protocol_counts(groups: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for group in groups or []:
        proto = str(group.get("proto_name") or group.get("protocol") or "UNKNOWN").upper()
        counts[proto] = counts.get(proto, 0) + 1
    return counts


def filter_pcap_session(session_id: str, src: str = "", sport: int = 0,
                         dst: str = "", dport: int = 0,
                         workspace_id: str = "") -> dict:
    """Filter PCAP session packets by 5-tuple."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        get_pcap_session(session_id, workspace_id=workspace_id)
        session = PCAP_SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    filtered = filter_by_5tuple(session.get("packets", []), src, sport, dst, dport)
    session["filtered"] = filtered
    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"匹配到 {len(filtered)} 个报文。",
        "count": len(filtered), "packets": filtered[:500], "truncated": len(filtered) > 500,
    }


def align_pcap_tcp(session_id: str, src: str = "", sport: int = 0,
                    dst: str = "", dport: int = 0,
                    use_filter: bool = False,
                    workspace_id: str = "") -> dict:
    """TCP sequence number / ACK alignment analysis."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        get_pcap_session(session_id, workspace_id=workspace_id)
        session = PCAP_SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])
    if use_filter:
        packets = filter_by_5tuple(packets, src, sport, dst, dport)
    else:
        packets = session.get("filtered", packets)
    result = tcp_stream_align(packets)
    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"完成 TCP 序列对齐，发现 {len(result.get('anomalies', []))} 个异常。",
        **result,
    }


def run_pcap_analysis(
    action: str, *, workspace_id: str = "", filepath: str = "",
    file_id: str = "", session_id: str = "", src: str = "", sport: int = 0,
    dst: str = "", dport: int = 0, protocol: str = "",
    use_filter: bool = False,
    run_id: str = "", agent_session_id: str = "", **kwargs,
) -> dict:
    """Unified PCAP analysis dispatcher."""
    action = (action or "").strip()
    if action == "parse":
        return parse_pcap_file(workspace_id, filepath=filepath, file_id=file_id,
                               run_id=run_id, session_id=agent_session_id)
    if action == "summary":
        return _pcap_summary(session_id, workspace_id=workspace_id)
    if action == "filter":
        return _pcap_filter(session_id, src=src, sport=sport, dst=dst, dport=dport,
                            protocol=protocol, workspace_id=workspace_id)
    if action == "protocol":
        return _pcap_protocol(session_id, workspace_id=workspace_id)
    if action == "align":
        return align_pcap_tcp(session_id, src=src, sport=sport, dst=dst, dport=dport, use_filter=use_filter, workspace_id=workspace_id)
    if action == "scan":
        return _pcap_scan(session_id, src=src, dst=dst, workspace_id=workspace_id)
    return {
        "ok": False, "tool_id": "pcap.manage", "status": "failed",
        "summary": f"unsupported pcap action: {action}", "errors": ["unsupported_action"],
    }


def _get_session(session_id: str, workspace_id: str) -> dict | None:
    """Get or recover a PCAP session."""
    session = PCAP_SESSIONS.get(session_id)
    if not session:
        get_pcap_session(session_id, workspace_id=workspace_id)
        session = PCAP_SESSIONS.get(session_id)
    return session


def _pcap_summary(session_id: str, workspace_id: str = "") -> dict:
    """Overview statistics for a PCAP session."""
    session = _get_session(session_id, workspace_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])
    groups = session.get("groups", [])
    proto_counts = _protocol_counts(groups)

    # Time range
    times = []
    for pkt in packets:
        if hasattr(pkt, 'time'):
            times.append(float(pkt.time))
    time_range = f"{min(times):.1f}s - {max(times):.1f}s" if len(times) >= 2 else "unknown"

    # Unique IPs
    ips = set()
    for pkt in packets:
        if hasattr(pkt, '__getitem__'):
            try:
                if 'IP' in pkt:
                    ips.add(pkt['IP'].src)
                    ips.add(pkt['IP'].dst)
            except Exception:
                pass

    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"PCAP总览: {len(packets)}报文, {len(groups)}连接, {len(ips)}个IP。",
        "total_packets": len(packets),
        "connections": len(groups),
        "protocol_counts": proto_counts,
        "unique_ips": len(ips),
        "time_range": time_range,
        "filename": Path(session.get("filepath", "")).name,
        "top_protocol": max(proto_counts, key=proto_counts.get) if proto_counts else "N/A",
    }


def _pcap_filter(session_id: str, src: str = "", sport: int = 0,
                  dst: str = "", dport: int = 0,
                  protocol: str = "", workspace_id: str = "") -> dict:
    """Multi-dimensional PCAP filtering."""
    session = _get_session(session_id, workspace_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])

    # Apply 5-tuple filter
    if src or sport or dst or dport:
        packets = filter_by_5tuple(packets, src, sport, dst, dport)

    # Apply protocol filter
    if protocol:
        proto = protocol.upper()
        packets = [p for p in packets if _pkt_proto(p) == proto]

    filtered_groups = get_connection_groups(packets) if packets else []
    result = {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"匹配 {len(packets)} 报文, {len(filtered_groups)} 条连接。",
        "total_packets": len(packets),
        "connections": filtered_groups,
        "connection_count": len(filtered_groups),
        "truncated": len(packets) > 500,
    }
    if protocol:
        result["protocol"] = protocol
    return result


def _pkt_proto(pkt) -> str:
    """Extract protocol name from a packet."""
    try:
        if hasattr(pkt, '__contains__'):
            if 'TCP' in pkt: return 'TCP'
            if 'UDP' in pkt: return 'UDP'
            if 'ICMP' in pkt: return 'ICMP'
        if hasattr(pkt, 'proto'):
            return {6: 'TCP', 17: 'UDP', 1: 'ICMP'}.get(pkt.proto, f"IP/{pkt.proto}")
        return 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'


def _pcap_protocol(session_id: str, workspace_id: str = "") -> dict:
    """Per-protocol breakdown analysis."""
    session = _get_session(session_id, workspace_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}
    packets = session.get("packets", [])

    breakdown: dict[str, dict] = {}
    for pkt in packets:
        proto = _pkt_proto(pkt)
        if proto not in breakdown:
            breakdown[proto] = {"packet_count": 0, "total_bytes": 0}
        breakdown[proto]["packet_count"] += 1
        try:
            if hasattr(pkt, '__len__') and hasattr(pkt, '__bytes__'):
                breakdown[proto]["total_bytes"] += len(pkt)
        except Exception:
            pass

    # Calculate percentages
    total = len(packets)
    for proto in breakdown:
        breakdown[proto]["percentage"] = round(breakdown[proto]["packet_count"] / total * 100, 1)

    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"协议分布: {list(breakdown.keys())}。",
        "protocols": list(breakdown.keys()),
        "breakdown": breakdown,
        "total_packets": total,
        "dominant_protocol": max(breakdown, key=lambda k: breakdown[k]["packet_count"]) if breakdown else "N/A",
    }


def _pcap_scan(session_id: str, src: str = "", dst: str = "",
                workspace_id: str = "") -> dict:
    """Security scan: port scanning detection, SYN flood, anomalies."""
    session = _get_session(session_id, workspace_id)
    if not session:
        return {"ok": False, "tool_id": "pcap.manage", "status": "failed",
                "summary": "未找到 PCAP session。", "errors": ["session_not_found"]}

    packets = session.get("packets", [])
    if src:
        packets = [p for p in packets if _pkt_has_ip(p, src)]
    if dst:
        packets = [p for p in packets if _pkt_has_ip(p, dst, key='dst')]

    findings = []

    # 1. Port scanning detection — one IP → many ports
    src_ports: dict[str, set] = {}
    for pkt in packets:
        src_ip, pkt_sport, pkt_dport = _pkt_5tuple(pkt)
        if src_ip:
            src_ports.setdefault(src_ip, set()).add(pkt_dport)
    for ip, ports in src_ports.items():
        if len(ports) >= 10:
            findings.append({
                "type": "port_scan",
                "source": ip,
                "ports_scanned": len(ports),
                "severity": "high" if len(ports) >= 50 else "medium",
            })

    # 2. SYN flood detection — many SYNs without ACK
    syn_count = 0
    ack_count = 0
    for pkt in packets:
        try:
            if hasattr(pkt, '__contains__') and 'TCP' in pkt:
                flags = pkt['TCP'].flags if 'TCP' in pkt else ''
                if flags & 0x02:
                    syn_count += 1
                if flags & 0x10:
                    ack_count += 1
        except Exception:
            pass
    if syn_count > 0 and ack_count == 0 and syn_count > 100:
        findings.append({
            "type": "syn_flood",
            "syn_count": syn_count,
            "ack_count": ack_count,
            "severity": "high",
        })

    # 3. Failed connections — RST or ICMP unreachable
    reset_count = 0
    for pkt in packets:
        try:
            if hasattr(pkt, '__contains__') and 'TCP' in pkt:
                flags = pkt['TCP'].flags if 'TCP' in pkt else ''
                if flags & 0x04:
                    reset_count += 1
        except Exception:
            pass
    if reset_count > 10:
        findings.append({
            "type": "connection_resets",
            "reset_count": reset_count,
            "severity": "medium",
        })

    return {
        "ok": True, "tool_id": "pcap.manage", "status": "succeeded",
        "summary": f"安全扫描完成，发现 {len(findings)} 个可疑模式。" if findings else "未发现可疑模式。",
        "findings": findings,
        "finding_count": len(findings),
        "safe": len(findings) == 0,
        "total_packets_analyzed": len(packets),
    }


def _pkt_5tuple(pkt) -> tuple:
    """Extract (src_ip, sport, dst_ip, dport) from a packet."""
    try:
        if hasattr(pkt, '__contains__') and 'IP' in pkt:
            ip = pkt['IP']
            sport = dport = 0
            if 'TCP' in pkt: sport, dport = pkt['TCP'].sport, pkt['TCP'].dport
            elif 'UDP' in pkt: sport, dport = pkt['UDP'].sport, pkt['UDP'].dport
            return (ip.src, sport, ip.dst, dport)
    except Exception:
        pass
    return ("", 0, "", 0)


def _pkt_has_ip(pkt, ip: str, key: str = 'src') -> bool:
    try:
        s, _, d, _ = _pkt_5tuple(pkt)
        return (s == ip if key == 'src' else d == ip)
    except Exception:
        return False
