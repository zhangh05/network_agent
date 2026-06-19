"""Behavioral acceptance tests for tool visibility hardening.

Validates that the planner exposes the correct tools for each scene type,
specifically verifying Stage 3 hardening rules:
  - Shell/PowerShell/Python are NOT in baseline; only exposed for local ops.
  - Sub-agent tools are only exposed for complex/parallel tasks.
  - Simple chat / knowledge QA / config translate / report scenes do not
    inherit local execution or sub-agent tools.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from agent.runtime.tool_category_router import route_tool_scene
from agent.runtime.tool_planner import deterministic_plan_tools
from tool_runtime.tool_namespace import TOOL_NAMESPACE

_LOCAL_EXEC_TOOLS = {"host.shell.exec", "host.powershell.exec", "host.python.exec"}
_AGENT_TOOLS = {"agent.spawn", "agent.role.list", "agent.result.get"}


def _plan_for(user_input: str) -> dict:
    """Run the full deterministic planner for a given user input."""
    scene = route_tool_scene(user_input)
    plan = deterministic_plan_tools(
        user_input=user_input,
        safe_context={},
        rule_scene=scene,
        available_catalog={"tools": list(TOOL_NAMESPACE.keys())},
    )
    return plan


def _candidates(plan: dict) -> set:
    return set(plan.get("candidate_tools", []))


def _vis(plan: dict) -> dict:
    return plan.get("visibility", {})


# ── Scenario 1: Simple chat ──────────────────────────────────────

class TestSimpleChat:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.plan = _plan_for("你好")
        self.tools = _candidates(self.plan)

    def test_no_shell(self):
        assert "host.shell.exec" not in self.tools

    def test_no_powershell(self):
        assert "host.powershell.exec" not in self.tools

    def test_no_python_exec(self):
        assert "host.python.exec" not in self.tools

    def test_no_agent_spawn(self):
        assert "agent.spawn" not in self.tools

    def test_local_ops_disabled(self):
        assert not _vis(self.plan).get("local_ops_enabled")

    def test_local_ops_filtered(self):
        filtered = self.plan.get("governance", {}).get("local_ops_filtered", [])
        assert any(t in filtered for t in _LOCAL_EXEC_TOOLS), \
            f"Local ops tools should be in filtered list, got: {filtered}"


# ── Scenario 2: Knowledge QA ─────────────────────────────────────

class TestKnowledgeQA:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.plan = _plan_for("知识库里有没有 OSPF 相关资料")
        self.tools = _candidates(self.plan)

    def test_knowledge_search_present(self):
        assert "knowledge.search" in self.tools

    def test_no_shell(self):
        assert "host.shell.exec" not in self.tools

    def test_no_powershell(self):
        assert "host.powershell.exec" not in self.tools

    def test_no_python_exec(self):
        assert "host.python.exec" not in self.tools

    def test_local_ops_disabled(self):
        assert not _vis(self.plan).get("local_ops_enabled")


# ── Scenario 3: Config translate ──────────────────────────────────

class TestConfigTranslate:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.plan = _plan_for("把这个华三配置翻译成思科配置")
        self.tools = _candidates(self.plan)

    def test_config_translate_present(self):
        assert "network.config.translate" in self.tools

    def test_file_tools_present(self):
        file_tools = {"workspace.file.read", "workspace.file.list", "workspace.file.preview"}
        assert file_tools & self.tools, f"Expected file tools, got: {self.tools & file_tools}"

    def test_no_shell(self):
        assert "host.shell.exec" not in self.tools

    def test_no_powershell(self):
        assert "host.powershell.exec" not in self.tools

    def test_no_python_exec(self):
        assert "host.python.exec" not in self.tools

    def test_local_ops_disabled(self):
        assert not _vis(self.plan).get("local_ops_enabled")


# ── Scenario 4: Local command execution ───────────────────────────

class TestLocalOps:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.plan = _plan_for("查看本机端口和进程")
        self.tools = _candidates(self.plan)

    def test_shell_or_powershell_present(self):
        assert _LOCAL_EXEC_TOOLS & self.tools, \
            f"Expected at least one local exec tool, got: {self.tools & _LOCAL_EXEC_TOOLS}"

    def test_local_ops_enabled(self):
        assert _vis(self.plan).get("local_ops_enabled")

    def test_local_ops_not_filtered(self):
        filtered = set(self.plan.get("governance", {}).get("local_ops_filtered", []))
        assert not (_LOCAL_EXEC_TOOLS & filtered), \
            f"Local ops tools should NOT be filtered when local_ops_enabled, got: {filtered}"


# ── Scenario 5: Parallel / sub-agent ─────────────────────────────

class TestSubAgent:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.plan = _plan_for("请分别检查所有文件，并行整理结果")
        self.tools = _candidates(self.plan)

    def test_agent_spawn_present(self):
        assert "agent.spawn" in self.tools, f"Expected agent.spawn in tools, got: {sorted(self.tools)}"

    def test_agent_role_list_present(self):
        assert "agent.role.list" in self.tools

    def test_agent_result_get_present(self):
        assert "agent.result.get" in self.tools


# ── Cross-cutting: baseline never contains local exec ─────────────

class TestBaselineIntegrity:
    def test_baseline_no_shell(self):
        from agent.runtime.tool_planner import _BASELINE_READ_TOOLS
        assert "host.shell.exec" not in _BASELINE_READ_TOOLS

    def test_baseline_no_powershell(self):
        from agent.runtime.tool_planner import _BASELINE_READ_TOOLS
        assert "host.powershell.exec" not in _BASELINE_READ_TOOLS

    def test_baseline_no_python_exec(self):
        from agent.runtime.tool_planner import _BASELINE_READ_TOOLS
        assert "host.python.exec" not in _BASELINE_READ_TOOLS

    def test_baseline_no_agent_spawn(self):
        from agent.runtime.tool_planner import _BASELINE_READ_TOOLS
        assert "agent.spawn" not in _BASELINE_READ_TOOLS

    def test_local_ops_tools_separate(self):
        from agent.runtime.tool_planner import _LOCAL_OPS_TOOLS
        assert "host.shell.exec" in _LOCAL_OPS_TOOLS
        assert "host.powershell.exec" in _LOCAL_OPS_TOOLS
        assert "host.python.exec" in _LOCAL_OPS_TOOLS


# ── Visibility metadata completeness ──────────────────────────────

class TestVisibilityMetadata:
    @pytest.fixture(params=[
        "你好",
        "知识库里有没有 OSPF 相关资料",
        "把这个华三配置翻译成思科配置",
        "查看本机端口和进程",
        "请分别检查所有文件，并行整理结果",
    ])
    def plan(self, request):
        return _plan_for(request.param)

    def test_visibility_has_scene(self, plan):
        assert "scene" in _vis(plan)

    def test_visibility_has_reason(self, plan):
        assert "reason" in _vis(plan)

    def test_visibility_has_visible_tools(self, plan):
        assert "visible_tools" in _vis(plan)

    def test_visibility_has_local_ops_enabled(self, plan):
        assert "local_ops_enabled" in _vis(plan)

    def test_visibility_has_filtered(self, plan):
        assert "filtered" in _vis(plan)

    def test_visibility_has_baseline(self, plan):
        assert "baseline_tools_added" in _vis(plan)
