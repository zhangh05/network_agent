"""Network-agent public capability surface contract."""

from __future__ import annotations


REMOVED_DEVELOPMENT_TOOLS = {
    "code.search",
    "git.manage",
    "spawn_review_agent",
    "spawn_fix_agent",
    "spawn_test_agent",
    "spawn_doc_agent",
}

NETWORK_SUBAGENTS = {
    "network_diag_agent",
    "config_translate_agent",
    "security_agent",
}


def test_tool_registries_expose_only_current_network_surface():
    from core.runtime_engine.contracts import BUILTIN_CONTRACTS
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    from core.tools.manifest_registry import MANIFESTS
    from core.tools.tool_namespace import TOOL_NAMESPACE

    expected = set(CANONICAL_REGISTRY)
    assert len(expected) == 24
    assert expected == set(MANIFESTS) == set(TOOL_NAMESPACE) == set(BUILTIN_CONTRACTS)
    assert REMOVED_DEVELOPMENT_TOOLS.isdisjoint(expected)
    assert "assurance.manage" in expected


def test_exec_keeps_general_execution_capabilities():
    from core.tools.canonical_registry import CANONICAL_REGISTRY

    schema = CANONICAL_REGISTRY["exec.run"].input_schema["properties"]
    actions = set(schema["action"]["enum"])

    assert {"shell", "python", "background", "stream"}.issubset(actions)
    assert set(schema["target"]["enum"]) == {"local", "ssh", "telnet"}
    assert set(schema["shell"]["enum"]) == {"cmd", "powershell"}


def test_only_network_domain_subagent_profiles_remain():
    from agent.runtime.durable.subagent import BUILTIN_PROFILES

    assert set(BUILTIN_PROFILES) == NETWORK_SUBAGENTS
    assert "pcap.manage" in BUILTIN_PROFILES["network_diag_agent"].allowed_tools
    assert "exec.run" in BUILTIN_PROFILES["network_diag_agent"].allowed_tools
    assert "config.manage" in BUILTIN_PROFILES["config_translate_agent"].allowed_tools
    assert "pcap.manage" in BUILTIN_PROFILES["security_agent"].allowed_tools
