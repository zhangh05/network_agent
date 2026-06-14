"""v2.2 Tool Namespace contract tests."""

import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(temp_dirs):
    from backend.main import app

    app.config["TESTING"] = True
    return app.test_client()


def test_namespace_has_one_canonical_for_each_execution_tool():
    from agent.runtime.services import default_runtime_services
    from tool_runtime.tool_namespace import TOOL_NAMESPACE, execution_tool_ids, legacy_aliases

    registry = default_runtime_services().tool_service.registry
    execution_ids = sorted(t.tool_id for t in registry.list_all())
    assert len(execution_ids) == 88
    assert sorted(execution_tool_ids()) == execution_ids
    assert len(TOOL_NAMESPACE) == 88
    assert len(set(TOOL_NAMESPACE)) == 88
    assert len(legacy_aliases()) >= 60


def test_required_namespace_mappings_are_present():
    from tool_runtime.tool_namespace import get_namespace_entry, get_canonical_tool_id, get_execution_tool_id

    cases = {
        "shell.exec": "host.shell.exec",
        "powershell.exec": "host.powershell.exec",
        "python.exec": "host.python.exec",
        "file.read": "workspace.file.read",
        "workspace.read_text_preview": "workspace.file.preview",
        "artifact.save_result": "workspace.artifact.save",
        "knowledge.search_chunks": "knowledge.search",
        "parser.extract_interfaces": "network.interface.extract",
        "config_translation.translate_config": "network.config.translate",
        "web.official_doc_search": "web.docs.official_search",
        "weather.current": "web.weather.current",
        "run.list_recent": "run.list",
        "memory.get_profile": "memory.profile.get",
        "report.render_markdown": "report.markdown.render",
        "agent.list_roles": "agent.role.list",
    }
    for execution_id, canonical_id in cases.items():
        assert get_canonical_tool_id(execution_id) == canonical_id
        assert get_execution_tool_id(canonical_id) == execution_id
        assert get_namespace_entry(canonical_id).execution_tool_id == execution_id


def test_tool_specs_include_namespace_metadata():
    from agent.runtime.services import default_runtime_services

    registry = default_runtime_services().tool_service.registry
    for spec in registry.list_all():
        meta = getattr(spec, "metadata", {})
        assert meta["canonical_tool_id"]
        assert meta["execution_tool_id"] == spec.tool_id
        assert meta["category"]
        assert meta["group"]
        assert meta["action"]
        assert meta["display_name"]
        assert meta["usage_hint"]


def test_tool_router_accepts_canonical_and_legacy_names():
    from agent.llm.tool_adapter import to_llm_tool_name
    from agent.runtime.services import default_runtime_services
    from agent.tools.router import ToolRouter

    router = ToolRouter.for_turn(default_runtime_services().tool_service.registry)
    canonical_name = to_llm_tool_name("workspace.file.read")
    legacy_name = to_llm_tool_name("file.read")

    assert canonical_name in router.llm_name_map
    assert router.llm_name_map[canonical_name] == "file.read"
    assert router.resolve_tool_id("workspace.file.read") == "file.read"
    assert router.resolve_tool_id("file.read") == "file.read"
    assert legacy_name not in router.llm_name_map


def test_llm_tool_names_use_canonical_ids():
    from agent.llm.tool_adapter import from_llm_tool_name, to_llm_tool_name

    name = to_llm_tool_name("workspace.file.read")
    assert name == "workspace__file__read"
    assert from_llm_tool_name(name) == "workspace.file.read"


def test_catalog_api_returns_category_tree(client):
    resp = client.get("/api/tools/catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 88
    categories = data["categories"]
    ids = {c["id"] for c in categories}
    assert {"host", "workspace", "knowledge", "network", "web", "runtime", "memory", "report_data", "agent"} <= ids
    workspace = next(c for c in categories if c["id"] == "workspace")
    file_group = next(g for g in workspace["groups"] if g["id"] == "file")
    tool = next(t for t in file_group["tools"] if t["canonical_tool_id"] == "workspace.file.read")
    assert tool["execution_tool_id"] == "file.read"
    assert "file.read" in tool["legacy_tool_ids"]


def test_scene_router_selects_category_groups():
    from agent.runtime.tool_category_router import route_tool_scene

    assert route_tool_scene("查看本机端口和进程")["category"] == "host"
    assert route_tool_scene("分析这段 Cisco 配置的接口")["category"] == "network"
    assert route_tool_scene("读取 workspace 里的配置文件")["group"] == "file"
    assert route_tool_scene("查一下官方文档最新说明")["category"] == "web"
    assert route_tool_scene("知识库里 OSPF 是什么")["category"] == "knowledge"


def test_namespace_inspector_passes():
    result = subprocess.run(
        ["python3", "scripts/inspect_tool_namespace.py"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_release_tags_not_moved():
    expected = {
        "v2.1.1-full-closure": "c9e9020937fc956f04f2d7bb25129514613a864f",
        "v2.1.3-hardening": "7b5684a546d692518d943783e3f50ed0fbdb6e23",
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
    absent = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", "v2.1.2*"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert absent.stdout.strip() == ""
