"""v2.3 tool architecture and capability action tests."""

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _plan(text: str, safe_context: dict | None = None):
    from agent.runtime.tool_category_router import route_tool_scene
    from agent.runtime.tool_planner import plan_tools
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    rule_scene = route_tool_scene(text, uploaded_files=(safe_context or {}).get("uploaded_files"))
    return plan_tools(
        user_input=text,
        safe_context=safe_context or {},
        rule_scene=rule_scene,
        available_catalog={"tools": list(TOOL_NAMESPACE)},
        model_config={"enabled": False},
    )


def test_capability_actions_cover_canonical_tools_or_exemptions():
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS, canonical_capability_coverage
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    coverage = canonical_capability_coverage()
    assert set(coverage["covered"]) | set(coverage["exempt"]) == set(TOOL_NAMESPACE)
    assert "workspace.file.read" in CAPABILITY_ACTIONS
    assert "network.config.analyze" in CAPABILITY_ACTIONS
    assert "report.create_and_save" in CAPABILITY_ACTIONS


def test_planner_uses_capability_actions_and_filters_governance():
    plan = _plan("帮我分析上传的华三配置，并整理成报告保存", {"uploaded_files": ["h3c.cfg"]})

    assert plan["planner_version"] == "v2.3"
    assert plan["capability_plan"]
    actions = [step["capability_action"] for step in plan["capability_plan"]]
    assert actions[:3] == [
        "workspace.file.read",
        "network.config.analyze",
        "report.create_and_save",
    ]
    assert "workspace.file.list_all" not in plan["candidate_tools"]
    assert "knowledge.not_found.explain" not in plan["candidate_tools"]
    assert plan["governance"]["deprecated_tools_filtered"] == []


def test_planner_validator_rejects_deprecated_and_unknown_capability_action():
    from agent.runtime.tool_planner import validate_tool_plan
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    bad_deprecated = {
        "candidate_tools": ["web.news.search"],
        "tool_plan": [{"step": 1, "goal": "x", "tool_candidates": ["web.news.search"], "required": True}],
        "capability_plan": [{"step": 1, "capability_action": "web.news.search", "preferred_tools": ["web.news.search"]}],
        "categories": ["web"],
        "groups": {"web": ["news"]},
    }
    valid, errors = validate_tool_plan(bad_deprecated, set(TOOL_NAMESPACE), user_input="搜索新闻")
    assert valid is False
    assert any("governance" in err or "deprecated" in err for err in errors)

    bad_action = {
        "candidate_tools": ["network.config.parse"],
        "tool_plan": [{"step": 1, "goal": "x", "tool_candidates": ["network.config.parse"], "required": True}],
        "capability_plan": [{"step": 1, "capability_action": "network.device.login", "preferred_tools": ["network.config.parse"]}],
        "categories": ["network"],
        "groups": {"network": ["config"]},
    }
    valid, errors = validate_tool_plan(bad_action, set(TOOL_NAMESPACE), user_input="分析配置")
    assert valid is False
    assert any("capability_action_unknown" in err for err in errors)


def test_audit_report_generation_and_json_contract(tmp_path):
    result = subprocess.run(
        ["python3", "scripts/audit_tool_architecture.py"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reports/TOOL_ARCHITECTURE_AUDIT.md" in result.stdout
    audit_json = PROJECT_ROOT / "reports" / "tool_architecture_audit.json"
    audit_md = PROJECT_ROOT / "reports" / "TOOL_ARCHITECTURE_AUDIT.md"
    assert audit_json.exists()
    assert audit_md.exists()

    data = json.loads(audit_json.read_text())
    assert data["summary"]["execution_count"] == 88
    assert data["summary"]["canonical_count"] == 88
    assert data["summary"]["governance_conflicts"] == 0
    assert len(data["tools"]) == 88
    sample = next(item for item in data["tools"] if item["canonical_tool_id"] == "workspace.file.read")
    assert sample["handler_module"]
    assert sample["input_schema_hash"]
    assert sample["recommendation"] == "keep"


def test_inspect_tool_architecture_passes():
    result = subprocess.run(
        ["python3", "scripts/inspect_tool_architecture.py"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "execution_count: 88" in result.stdout
    assert "canonical_count: 88" in result.stdout
    assert "governance_conflicts: 0" in result.stdout
    assert "planner_uses_deprecated: 0" in result.stdout
    assert "PASS" in result.stdout


def test_release_tags_are_not_moved_and_agent_run_not_restored():
    expected = {
        "v2.1.1-full-closure": "c9e9020937fc956f04f2d7bb25129514613a864f",
        "v2.1.3-hardening": "7b5684a546d692518d943783e3f50ed0fbdb6e23",
        "v2.2-tool-namespace-refactor": "ad0538b26172500f46dd144257745e035110272c",
        "v2.2.2-intelligent-tool-planner": "afa77c3235021057a525b1f25d59ffee56680800",
    }
    for tag, oid in expected.items():
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", tag],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        refs = {
            line.split()[1]: line.split()[0]
            for line in result.stdout.splitlines()
            if line.split()
        }
        assert refs.get(f"refs/tags/{tag}") == oid

    route_text = "\n".join(
        path.read_text(errors="ignore")
        for folder in ("backend", "agent")
        for path in (PROJECT_ROOT / folder).rglob("*.py")
    )
    assert '@app.route("/api/agent/run' not in route_text
    assert "@app.route('/api/agent/run" not in route_text
