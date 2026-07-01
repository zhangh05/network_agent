"""v3.12.1 RiskPolicy block/approval boundary tests (config-driven thresholds).

Verifies the three-way risk gate with configurable thresholds:
  - exec: ≤5 allow, >5≤20 approval, >20 hard_block
  - total: ≤20 allow, >20≤50 approval, >50 hard_block
"""

import asyncio
import json
from unittest import mock

import pytest

from speg_engine.models import ExecutionDAG, ExecutionNode, SPEGConfig
from speg_engine.risk_policy import (
    RiskPolicyEngine,
    _check_destructive_command,
    _check_system_destroy,
)


# ── Helpers ────────────────────────────────────────────────────────────

@pytest.fixture
def risk_engine():
    return RiskPolicyEngine()


def _dag(nodes: list[ExecutionNode]) -> ExecutionDAG:
    return ExecutionDAG(nodes=nodes, total_nodes=len(nodes), max_depth=0)


def _node(idx: str, tool: str, **args) -> ExecutionNode:
    return ExecutionNode(id=idx, tool=tool, args=args, depth=0)


def _make_speng(**cfg_overrides):
    from speg_engine.engine import SPEGEngine
    cfg_kwargs = {"enable_finalizer": False}
    cfg_kwargs.update(cfg_overrides)
    cfg = SPEGConfig(**cfg_kwargs)

    def mock_llm(**kw):
        return json.dumps({"nodes": []})

    return SPEGEngine(config=cfg, llm_invoke=mock_llm, tool_registry={})


# ── Tests: allow (safe to run) ─────────────────────────────────────────

def test_allow_readonly_tools(risk_engine):
    dag = _dag([
        _node("a", "knowledge.manage", action="search"),
        _node("b", "data.manage", action="filter"),
        _node("c", "text.analyze", action="classify"),
    ])
    result = risk_engine.assess(dag)
    assert result.hard_block is False
    assert result.requires_approval is False
    assert result.safe_to_run is True


def test_3_exec_no_approval_trigger(risk_engine):
    """≤5 exec → no count-based approval (contract approval still fires)."""
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(3)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    # Contract requires_approval=True per exec.run, so approval_required=True
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == ""  # no count-based reason


def test_5_exec_borderline(risk_engine):
    """Exactly 5 exec → no count-based approval trigger."""
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(5)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.hard_block is False
    # Per-node contract approval fires
    assert result.requires_approval is True


# ── Tests: approval_required (count-based) ─────────────────────────────

def test_6_exec_large_batch(risk_engine):
    """6 exec → approval_required, reason=large_command_batch."""
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(6)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == "large_command_batch"


def test_20_exec_approval(risk_engine):
    """20 exec → approval_required, NOT hard block."""
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(20)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False


