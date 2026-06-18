"""Pcap analysis API — upload, parse, filter, TCP seq alignment."""

import os
import re
import json
import hashlib
from pathlib import Path
from flask import request, jsonify
from agent.modules.knowledge.ingestion import _ws_root

_PCAP_SESSIONS: dict[str, dict] = {}  # session_id -> {filepath, packets}


def _session_meta_path(filepath: str) -> Path:
    return Path(str(filepath) + ".meta.json")


def _ensure_pcap_file_record(session_id: str, filename: str, filepath: str, total_pkts: int, groups: list, ws_id: str) -> str:
    """Create a file record for this pcap in the unified files system. Returns file_id."""
    import uuid
    from backend.api.files_routes import _files_dir, _source_dir, _now_iso
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


def _load_session_from_file(session_id: str) -> dict | None:
    """Try to re-parse a session from its saved file + meta."""
    ws_root = _ws_root()
    if not ws_root.exists():
        return None
    for ws_dir in ws_root.iterdir():
        if not ws_dir.is_dir() or ws_dir.name.startswith("_"):
            continue
        # Scan source subdirs: upload/, agent/
        for src_name in ("upload", "agent"):
            up_dir = ws_dir / "files" / src_name
            if not up_dir.exists():
                continue
            for fname in os.listdir(str(up_dir)):
                if not fname.endswith(".meta.json"):
                    continue
                try:
                    meta = json.loads((up_dir / fname).read_text())
                    if meta.get("session_id") == session_id:
                        filepath = meta["filepath"]
                        packets = _parse_pcap(filepath)
                        if packets:
                            groups = _get_connection_groups(packets)
                            session = {"filepath": filepath, "packets": packets, "groups": groups}
                            _PCAP_SESSIONS[session_id] = session
                            return session
                except Exception:
                    continue
    return None


def _safe_name(filename: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)[:120] or "upload.pcap"


def _parse_pcap(filepath: str) -> list[dict]:
    """Parse pcap file into structured packet list using scapy."""
    try:
        from scapy.all import rdpcap, IP, TCP, UDP, ICMP, Raw
        from scapy.error import Scapy_Exception
    except ImportError:
        return []

    try:
        pkts = rdpcap(filepath)
    except Scapy_Exception:
        return []

    result = []
    for seq, pkt in enumerate(pkts):
        entry = {"index": seq, "time": float(getattr(pkt, "time", 0)), "length": len(pkt)}
        if IP in pkt:
            ip = pkt[IP]
            entry["src"] = ip.src
            entry["dst"] = ip.dst
            entry["proto"] = ip.proto
            entry["ip_len"] = ip.len
            entry["ttl"] = ip.ttl
            if TCP in pkt:
                tcp = pkt[TCP]
                entry["sport"] = tcp.sport
                entry["dport"] = tcp.dport
                entry["tcp_seq"] = tcp.seq
                entry["tcp_ack"] = tcp.ack
                entry["tcp_flags"] = str(tcp.flags)
                if Raw in tcp:
                    entry["payload_len"] = len(tcp[Raw].load)
            elif UDP in pkt:
                udp = pkt[UDP]
                entry["sport"] = udp.sport
                entry["dport"] = udp.dport
            elif ICMP in pkt:
                entry["icmp_type"] = pkt[ICMP].type
        result.append(entry)
    return result


def _get_connection_groups(packets: list[dict]) -> list[dict]:
    """Merge bidirectional 5-tuples into connection groups.
    
    A TCP connection has two 5-tuples (src→dst and dst→src).
    We merge them into one group so the UI shows one row per connection.
    Unidirectional flows (no reply) still appear as single groups.
    """
    # Pass 1: collect all unique 5-tuples and their packet counts
    by_5tuple: dict[tuple, dict] = {}
    for pkt in packets:
        if not all(k in pkt for k in ("src", "dst", "proto", "sport", "dport")):
            continue
        key = (pkt["src"], pkt["sport"], pkt["dst"], pkt["dport"], pkt["proto"])
        if key not in by_5tuple:
            by_5tuple[key] = {"fwd": 0}
        by_5tuple[key]["fwd"] += 1

    # Pass 2: merge bidirectional pairs
    seen = set()
    groups: list[dict] = []
    proto_names = {6: "TCP", 17: "UDP"}

    for (src, sport, dst, dport, proto), info in by_5tuple.items():
        if (src, sport, dst, dport, proto) in seen:
            continue
        seen.add((src, sport, dst, dport, proto))

        rev_key = (dst, dport, src, sport, proto)
        rev_info = by_5tuple.get(rev_key)

        fwd_count = info["fwd"]
        rev_count = rev_info["fwd"] if rev_info else 0
        if rev_info:
            seen.add((dst, dport, src, sport, proto))

        groups.append({
            "src": src,
            "sport": sport,
            "dst": dst,
            "dport": dport,
            "proto": proto,
            "proto_name": proto_names.get(proto, str(proto)),
            "packets_fwd": fwd_count,
            "packets_rev": rev_count,
            "total": fwd_count + rev_count,
            "bidirectional": rev_count > 0,
        })

    return sorted(groups, key=lambda g: -g["total"])


