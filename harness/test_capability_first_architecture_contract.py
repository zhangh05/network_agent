# harness/test_capability_first_architecture_contract.py
"""Architecture guard: capability-first execution contract invariants."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_architecture_doc_exists_and_defines_core_terms():
    doc = Path("docs/CAPABILITY_FIRST_ARCHITECTURE.md")
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")

    assert "Skill" in text
    assert "CapabilityPackage" in text
    assert "Business Module" in text
    assert "Platform Service" in text
    assert "Directory-level Tool" in text
    assert "Prompt Architecture" in text


def test_business_modules_are_sealed():
    from agent.runtime.capability_routing.module_types import BUSINESS_MODULES

    assert BUSINESS_MODULES == {
        "config_translation",
        "config_analysis",
        "pcap_analysis",
    }


def test_platform_services_are_sealed():
    from agent.runtime.capability_routing.module_types import PLATFORM_SERVICES

    assert PLATFORM_SERVICES == {
        "workspace",
        "knowledge",
        "memory",
        "artifact",
        "runtime",
        "report",
        "web",
    }


def test_capability_packages_reference_existing_modules():
    from agent.runtime.capability_routing.manifests import CAPABILITY_PACKAGES, MODULE_MANIFESTS

    for package in CAPABILITY_PACKAGES:
        for module_id in package.module_ids:
            assert module_id in MODULE_MANIFESTS, f"{package.capability_id} references missing module {module_id}"


def test_business_capabilities_use_directory_level_tools():
    from agent.runtime.capability_routing.manifests import package_by_id

    config_pkg = package_by_id("config_translation")
    assert config_pkg is not None
    assert "config.analysis.run" in config_pkg.tool_ids

    pcap_pkg = package_by_id("pcap_analysis")
    assert pcap_pkg is not None
    assert "pcap.analysis.run" in pcap_pkg.tool_ids


def test_old_fine_grained_network_tools_are_deleted():
    from tool_runtime.tool_governance import get_governance_entry

    old_tools = [
        "network" + ".config.parse",
        "network" + ".config.translate",
        "network" + ".interface.extract",
        "network" + ".route.extract",
        "network" + ".pcap.parse",
        "network" + ".pcap.session",
        "network" + ".pcap.filter",
        "network" + ".pcap.align",
    ]

    for tool_id in old_tools:
        entry = get_governance_entry(tool_id)
        assert entry.status == "forbidden", tool_id
        assert entry.planner_visible is False
        assert entry.planner_visible is False, tool_id


def test_prompt_contract_mentions_boundary_terms():
    from agent.runtime.prompt_architecture.policies import SYSTEM_CONTRACT

    assert "Skill is a CapabilityPackage manifest" in SYSTEM_CONTRACT
    assert "Business Modules implement domain logic" in SYSTEM_CONTRACT
    assert "Platform Services provide infrastructure" in SYSTEM_CONTRACT
    assert "config.analysis.run" in SYSTEM_CONTRACT
    assert "pcap.analysis.run" in SYSTEM_CONTRACT


def test_no_full_tool_namespace_default_in_planner_or_context_builder():
    for path in [
        "agent/runtime/tool_planning/planner.py",
        "agent/runtime/context_builder.py",
    ]:
        text = Path(path).read_text(encoding="utf-8")
        assert 'available_catalog = {"tools": list(TOOL_NAMESPACE)}' not in text
        assert 'available_catalog={"tools": list(TOOL_NAMESPACE)}' not in text


def test_readme_runtime_pipeline_matches_capability_first_chain():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "CapabilityRouter" in text
    assert "SkillManifest / CapabilityPackage" in text
    assert "ModuleServiceManifest" in text
    assert "ToolBundle" in text
    assert "ToolPlannerV2" in text
    assert "PromptArchitecture" in text
    assert "ActionExecutionKernel" in text

    old_chain_fragments = [
        "UserInput -> SceneDecision -> RuntimeState -> Evidence -> Planner",
        "Evidence -> Planner -> Prompt",
        "Planner -> Prompt -> ActionKernel",
        "MemoryPlan -> Trace -> Truth -> Stability",
    ]
    for frag in old_chain_fragments:
        assert frag not in text, f"README still contains old pipeline: {frag}"


def test_docs_do_not_contain_old_planner_first_pipeline():
    paths = [
        Path("README.md"),
        Path("DESIGN.md"),
        Path("AGENTS.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("docs/CAPABILITY_FIRST_ARCHITECTURE.md"),
    ]

    old_chain_fragments = [
        "UserInput -> SceneDecision -> RuntimeState -> Evidence -> Planner",
        "Evidence -> Planner -> Prompt",
        "Planner -> Prompt -> ActionKernel",
        "MemoryPlan -> Trace -> Truth -> Stability",
    ]

    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for frag in old_chain_fragments:
            assert frag not in text, f"{path} still contains old pipeline fragment: {frag}"
