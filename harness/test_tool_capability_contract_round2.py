"""Tool/capability contract checks for the canonical runtime surface."""


def test_tools_dry_run_requires_workspace_id():
    from backend.main import create_app

    client = create_app().test_client()

    missing = client.post(
        "/api/tools/dry-run",
        json={"tool_id": "text.analyze", "arguments": {"action": "keywords", "text": "x"}},
    )
    invalid = client.post(
        "/api/tools/dry-run?workspace_id=../x",
        json={"tool_id": "text.analyze", "arguments": {"action": "keywords", "text": "x"}},
    )
    ok = client.post(
        "/api/tools/dry-run?workspace_id=default",
        json={"tool_id": "text.analyze", "arguments": {"action": "keywords", "text": "x"}},
    )

    assert missing.status_code == 400
    assert missing.get_json()["error"] == "invalid_workspace_id"
    assert invalid.status_code == 400
    assert invalid.get_json()["error"] == "invalid_workspace_id"
    assert ok.status_code == 200
    assert ok.get_json()["workspace_id"] == "default"


def test_tools_dry_run_reports_policy_escalation():
    from backend.main import create_app

    client = create_app().test_client()

    destructive_action = client.post(
        "/api/tools/dry-run?workspace_id=default",
        json={"tool_id": "device.manage", "arguments": {"action": "delete", "asset_id": "dev_1"}},
    )
    destructive_command = client.post(
        "/api/tools/dry-run?workspace_id=default",
        json={"tool_id": "exec.run", "arguments": {"action": "shell", "command": "rm -rf /tmp/demo"}},
    )

    assert destructive_action.status_code == 200
    assert destructive_action.get_json()["requires_approval"] is True
    assert destructive_action.get_json()["risk_level"] == "high"
    assert destructive_command.status_code == 200
    assert destructive_command.get_json()["requires_approval"] is True
    assert destructive_command.get_json()["risk_level"] == "high"


def test_catalog_exposes_action_and_usage_guidance():
    from tool_runtime.catalog_snapshot import reset_catalog_snapshot_cache, build_catalog_snapshot
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    reset_catalog_snapshot_cache()
    catalog = build_catalog_snapshot()

    # Catalog count must match the canonical tool namespace — no drift.
    # v3.9.13 added `inspection.manage` (CMDB-driven inspection).
    assert catalog["count"] == len(TOOL_NAMESPACE)
    by_id = {tool["canonical_tool_id"]: tool for tool in catalog["tools"]}
    text = by_id["text.analyze"]
    exec_tool = by_id["exec.run"]
    inspection_tool = by_id["inspection.manage"]

    assert "keywords" in text["actions"]
    assert text["usage_hint"]
    assert text["not_for"] is not None
    assert "turn_runner" in exec_tool["allowed_callers"]
    # The runner is exposed to the inspection_runner caller (internal)
    assert "inspection_runner" in inspection_tool["allowed_callers"]


def test_llm_tool_description_contains_actionable_guidance():
    from agent.llm.tool_adapter import list_tools_for_orchestrator

    tools = list_tools_for_orchestrator()
    by_name = {item["function"]["name"]: item["function"] for item in tools}
    fn = by_name["exec__run"]

    assert "[tool_id=exec.run]" in fn["description"]
    assert "Use when:" in fn["description"]
    assert "Risk:" in fn["description"]


def test_subagent_can_load_skill_catalog():
    from tool_runtime.integration import get_default_tool_runtime_client
    from tool_runtime.context import ToolRuntimeContext

    result = get_default_tool_runtime_client().invoke(
        "skill.manage",
        {"action": "list"},
        context=ToolRuntimeContext(workspace_id="default", requested_by="subagent"),
    )

    assert result.status == "succeeded"
    assert result.output.get("ok") is True
