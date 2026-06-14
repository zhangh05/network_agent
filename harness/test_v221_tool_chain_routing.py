"""v2.2.1 multi-category tool-chain routing contract tests."""

from agent.llm.tool_adapter import to_llm_tool_name
from agent.runtime.services import default_runtime_services
from agent.runtime.tool_category_router import route_tool_scene
from agent.tools.router import ToolRouter
from tool_runtime.tool_namespace import TOOL_NAMESPACE


def _assert_canonical_only(scene: dict):
    canonical = set(TOOL_NAMESPACE)
    for tool_id in scene["candidate_tools"]:
        assert tool_id in canonical, f"non-canonical candidate: {tool_id}"


def _assert_chain_subset(scene: dict):
    candidates = set(scene["candidate_tools"])
    for step in scene.get("tool_chain", []):
        assert set(step["preferred_tools"]) <= candidates


def test_host_ip_scene_exposes_host_runtime_not_network():
    scene = route_tool_scene("本机 OS 的 IP 是多少")
    assert scene["primary_category"] == "host"
    assert scene["category"] == "host"
    assert "host" in scene["categories"]
    assert "runtime" in scene["categories"]
    assert {"host.shell.exec", "host.powershell.exec"} & set(scene["candidate_tools"])
    assert "runtime.health" in scene["candidate_tools"]
    assert "network.config.parse" not in scene["candidate_tools"]
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_uploaded_network_config_scene_combines_workspace_and_network():
    scene = route_tool_scene("帮我分析上传的华三配置")
    assert scene["primary_category"] == "network"
    assert {"workspace", "network"} <= set(scene["categories"])
    assert "workspace.file.read" in scene["candidate_tools"]
    assert "network.config.parse" in scene["candidate_tools"]
    assert "network.interface.extract" in scene["candidate_tools"]
    assert "network.route.extract" in scene["candidate_tools"]
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_uploaded_network_config_report_scene_has_full_tool_chain():
    scene = route_tool_scene("帮我分析上传的华三配置，并整理成报告保存")
    assert scene["primary_category"] == "network"
    assert {"workspace", "network", "report_data"} <= set(scene["categories"])
    assert "report.markdown.render" in scene["candidate_tools"]
    assert "workspace.artifact.save" in scene["candidate_tools"]
    assert len(scene["tool_chain"]) >= 4
    assert scene["tool_chain"][0]["preferred_tools"][0].startswith("workspace.file.")
    assert scene["tool_chain"][-1]["preferred_tools"][-1] == "workspace.artifact.save"
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_official_docs_network_scene_combines_web_and_network():
    scene = route_tool_scene("根据官方文档看看这个 Cisco OSPF 配置有没有问题")
    assert scene["primary_category"] == "network"
    assert {"web", "network"} <= set(scene["categories"])
    assert "web.docs.official_search" in scene["candidate_tools"]
    assert "network.config.parse" in scene["candidate_tools"]
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_knowledge_scene_prefers_knowledge_tools():
    scene = route_tool_scene("从知识库里找之前导入的 SD-WAN 资料")
    assert scene["primary_category"] == "knowledge"
    assert "knowledge" in scene["categories"]
    assert {"knowledge.search", "knowledge.query"} & set(scene["candidate_tools"])
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_runtime_trace_scene_exposes_run_or_runtime_tools():
    scene = route_tool_scene("查看这个 run 的 trace")
    assert scene["primary_category"] == "runtime"
    assert "runtime" in scene["categories"]
    assert {"run.summary.get", "runtime.diagnostics"} & set(scene["candidate_tools"])
    _assert_canonical_only(scene)
    _assert_chain_subset(scene)


def test_context_builder_tool_router_uses_chain_candidate_tools():
    registry = default_runtime_services().tool_service.registry
    scene = route_tool_scene("帮我分析上传的华三配置，并整理成报告保存")
    router = ToolRouter.for_turn(registry, allowed_tool_ids=scene["candidate_tools"])
    names = {
        tool["function"]["name"]
        for tool in router.model_visible_tools()
    }
    assert to_llm_tool_name("network.config.parse") in names
    assert to_llm_tool_name("workspace.file.read") in names
    assert to_llm_tool_name("report.markdown.render") in names
    assert to_llm_tool_name("host.shell.exec") not in names
