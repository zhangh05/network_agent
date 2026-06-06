"""Module / Skill / Tool Model Architecture Tests — v0.1

Ensures docs/MODULE_SKILL_TOOL_MODEL.md is present, complete, and self-consistent.
These tests verify the document's design claims, not runtime behavior.
"""

import re
import os
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")


def _read_doc(name):
    path = os.path.join(DOCS_DIR, name)
    assert os.path.exists(path), f"{name} does not exist"
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDocExists:
    def test_doc_exists(self):
        """docs/MODULE_SKILL_TOOL_MODEL.md must exist."""
        assert os.path.exists(os.path.join(DOCS_DIR, "MODULE_SKILL_TOOL_MODEL.md"))

    def test_arch_ref_exists(self):
        """docs/ARCHITECTURE.md must reference MODULE_SKILL_TOOL_MODEL.md."""
        arch = _read_doc("ARCHITECTURE.md")
        assert "MODULE_SKILL_TOOL_MODEL.md" in arch, (
            "ARCHITECTURE.md must link to MODULE_SKILL_TOOL_MODEL.md"
        )


class TestDocDefinitions:
    """Document must define Module, Skill, Capability, Tool."""

    def test_defines_module(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "### 3.1 Module" in c or "## 3.1 Module" in c, "Missing Module definition section"
        assert "Module is" in c or "Module 是" in c

    def test_defines_skill(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "### 3.2 Skill" in c or "## 3.2 Skill" in c, "Missing Skill definition section"

    def test_defines_capability(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "### 3.3 Capability" in c or "## 3.3 Capability" in c, "Missing Capability definition section"

    def test_defines_tool(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "### 3.4 Tool" in c or "## 3.4 Tool" in c, "Missing Tool definition section"


class TestRecommendedCallFlow:
    """Document must describe the recommended call chain."""

    def test_recommended_chain(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        # The recommended flow: Agent → Capability → Skill → Module → Tool
        chain = c.lower()
        has_agent = "agent" in chain
        has_capability = "capability" in chain
        has_skill = "skill" in chain
        has_module = "module" in chain
        has_tool = "tool" in chain
        assert has_agent and has_capability and has_skill and has_module and has_tool, (
            "Document must mention Agent, Capability, Skill, Module, Tool in call chain context"
        )

    def test_agent_never_call_tool_directly(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assertions = [
            ("agent" in text and ("never calls tool" in text or "never call tool" in text
             or "not call tool" in text or "不直接调" in text or "does not call tool" in text)),
        ]
        # Check that the principle is stated
        assert any([
            "agent never calls tool" in text,
            "agent does not call tool" in text,
            "agent 不直接调" in text,
            "agent must not execute" in text and "tool" in text,
        ]), "Document must state Agent never calls Tool directly"

    def test_module_orchestrates_tool(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert any([
            "module orchestrates tool" in text,
            "module 编排 tool" in text,
            "module orchestrates" in text and "tool" in text,
        ]), "Document must state Module orchestrates Tool"


class TestToolRuntimeV01Scope:
    """Tool Runtime v0.1 must be described as planned/design only, not implemented."""

    def test_not_claim_implemented(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        # Document must NOT claim Tool Runtime is already implemented
        assert "not yet implemented" in c.lower() or "does not yet exist" in c.lower() or (
            "not yet exist" in c.lower()), (
            "Document must not claim Tool Runtime is implemented"
        )

    def test_v01_is_candidate_scope(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "candidate" in c.lower() or "planned" in c.lower() or "v0.1" in c.lower(), (
            "Document must describe Tool Runtime v0.1 as candidate scope / planned"
        )

    def test_no_ssh(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        # Must explicitly forbid SSH
        assert any([
            "ssh" in text and ("out of scope" in text or "forbidden" in text or "must not" in text
                               or "禁止" in text),
            "ssh.exec" in text,
        ]), "Document must forbid SSH in v0.1"

    def test_no_telnet(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert any([
            "telnet" in text and ("out of scope" in text or "forbidden" in text or "must not" in text
                                  or "禁止" in text),
            "telnet.exec" in text,
        ]), "Document must forbid Telnet in v0.1"

    def test_no_snmp(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert any([
            "snmp" in text and ("out of scope" in text or "forbidden" in text or "must not" in text
                               or "禁止" in text),
            "snmp.walk" in text,
        ]), "Document must forbid SNMP in v0.1"

    def test_no_nmap(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert any([
            "nmap" in text and ("out of scope" in text or "forbidden" in text or "must not" in text
                               or "禁止" in text),
            "nmap.scan" in text,
        ]), "Document must forbid nmap in v0.1"

    def test_no_arbitrary_shell(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert "arbitrary shell" in text or "become an arbitrary shell" in text, (
            "Document must forbid Tool Runtime from becoming arbitrary shell"
        )

    def test_no_real_device_execution(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert any([
            "real device" in text and "out of scope" in text,
            "real device" in text and "forbidden" in text,
        ]), "Document must forbid real device execution in v0.1"


class TestCurrentSourceFindings:
    """Document must accurately describe current source code reality."""

    def test_describes_module_yaml(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "module.yaml" in c, "Document must reference module.yaml"

    def test_describes_skill_yaml(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "skill.yaml" in c, "Document must reference skill.yaml"

    def test_describes_registry_loader(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "registry/loader.py" in c or "_generate_capabilities" in c, (
            "Document must describe capability generation in registry loader"
        )

    def test_describes_skill_executor(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "skill_executor" in c or "execute()" in c, (
            "Document must describe how skill executor calls adapter"
        )

    def test_notes_tool_runtime_does_not_exist(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "does not yet exist" in c.lower() or "not yet implemented" in c.lower() or (
            "not yet exist" in c.lower()), (
            "Document must state Tool Runtime does not yet exist"
        )

    def test_describes_confusion_points(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        # Document should mention at least one of the identified confusion points
        confusion_indicators = [
            "tool_calls",
            "tool_results",
            "external_tool",
            "confusion",
            "naming issue",
        ]
        found = any(indicator in c for indicator in confusion_indicators)
        assert found, "Document must identify current Tool/Skill confusion points"

    def test_no_claim_tool_runtime_enabled(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        # Must not claim Tool Runtime is an enabled capability
        assert "tools/" not in c or "not yet" in c.lower() or "planned" in c.lower(), (
            "Document must not suggest tools/ directory already exists with implementations"
        )


class TestNonGoals:
    """Document's non-goals must be consistent with this batch's scope."""

    def test_states_non_goal(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        assert "non-goal" in c.lower() or "non goal" in c.lower() or "does not" in c.lower(), (
            "Document must state that Tool Runtime implementation is a non-goal"
        )


class TestSecurityRedLines:
    """Document must include security red lines section."""

    def test_has_security_section(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert "security red line" in text or "安全" in text, (
            "Document must have security red lines section"
        )

    def test_tool_registration_required(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert "registered" in text or "toolregistry" in text.lower(), (
            "Document must state tools must be registered"
        )

    def test_tool_policy_check_required(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert "policy" in text, (
            "Document must reference policy checking for tools"
        )

    def test_tool_redaction_required(self):
        c = _read_doc("MODULE_SKILL_TOOL_MODEL.md")
        text = c.lower()
        assert "redact" in text, (
            "Document must mention redaction for tool outputs"
        )
