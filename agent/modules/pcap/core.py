# agent/modules/pcap/core.py
"""PCAP analysis core logic — pure functions, no Flask dependency.

This module owns the PCAP parsing, session management, filtering, and TCP
alignment logic. Both the agent module service and the backend API routes
import from here.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# ── Session state ────────────────────────────────────────────────────

PCAP_SESSIONS: dict[str, dict] = {}


def safe_name(filename: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)[:120] or "upload.pcap"


def pcap_session_id_for(path) -> str:
    """Generate a deterministic session ID from the first 1024 bytes of a file."""
    with open(str(path), "rb") as fh:
        return hashlib.md5(fh.read(1024)).hexdigest()[:12]


# ── Core PCAP functions ──────────────────────────────────────────────

def parse_pcap(filepath: str) -> list[dict]:
    """Parse pcap file into structured packet list using scapy."""
    try:
        from scapy.all import rdpcap, IP, TCP, UDP, ICMP, Raw
        from scapy.error import Scapy_Exception
    except ImportError:
        return []

    try:
        pkts = rdpcap(filepath)
    except Exception:
        return []

    result = []
    for seq, pkt in enumerate(pkts):
        entry: dict[str, Any] = {"index": seq, "time": float(getattr(pkt, "time", 0)), "length": len(pkt)}
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


def get_connection_groups(packets: list[dict]) -> list[dict]:
    """Merge bidirectional 5-tuples into connection groups."""
    by_5tuple: dict[tuple, dict] = {}
    for pkt in packets:
        if not all(k in pkt for k in ("src", "dst", "proto", "sport", "dport")):
            continue
        key = (pkt["src"], pkt["sport"], pkt["dst"], pkt["dport"], pkt["proto"])
        if key not in by_5tuple:
            by_5tuple[key] = {"fwd": 0}
        by_5tuple[key]["fwd"] += 1

    seen: set[tuple] = set()
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
            "src": src, "sport": sport, "dst": dst, "dport": dport,
            "proto": proto, "proto_name": proto_names.get(proto, str(proto)),
            "packets_fwd": fwd_count, "packets_rev": rev_count,
            "total": fwd_count + rev_count, "bidirectional": rev_count > 0,
        })
    return sorted(groups, key=lambda g: -g["total"])


def filter_by_5tuple(packets: list[dict], src: str, sport: int, dst: str, dport: int) -> list[dict]:
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


def tcp_stream_align(packets: list[dict]) -> dict:
    """Align TCP packets by sequence number, detecting gaps and anomalies."""
    tcp_pkts = [p for p in packets if p.get("tcp_seq") is not None]
    if not tcp_pkts:
        return {"events": [], "anomalies": [], "syn_count": 0, "fin_count": 0, "rst_count": 0, "total_tcp_packets": 0}

    first = tcp_pkts[0]
    src = first.get("src")
    dst = first.get("dst")
    src_port = first.get("sport")
    dst_port = first.get("dport")

    fwd = [p for p in tcp_pkts if p.get("src") == src and p.get("dst") == dst
           and p.get("sport") == src_port and p.get("dport") == dst_port]
    rev = [p for p in tcp_pkts if p.get("src") == dst and p.get("dst") == src
           and p.get("sport") == dst_port and p.get("dport") == src_port]

    fwd_base = min(p.get("tcp_seq", 0) for p in fwd) if fwd else 0
    rev_base = min(p.get("tcp_seq", 0) for p in rev) if rev else 0

    def _build_events(pkts, direction, base, peer_base):
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
                "seq": raw_seq, "ack": raw_ack, "rel_seq": rel_seq, "rel_ack": rel_ack,
                "dir": direction, "flags": flags,
                "time": round(pkt.get("time", 0), 6),
                "payload_len": payload, "index": pkt.get("index"),
            }
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
    all_events = sorted(fwd_events + rev_events, key=lambda x: x["time"])

    anomalies = []
    for evt in all_events:
        if evt.get("gap"):
            anomalies.append({
                "type": "seq_gap", "at_seq": evt["seq"], "rel_seq": evt.get("rel_seq", 0),
                "direction": evt["dir"], "gap_size": evt.get("gap_size", 0),
                "reason": f"序列号跳跃 {evt.get('gap_size')} 字节，可能丢包",
            })
        if "R" in str(evt.get("flags", "")):
            anomalies.append({
                "type": "rst", "at_seq": evt["seq"], "direction": evt["dir"],
                "reason": "连接被 RST 重置",
            })

    return {
        "conn": f"{first.get('src', '?')}:{src_port} ↔ {first.get('dst', '?')}:{dst_port}",
        "total_tcp_packets": len(tcp_pkts),
        "events": all_events, "anomalies": anomalies,
        "syn_count": sum(1 for e in all_events if "S" in str(e.get("flags", ""))),
        "fin_count": sum(1 for e in all_events if "F" in str(e.get("flags", ""))),
        "rst_count": sum(1 for e in all_events if "R" in str(e.get("flags", ""))),
    }
