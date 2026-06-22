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

# Time-window for connection grouping (seconds)
CONNECTION_IDLE_TIMEOUT = 30.0


def safe_name(filename: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)[:120] or "upload.pcap"


def pcap_session_id_for(path) -> str:
    """Generate a deterministic session ID from file content hash."""
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:16]


# ── Core PCAP functions ──────────────────────────────────────────────

def parse_pcap(filepath: str) -> list[dict]:
    """Parse pcap file into structured packet list using scapy.

    For large files, falls back to streaming reader mode to avoid OOM.
    """
    try:
        from scapy.all import rdpcap, PcapReader, IP, TCP, UDP, ICMP, Raw
        from scapy.error import Scapy_Exception
    except ImportError:
        return []

    import os
    file_size = os.path.getsize(filepath)

    try:
        # Stream-read for large files (>200MB) to avoid OOM
        if file_size > 200 * 1024 * 1024:
            pkts = PcapReader(filepath)
        else:
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
    """Group packets into bidirectional connections.

    Canonical 4-tuple approach (Wireshark/tcpflow standard):
    - Key = sorted endpoint pair: ((ip_a, port_a), (ip_b, port_b), proto)
    - Both directions → same key → one bidirectional group
    - TCP: bare SYN (no ACK) starts new flow, even with same 4-tuple
    - UDP: canonical 4-tuple only
    """
    if not packets:
        return []

    sorted_pkts = sorted(packets, key=lambda p: p.get("time", 0))
    proto_names = {6: "TCP", 17: "UDP"}
    flows: dict[tuple, dict] = {}
    flow_order: list[tuple] = []

    for pkt in sorted_pkts:
        if not all(k in pkt for k in ("src", "dst", "proto", "sport", "dport")):
            continue

        t = pkt.get("time", 0)
        src, sport = pkt["src"], pkt["sport"]
        dst, dport = pkt["dst"], pkt["dport"]
        proto = pkt["proto"]
        flags = str(pkt.get("tcp_flags", ""))
        is_tcp = proto == 6

        # Canonical key: sorted endpoint pair
        if (src, sport) < (dst, dport):
            ckey = (src, sport, dst, dport, proto)
        else:
            ckey = (dst, dport, src, sport, proto)

        # TCP: bare SYN starts a new flow even with same canonical key
        is_new_syn = is_tcp and "S" in flags and "A" not in flags
        existing = flows.get(ckey)
        reuse = existing is not None and (
            not is_new_syn or t - existing["last_time"] <= CONNECTION_IDLE_TIMEOUT
        )

        if not reuse:
            existing = {"fwd": 0, "rev": 0, "time": t, "last_time": t}
            flows[ckey] = existing
            flow_order.append(ckey)

        existing["last_time"] = max(existing["last_time"], t)

        # Direction: is this packet forward relative to canonical key?
        if (src, sport) == (ckey[0], ckey[1]):
            existing["fwd"] += 1
        else:
            existing["rev"] += 1

    groups: list[dict] = []
    for ckey in flow_order:
        info = flows[ckey]
        src, sport, dst, dport, proto = ckey
        groups.append({
            "src": src, "sport": int(sport), "dst": dst, "dport": int(dport),
            "proto": int(proto), "proto_name": proto_names.get(int(proto), str(proto)),
            "packets_fwd": info["fwd"], "packets_rev": info["rev"],
            "total": info["fwd"] + info["rev"],
            "bidirectional": info["rev"] > 0,
            "start_time": info["time"],
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

    # Detect client direction from first SYN
    first = tcp_pkts[0]
    syn_pkt = next((p for p in tcp_pkts if "S" in str(p.get("tcp_flags", "")) and "A" not in str(p.get("tcp_flags", ""))), None)
    if syn_pkt:
        first = syn_pkt
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
            if next_seq is not None and raw_seq > next_seq:
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
