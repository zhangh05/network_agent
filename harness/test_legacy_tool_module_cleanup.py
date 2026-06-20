# harness/test_legacy_tool_module_cleanup.py
"""Guards for PRB+PRC: planner chain cleanup, PCAP service decoupling, config_analysis impl."""

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── 6.1 chain_builder no longer outputs old fine tools ───────────────

def test_build_tool_chain_routes_config_to_directory_tool():
    from agent.runtime.tool_planning.chain_builder import build_tool_chain

    candidates = {
        "workspace.file.read", "workspace.file.list", "workspace.file.preview",
        "config.analysis.run",
        "network.config.parse", "network.interface.extract", "network.route.extract",
    }
    chain = build_tool_chain({"mentions_network_config": True}, candidates)
    text = str(chain)

    assert "config.analysis.run" in text
    assert "network.config.parse" not in text
    assert "network.interface.extract" not in text
    assert "network.route.extract" not in text


def test_build_tool_chain_routes_translate_to_directory_tool():
    from agent.runtime.tool_planning.chain_builder import build_tool_chain

    candidates = {
        "workspace.file.read", "workspace.file.list", "workspace.file.preview",
        "config.analysis.run", "network.config.translate",
    }
    chain = build_tool_chain({"mentions_config_translate": True}, candidates)
    text = str(chain)

    assert "config.analysis.run" in text
    assert "network.config.translate" not in text


def test_build_tool_chain_routes_pcap_to_directory_tool():
    from agent.runtime.tool_planning.chain_builder import build_tool_chain

    candidates = {
        "workspace.file.read", "workspace.file.list",
        "pcap.analysis.run",
        "network.pcap.parse", "network.pcap.session",
        "network.pcap.filter", "network.pcap.align",
    }
    chain = build_tool_chain({"mentions_packet": True}, candidates)
    text = str(chain)

    assert "pcap.analysis.run" in text
    assert "network.pcap.parse" not in text
    assert "network.pcap.session" not in text
    assert "network.pcap.filter" not in text
    assert "network.pcap.align" not in text


# ── 6.2 planner source has no legacy fine-tool special case ──────────

def test_planner_no_legacy_config_tool_special_case():
    import agent.runtime.tool_planning.planner as planner

    source = inspect.getsource(planner)

    # _has_config_tools must not contain old fine tools
    assert '"network.config.parse"' not in source
    assert '"network.interface.extract"' not in source
    # config.analysis.run should be present
    assert "config.analysis.run" in source


# ── 6.3 pcap service does not import backend routes ──────────────────

def test_pcap_service_does_not_import_backend_routes():
    import agent.modules.pcap.service as service

    source = inspect.getsource(service)
    assert "backend.api.pcap_routes" not in source


# ── 6.4 config_analysis service is not pure stub ─────────────────────

def test_config_analysis_parse_extracts_interfaces_and_routes():
    from agent.modules.config_analysis.service import parse_config

    sample = """
interface GigabitEthernet0/0/1
 description Uplink
 ip address 10.0.0.1 255.255.255.0
#
interface LoopBack0
 ip address 1.1.1.1 255.255.255.255
#
ip route-static 0.0.0.0 0.0.0.0 10.0.0.254
vlan batch 10 20
"""
    parsed = parse_config(sample, vendor="huawei")

    assert parsed["vendor"] == "huawei"
    assert len(parsed["interfaces"]) >= 2
    iface_names = [i["name"] for i in parsed["interfaces"]]
    assert "GigabitEthernet0/0/1" in iface_names
    assert "LoopBack0" in iface_names
    assert len(parsed["routes"]) >= 1
    assert any("10.0.0.254" in r["detail"] for r in parsed["routes"])
    assert parsed["vlans"]


def test_config_analysis_run_parse_action():
    from agent.modules.config_analysis.service import run_config_analysis

    result = run_config_analysis(
        action="parse",
        source_config="interface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.0\n#\n",
        source_vendor="huawei",
    )
    assert result["ok"]
    assert result["tool_id"] == "config.analysis.run"
    assert result.get("interfaces")


def test_config_analysis_diff():
    from agent.modules.config_analysis.service import diff_configs

    before = "interface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.0"
    after = "interface GigabitEthernet0/0/1\n ip address 10.0.0.2 255.255.255.0"
    result = diff_configs(before, after)
    assert result["added"]
    assert result["removed"]
