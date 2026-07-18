from __future__ import annotations

from agent.modules.inspection.structured import parse_device_output, split_command_output


H3C_OUTPUT = """dis cpu-usage
Unit CPU usage:
  20% in last 5 seconds
  18% in last 1 minute
  17% in last 5 minutes
<R1>dis memory
Mem:  1000 500 500 0 0 0 50.0%
<R1>dis environment
Slot Sensor Temperature LowerLimit WarningLimit AlarmLimit
0/0 Hotspot 1 40 -5 66 76
<R1>dis ip int brief
Interface Physical Protocol IP address/Mask VPN Description
GE0/1 up up 10.0.0.1/24 -- --
<R1>dis ip routing-table
Destinations : 1 Routes : 1
Destination/Mask Proto Pre Cost NextHop Interface
20.0.0.0/24 BGP 255 0 10.0.0.2 GE0/1
<R1>dis bgp peer ipv4
BGP local router ID: 10.0.0.1
Local AS number: 65001
10.0.0.2 65002 10 10 0 1 01h00m Established
<R1>dis lldp nei
LLDP is not configured.
"""


def test_h3c_output_becomes_typed_assurance_facts():
    sections = split_command_output(H3C_OUTPUT)
    assert sections[0][0] == "dis cpu-usage"
    parsed = parse_device_output("H3C", H3C_OUTPUT)
    facts = {item["key"]: item for item in parsed["facts"]}
    assert parsed["quality"] == "complete"
    assert facts["health.cpu.5s.percent"]["policy"] == "threshold"
    assert facts["health.memory.free_ratio.percent"]["direction"] == "min"
    assert facts["interface.ge0_1.protocol"]["value"] == "up"
    assert facts["route.20.0.0.0_24"]["value"]["next_hop"] == "10.0.0.2"
    assert facts["protocol.bgp.peer.10.0.0.2.state"]["value"] == "established"


def test_policy_engine_distinguishes_threshold_and_baseline_delta():
    from agent.modules.assurance.service import compare_snapshots

    reference = {"source_status": "succeeded", "facts": [
        {"key": "asset.a1.health.cpu.5s.percent", "value": 20, "asset_id": "a1",
         "policy": "threshold", "warning": 80, "critical": 95, "direction": "max",
         "severity": "warning", "resource_type": "cpu", "resource_id": "system"},
        {"key": "asset.a1.routing.route_count", "value": 100, "asset_id": "a1",
         "policy": "baseline_delta", "warning": .2, "critical": .5,
         "severity": "warning", "resource_type": "routing_table", "resource_id": "ipv4"},
    ]}
    current = {"source_status": "succeeded", "facts": [
        {**reference["facts"][0], "value": 90, "evidence_ref": "artifact:cpu"},
        {**reference["facts"][1], "value": 160, "evidence_ref": "artifact:route"},
    ]}
    changes = {item["key"]: item for item in compare_snapshots(reference, current)}
    assert changes["asset.a1.health.cpu.5s.percent"]["kind"] == "threshold_breach"
    assert changes["asset.a1.health.cpu.5s.percent"]["severity"] == "warning"
    assert changes["asset.a1.routing.route_count"]["kind"] == "baseline_delta"
    assert changes["asset.a1.routing.route_count"]["severity"] == "critical"


def test_fact_missing_from_incomplete_baseline_is_not_a_drift():
    from agent.modules.assurance.service import compare_snapshots

    reference = {"source_status": "succeeded", "quality": {"level": "partial", "evidence_complete": False}, "facts": []}
    current = {"source_status": "succeeded", "quality": {"level": "complete", "evidence_complete": True}, "facts": [{
        "key": "asset.a1.protocol.bgp.peer.10.0.0.2.state", "value": "established",
        "asset_id": "a1", "policy": "must_equal", "severity": "critical",
        "resource_type": "bgp_peer", "resource_id": "10.0.0.2", "evidence_ref": "artifact:new",
    }]}
    change = compare_snapshots(reference, current)[0]
    assert change["kind"] == "newly_observable"
    assert change["severity"] == "info"
    assert change["policy"] == "coverage"


def test_continuous_alarm_requires_confirmation_and_recovery(tmp_path, monkeypatch):
    from agent.modules.assurance import service, store
    import storage.paths as spaths

    monkeypatch.setattr(spaths, "workspace_root", lambda workspace_id: tmp_path / workspace_id)
    schedule = {"schedule_id": "s1", "baseline_id": "b1", "confirm_after": 2, "recover_after": 2}
    change = {"asset_id": "a1", "key": "asset.a1.interface.ge0_1.protocol",
              "severity": "critical", "evidence_ref": "artifact:1"}
    assert service._update_schedule_alarms("default", schedule, {"changes": [change]}) == 0
    assert service._update_schedule_alarms("default", schedule, {"changes": [change]}) == 1
    assert service.list_alarms("default", "open")[0]["consecutive_hits"] == 2
    assert service._update_schedule_alarms("default", schedule, {"changes": []}) == 1
    assert service._update_schedule_alarms("default", schedule, {"changes": []}) == 0
    assert service.list_alarms("default", "resolved")[0]["consecutive_clears"] == 2