def test_21_total_nodes_large_batch(risk_engine):
    """21 total tool nodes → approval_required, reason=large_tool_batch."""
    nodes = [_node(str(i), "knowledge.manage", action="search") for i in range(21)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == "large_tool_batch"


def test_50_total_nodes_approval(risk_engine):
    """50 total nodes → approval_required, NOT hard block."""
    nodes = [_node(str(i), "knowledge.manage", action="search") for i in range(50)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False


# ── Tests: hard_block (count-based) ────────────────────────────────────

def test_21_exec_hard_block(risk_engine):
    """21 exec → hard_block (excessive_command_batch)."""
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(21)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.hard_block is True
    assert "Excessive command batch" in result.blocked_reason


def test_51_total_nodes_hard_block(risk_engine):
    """51 total nodes → hard_block (excessive_tool_batch)."""
    nodes = [_node(str(i), "knowledge.manage", action="search") for i in range(51)]
    dag = _dag(nodes)
    result = risk_engine.assess(dag)
    assert result.hard_block is True
    assert "Excessive tool batch" in result.blocked_reason


# ── Tests: destructive commands (approval) ─────────────────────────────

def test_rm_f_approval(risk_engine):
    dag = _dag([_node("a", "exec.run", command="rm -f /tmp/test.txt")])
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == "destructive_command"
    assert len(result.approval_details) == 1
    assert result.approval_details[0]["risk_reason"] == "rm -f"


def test_rm_rf_approval(risk_engine):
    dag = _dag([_node("a", "exec.run", command="rm -rf /tmp/build/")])
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False


def test_git_reset_hard_approval(risk_engine):
    dag = _dag([_node("a", "exec.run", command="git reset --hard HEAD~1")])
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.approval_reason == "destructive_command"


# ── Tests: hard_block (system destroy) ─────────────────────────────────

def test_rm_rf_root_hard_block(risk_engine):
    dag = _dag([_node("a", "exec.run", command="rm -rf /")])
    result = risk_engine.assess(dag)
    assert result.hard_block is True
    assert result.safe_to_run is False


def test_del_windows_hard_block(risk_engine):
    dag = _dag([_node("a", "exec.run", command="del C:\\Windows")])
    result = risk_engine.assess(dag)
    assert result.hard_block is True


# ── Tests: destructive pattern detection ───────────────────────────────

def test_destructive_patterns():
    assert _check_destructive_command("rm -f /tmp/x") == "rm -f"
    assert _check_destructive_command("rm -rf build/") == "rm -rf"
    assert _check_destructive_command("del /f /s *.tmp") == "del /f"
    assert _check_destructive_command("chmod -R 777 /var/www") == "chmod -R 777"
    assert _check_destructive_command("docker system prune -af") == "docker system prune"
    assert _check_destructive_command("kubectl delete pod my-pod") == "kubectl delete"
    assert _check_destructive_command("ls -la") == ""


def test_system_destroy_patterns():
    assert _check_system_destroy("rm -rf /") == "rm -rf /"
    assert _check_system_destroy("rm -rf /*") == "rm -rf /*"
    assert _check_system_destroy("del C:\\Windows\\system32") == "del C:\\Windows"
    assert _check_system_destroy("del C:\\Users") == "del C:\\Users"
    assert _check_system_destroy("format C:") == "format C:"
    assert _check_system_destroy("rm -rf /tmp/build") == ""


# ── Tests: destructive + credential combo → hard_block ─────────────────

def test_rm_rf_plain_approval(risk_engine):
    """Plain rm -rf /tmp/build → approval_required, NOT hard_block."""
    dag = _dag([_node("a", "exec.run", command="rm -rf /tmp/build")])
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == "destructive_command"


def test_rm_rf_with_credential_hard_block(risk_engine):
    """rm -rf /tmp/build && cat ~/.ssh/id_rsa → hard_block (credential access)."""
    dag = _dag([_node("a", "exec.run",
                      command="rm -rf /tmp/build && cat ~/.ssh/id_rsa")])
    result = risk_engine.assess(dag)
    assert result.hard_block is True
    assert result.safe_to_run is False
    assert "command" in result.blocked_reason.lower() or \
           "credential" in result.blocked_reason.lower() or \
           "private" in result.blocked_reason.lower()


def test_git_reset_with_credential_hard_block(risk_engine):
    """git reset --hard && cat ~/.ssh/id_rsa → hard_block."""
    dag = _dag([_node("a", "exec.run",
                      command="git reset --hard && cat ~/.ssh/id_rsa")])
    result = risk_engine.assess(dag)
    assert result.hard_block is True


def test_docker_prune_plain_approval(risk_engine):
    """docker system prune -af → approval_required, NOT hard_block."""
    dag = _dag([_node("a", "exec.run", command="docker system prune -af")])
    result = risk_engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    assert result.approval_reason == "destructive_command"


def test_docker_prune_with_credential_hard_block(risk_engine):
    """docker system prune -af && cat ~/.ssh/id_rsa → hard_block."""
    dag = _dag([_node("a", "exec.run",
                      command="docker system prune -af && cat ~/.ssh/id_rsa")])
    result = risk_engine.assess(dag)
    assert result.hard_block is True


# ── Tests: pipeline ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_bypass_resume():
    from speg_engine.engine import SPEGEngine
    config = SPEGConfig(enable_finalizer=False)

    def mock_llm(**kw):
        return json.dumps({"nodes": [
            {"id": "n1", "tool": "exec.run",
             "args": {"command": "echo hello"}, "deps": []},
        ]})

    registry = {"exec.run": {"description": "", "args_schema": {
        "required": ["command"], "properties": {"command": {"type": "string"}},
    }}}
    engine = SPEGEngine(config=config, llm_invoke=mock_llm, tool_registry=registry)
    engine.register_tool("exec.run", mock.AsyncMock())

    result1 = await engine.run("test")
    assert result1.metadata.get("approval_required") is True
    assert result1.node_success_count == 0

    result2 = await engine.run("test", extras={"approved_risk": True})
    assert result2.success
    assert result2.node_success_count == 1


@pytest.mark.asyncio
async def test_hard_block_denied_approval():
    from speg_engine.engine import SPEGEngine
    config = SPEGConfig(enable_finalizer=False)

    def mock_llm(**kw):
        return json.dumps({"nodes": [
            {"id": "n1", "tool": "exec.run",
             "args": {"command": "rm -rf /"}, "deps": []},
        ]})

    registry = {"exec.run": {"description": "", "args_schema": {
        "required": ["command"], "properties": {"command": {"type": "string"}},
    }}}
    engine = SPEGEngine(config=config, llm_invoke=mock_llm, tool_registry=registry)
    engine.register_tool("exec.run", mock.AsyncMock())

    result = await engine.run("test", extras={"approved_risk": True})
    assert result.success is False
    assert result.metadata.get("hard_block") is True


def test_approval_metadata_in_result():
    from speg_engine.engine import SPEGEngine
    config = SPEGConfig(enable_finalizer=False)

    def mock_llm(**kw):
        return json.dumps({"nodes": [
            {"id": "n1", "tool": "exec.run",
             "args": {"command": "rm -f /tmp/x"}, "deps": []},
        ]})

    registry = {"exec.run": {"description": "", "args_schema": {
        "required": ["command"], "properties": {"command": {"type": "string"}},
    }}}
    engine = SPEGEngine(config=config, llm_invoke=mock_llm, tool_registry=registry)
    engine.register_tool("exec.run", mock.AsyncMock())

    result = asyncio.run(engine.run("test"))
    meta = result.metadata
    assert meta.get("approval_required") is True
    assert meta.get("approval_reason") == "destructive_command"
    assert len(meta.get("approval_nodes", [])) == 1
    assert meta["approval_details"][0]["risk_reason"] == "rm -f"


# ── Tests: config-driven thresholds ────────────────────────────────────

def test_custom_thresholds_exec():
    """Custom config: max_exec_allow=2, max_exec_approval=4."""
    cfg = SPEGConfig(rp_max_exec_allow=2, rp_max_exec_approval=4)
    engine = RiskPolicyEngine(cfg)
    # 3 exec → approval (2 < 3 ≤ 4)
    nodes = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(3)]
    dag = _dag(nodes)
    result = engine.assess(dag)
    assert result.requires_approval is True
    assert result.approval_reason == "large_command_batch"
    # 5 exec → hard_block (5 > 4)
    nodes2 = [_node(str(i), "exec.run", command=f"cmd{i}") for i in range(5)]
    dag2 = _dag(nodes2)
    result2 = engine.assess(dag2)
    assert result2.hard_block is True


def test_custom_thresholds_tools():
    """Custom config: max_tool_nodes_allow=3, max_tool_nodes_approval=6."""
    cfg = SPEGConfig(rp_max_tool_nodes_allow=3, rp_max_tool_nodes_approval=6)
    engine = RiskPolicyEngine(cfg)
    # 5 nodes → approval
    nodes = [_node(str(i), "knowledge.manage", action="search") for i in range(5)]
    dag = _dag(nodes)
    result = engine.assess(dag)
    assert result.requires_approval is True
    assert result.hard_block is False
    # 7 nodes → hard_block
    nodes2 = [_node(str(i), "knowledge.manage", action="search") for i in range(7)]
    dag2 = _dag(nodes2)
    result2 = engine.assess(dag2)
    assert result2.hard_block is True
