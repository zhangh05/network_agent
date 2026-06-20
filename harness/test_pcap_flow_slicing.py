"""PCAP flow slicing and TCP alignment quality checks."""

import pytest

from agent.modules.pcap.core import (
    PCAP_SESSIONS as _PCAP_SESSIONS,
    filter_by_5tuple as _filter_by_5tuple,
    get_connection_groups as _get_connection_groups,
    tcp_stream_align as _tcp_stream_align,
)
from backend.main import app as _flask_app


@pytest.fixture
def client(temp_dirs):
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def _pkt(index, time, src, sport, dst, dport, seq, ack, flags, payload_len=0):
    rec = {
        "index": index,
        "time": time,
        "src": src,
        "dst": dst,
        "proto": 6,
        "sport": sport,
        "dport": dport,
        "tcp_seq": seq,
        "tcp_ack": ack,
        "tcp_flags": flags,
    }
    if payload_len:
        rec["payload_len"] = payload_len
    return rec


def _normal_flow():
    return [
        _pkt(0, 0.0, "10.0.0.1", 12345, "10.0.0.2", 443, 1000, 0, "S"),
        _pkt(1, 0.1, "10.0.0.2", 443, "10.0.0.1", 12345, 9000, 1001, "SA"),
        _pkt(2, 0.2, "10.0.0.1", 12345, "10.0.0.2", 443, 1001, 9001, "A"),
        _pkt(3, 0.3, "10.0.0.1", 12345, "10.0.0.2", 443, 1001, 9001, "PA", 10),
        _pkt(4, 0.4, "10.0.0.2", 443, "10.0.0.1", 12345, 9001, 1011, "A"),
    ]


def test_connection_groups_merge_bidirectional_5tuple():
    groups = _get_connection_groups(_normal_flow())

    assert groups == [
        {
            "src": "10.0.0.1",
            "sport": 12345,
            "dst": "10.0.0.2",
            "dport": 443,
            "proto": 6,
            "proto_name": "TCP",
            "packets_fwd": 3,
            "packets_rev": 2,
            "total": 5,
            "bidirectional": True,
        }
    ]


def test_tcp_align_does_not_duplicate_same_port_flows():
    packets = [
        _pkt(0, 0.0, "10.0.0.1", 179, "10.0.0.2", 179, 1000, 0, "S"),
        _pkt(1, 0.1, "10.0.0.2", 179, "10.0.0.1", 179, 5000, 1001, "SA"),
        _pkt(2, 0.2, "10.0.0.1", 179, "10.0.0.2", 179, 1001, 5001, "A"),
    ]

    result = _tcp_stream_align(packets)

    assert result["total_tcp_packets"] == 3
    assert len(result["events"]) == 3
    assert [event["dir"] for event in result["events"]] == ["→", "←", "→"]


def test_tcp_align_ack_only_does_not_consume_sequence_space():
    packets = _normal_flow() + [
        _pkt(5, 0.5, "10.0.0.1", 12345, "10.0.0.2", 443, 1011, 9001, "PA", 5),
    ]

    result = _tcp_stream_align(packets)

    assert result["anomalies"] == []


def test_tcp_align_detects_payload_gap_with_exact_size():
    packets = _normal_flow() + [
        _pkt(5, 0.5, "10.0.0.1", 12345, "10.0.0.2", 443, 1021, 9001, "PA", 5),
    ]

    result = _tcp_stream_align(packets)

    assert result["anomalies"][0]["type"] == "seq_gap"
    assert result["anomalies"][0]["gap_size"] == 10


def test_pcap_align_can_slice_requested_flow_without_prior_filter(client):
    session_id = "pcap_contract"
    _PCAP_SESSIONS[session_id] = {
        "filepath": "/tmp/contract.pcap",
        "packets": _normal_flow()
        + [
            _pkt(10, 1.0, "192.0.2.1", 5555, "192.0.2.2", 80, 1, 0, "S"),
        ],
        "groups": [],
    }

    try:
        resp = client.post(
            "/api/pcap/align",
            json={
                "session_id": session_id,
                "src": "10.0.0.1",
                "sport": 12345,
                "dst": "10.0.0.2",
                "dport": 443,
            },
        )
    finally:
        _PCAP_SESSIONS.pop(session_id, None)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["total_tcp_packets"] == 5
    assert all(
        event["index"] in {0, 1, 2, 3, 4}
        for event in data["events"]
    )


def test_pcap_parser_dependency_is_declared():
    reqs = open("requirements.txt", encoding="utf-8").read()

    assert "scapy" in reqs.lower()
