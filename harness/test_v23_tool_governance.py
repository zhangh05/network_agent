"""v2.3 tool governance contract tests."""

from agent.runtime.services import default_runtime_services
import pytest


@pytest.fixture
def client(temp_dirs):
    from backend.main import app

    app.config["TESTING"] = True
    return app.test_client()


def test_every_canonical_tool_has_governance_entry():
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    assert set(TOOL_GOVERNANCE) == set(TOOL_NAMESPACE)
    for canonical_id, entry in TOOL_GOVERNANCE.items():
        assert entry.canonical_tool_id == canonical_id
        assert entry.status in {"keep", "alias", "merged", "deprecated", "removed_candidate"}
        assert entry.reason
        assert entry.overlap_group
        if entry.status in {"alias", "merged", "deprecated", "removed_candidate"}:
            assert entry.migration_notes


def test_governance_marks_known_overlap_groups():
    from tool_runtime.tool_governance import TOOL_GOVERNANCE, governance_summary

    assert TOOL_GOVERNANCE["workspace.file.list"].status == "keep"
    assert TOOL_GOVERNANCE["workspace.file.list_all"].status in {"alias", "merged"}
    assert TOOL_GOVERNANCE["workspace.file.path_exists"].status in {"alias", "merged"}
    assert TOOL_GOVERNANCE["workspace.file.read"].overlap_group == "workspace_file"
    assert TOOL_GOVERNANCE["workspace.artifact.read"].overlap_group == "artifact_read"
    assert TOOL_GOVERNANCE["knowledge.search"].overlap_group == "knowledge_search"
    assert TOOL_GOVERNANCE["host.shell.exec"].status == "keep"
    assert TOOL_GOVERNANCE["host.powershell.exec"].status == "keep"
    assert TOOL_GOVERNANCE["host.python.exec"].status == "keep"

    summary = governance_summary()
    assert summary["keep"] > 0
    assert summary["merged"] > 0
    assert summary["deprecated"] > 0


def test_router_resolves_merged_canonical_to_replacement_and_preserves_legacy_execution():
    from agent.tools.router import ToolRouter
    from tool_runtime.tool_governance import resolve_governed_tool_id

    assert ToolRouter.resolve_tool_id("workspace.file.list_all") == "file.list"
    assert resolve_governed_tool_id("workspace.file.list_all").replacement == "workspace.file.list"
    assert resolve_governed_tool_id("workspace.list_files").execution_tool_id == "file.list"

    deprecated = resolve_governed_tool_id("web.news.search")
    assert deprecated.governance_status == "deprecated"
    assert deprecated.execution_tool_id == "news.search"
    assert deprecated.warning


def test_catalog_api_returns_governance_fields(client):
    resp = client.get("/api/tools/catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 88
    assert data["governance_summary"]["keep"] > 0
    assert data["planner_visible_count"] < 88

    tools = {item["canonical_tool_id"]: item for item in data["tools"]}
    assert tools["workspace.file.list"]["governance_status"] == "keep"
    assert tools["workspace.file.list_all"]["governance_status"] in {"alias", "merged"}
    assert tools["workspace.file.list_all"]["replacement"] == "workspace.file.list"
    assert tools["web.news.search"]["planner_visible"] is False

    workspace = next(c for c in data["categories"] if c["id"] == "workspace")
    file_group = next(g for g in workspace["groups"] if g["id"] == "file")
    list_all = next(t for t in file_group["tools"] if t["canonical_tool_id"] == "workspace.file.list_all")
    assert list_all["governance_status"] in {"alias", "merged"}
    assert list_all["planner_visible"] is False


def test_deprecated_tools_are_not_model_visible_when_catalog_is_planner_filtered():
    from tool_runtime.tool_governance import planner_visible_tool_ids

    visible = set(planner_visible_tool_ids())
    assert "web.news.search" not in visible
    assert "workspace.file.list_all" not in visible
    assert "workspace.file.list" in visible


def test_execution_tool_count_does_not_drift():
    registry = default_runtime_services().tool_service.registry
    assert len(registry.list_all()) == 88
    assert len(registry.list_model_visible()) == 88