def _filter_by_5tuple(packets: list[dict], src: str, sport: int, dst: str, dport: int) -> list[dict]:
    """Filter packets by 5-tuple (bidirectional)."""
    sport_int = int(sport)
    dport_int = int(dport)
    return [
        p for p in packets
        if (
            (p.get("src") == src and p.get("dst") == dst
             and p.get("sport") == sport_int and p.get("dport") == dport_int)
            or
            (p.get("src") == dst and p.get("dst") == src
             and p.get("sport") == dport_int and p.get("dport") == sport_int)
        )
    ]


def _tcp_stream_align(packets: list[dict]) -> dict:
    """Align TCP packets by sequence number, detecting gaps and anomalies.
    
    Returns events with relative seq/ack numbers (Wireshark-style,
    where the first SYN in each direction is rel_seq=0).
    """
    tcp_pkts = [p for p in packets if p.get("tcp_seq") is not None]
    if not tcp_pkts:
        return {"events": [], "anomalies": [], "syn_count": 0, "fin_count": 0, "rst_count": 0, "total_tcp_packets": 0}

    # Group into forward/reverse directions using the full endpoint tuple.
    # Port-only matching duplicates flows where sport == dport, such as BGP.
    first = tcp_pkts[0]
    src = first.get("src")
    dst = first.get("dst")
    src_port = first.get("sport")
    dst_port = first.get("dport")

    fwd = [
        p for p in tcp_pkts
        if p.get("src") == src and p.get("dst") == dst
        and p.get("sport") == src_port and p.get("dport") == dst_port
    ]
    rev = [
        p for p in tcp_pkts
        if p.get("src") == dst and p.get("dst") == src
        and p.get("sport") == dst_port and p.get("dport") == src_port
    ]

    # Compute relative sequence base for each direction
    # Base = first raw seq seen (SYN's seq, or data packet's seq if no SYN)
    fwd_base = min(p.get("tcp_seq", 0) for p in fwd) if fwd else 0
    rev_base = min(p.get("tcp_seq", 0) for p in rev) if rev else 0

    def _build_events(pkts: list[dict], direction: str, base: int, peer_base: int) -> list[dict]:
        events = []
        next_seq = None
        for pkt in pkts:
            raw_seq = pkt.get("tcp_seq", 0)
            raw_ack = pkt.get("tcp_ack", 0)
            flags = pkt.get("tcp_flags", "")
            payload = pkt.get("payload_len", 0)
            rel_seq = max(0, raw_seq - base)
            rel_ack = max(0, raw_ack - peer_base) if peer_base and raw_ack > 0 else 0
            evt = {
                "seq": raw_seq,
                "ack": raw_ack,
                "rel_seq": rel_seq,
                "rel_ack": rel_ack,
                "dir": direction,
                "flags": flags,
                "time": round(pkt.get("time", 0), 6),
                "payload_len": payload,
                "index": pkt.get("index"),
            }
            # Detect gap
            if next_seq is not None and raw_seq != next_seq:
                if raw_seq > next_seq:
                    evt["gap"] = True
                    evt["gap_size"] = raw_seq - next_seq
            events.append(evt)
            consumes = payload
            if "S" in str(flags):
                consumes += 1
            if "F" in str(flags):
                consumes += 1
            pkt_next = raw_seq + consumes
            next_seq = pkt_next if next_seq is None else max(next_seq, pkt_next)
        return events

    fwd_events = _build_events(fwd, "→", fwd_base, rev_base)
    rev_events = _build_events(rev, "←", rev_base, fwd_base)

    # Merge and sort by time
    all_events = sorted(fwd_events + rev_events, key=lambda x: x["time"])

    # Detect anomalies
    anomalies = []
    for evt in all_events:
        if evt.get("gap"):
            anomalies.append({
                "type": "seq_gap",
                "at_seq": evt["seq"],
                "rel_seq": evt.get("rel_seq", 0),
                "direction": evt["dir"],
                "gap_size": evt.get("gap_size", 0),
                "reason": f"序列号跳跃 {evt.get('gap_size')} 字节，可能丢包",
            })
        if "R" in str(evt.get("flags", "")):
            anomalies.append({
                "type": "rst",
                "at_seq": evt["seq"],
                "direction": evt["dir"],
                "reason": "连接被 RST 重置",
            })

    return {
        "conn": f"{first.get('src','?')}:{src_port} ↔ {first.get('dst','?')}:{dst_port}",
        "total_tcp_packets": len(tcp_pkts),
        "events": all_events,
        "anomalies": anomalies,
        "syn_count": sum(1 for e in all_events if "S" in str(e.get("flags", ""))),
        "fin_count": sum(1 for e in all_events if "F" in str(e.get("flags", ""))),
        "rst_count": sum(1 for e in all_events if "R" in str(e.get("flags", ""))),
    }


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

        safe = _safe_name(uploaded.filename)
        up_dir = _ws_root() / ws_id / "files" / "upload"
        up_dir.mkdir(parents=True, exist_ok=True)
        target = up_dir / safe
        uploaded.save(str(target))

        packets = _parse_pcap(str(target))
        if not packets:
            return jsonify({"ok": False, "error": "无法解析 pcap 文件"}), 400

        groups = _get_connection_groups(packets)
        session_id = hashlib.md5(open(str(target), "rb").read(1024)).hexdigest()[:12]
        _PCAP_SESSIONS[session_id] = {"filepath": str(target), "packets": packets, "groups": groups}

        # Save session meta to disk for persistence across restarts
        meta = {
            "session_id": session_id,
            "filepath": str(target),
            "filename": safe,
            "total_packets": len(packets),
            "connections": groups,
        }
        _session_meta_path(str(target)).write_text(json.dumps(meta, ensure_ascii=False))

        # Use original filename for display, safe name for disk
        display_name = uploaded.filename or safe

        # Also create a unified file record for the pcap
        file_id = _ensure_pcap_file_record(session_id, display_name, str(target), len(packets), groups, ws_id)

        return jsonify({
            "ok": True,
            "session_id": session_id,
            "file_id": file_id,
            "filename": safe,
            "total_packets": len(packets),
            "connections": groups,
            "summary": f"共 {len(packets)} 个报文, {len(groups)} 条连接",
        })

    @app.route("/api/pcap/session/<session_id>", methods=["GET"])
    def api_pcap_session(session_id):
        """Restore session metadata (survives page refresh)."""
        session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
        if not session:
            # Fallback: try to load meta from source subdirs
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
            "ok": True,
            "session_id": session_id,
            "filename": Path(session["filepath"]).name,
            "total_packets": len(session["packets"]),
            "connections": session.get("groups", []),
        })

    @app.route("/api/pcap/filter", methods=["POST"])
    def api_pcap_filter():
        data = request.get_json(force=True)
        session_id = data.get("session_id", "")
        src = data.get("src", "")
        sport = data.get("sport", 0)
        dst = data.get("dst", "")
        dport = data.get("dport", 0)

        session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
        if not session:
            return jsonify({"ok": False, "error": "session not found"}), 404

        filtered = _filter_by_5tuple(session["packets"], src, sport, dst, dport)
        session["filtered"] = filtered

        return jsonify({
            "ok": True,
            "count": len(filtered),
            "packets": filtered[:500],  # truncate for response size
            "truncated": len(filtered) > 500,
        })

    @app.route("/api/pcap/align", methods=["POST"])
    def api_pcap_align():
        data = request.get_json(force=True)
        session_id = data.get("session_id", "")

        session = _PCAP_SESSIONS.get(session_id) or _load_session_from_file(session_id)
        if not session:
            return jsonify({"ok": False, "error": "session not found"}), 404

        packets = session.get("packets", [])
        if all(k in data for k in ("src", "sport", "dst", "dport")):
            filtered = _filter_by_5tuple(
                packets,
                data.get("src", ""),
                data.get("sport", 0),
                data.get("dst", ""),
                data.get("dport", 0),
            )
        else:
            filtered = session.get("filtered", packets)
        result = _tcp_stream_align(filtered)

        return jsonify({"ok": True, **result})
