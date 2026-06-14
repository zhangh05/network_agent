"""v2.2.2 intelligent tool planner contract tests."""

from agent.runtime.services import default_runtime_services
from agent.runtime.tool_category_router import route_tool_scene
from agent.tools.router import ToolRouter
from agent.llm.tool_adapter import to_llm_tool_name


def _plan(text: str, safe_context: dict | None = None):
    from agent.runtime.tool_planner import plan_tools
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    rule_scene = route_tool_scene(text)
    return plan_tools(
        user_input=text,
        safe_context=safe_context or {},
        rule_scene=rule_scene,
        available_catalog={"tools": list(TOOL_NAMESPACE)},
        model_config={"enabled": False},
    )


def test_network_report_plan_is_ordered_and_minimal():
    plan = _plan("帮我分析上传的华三配置，并整理成报告保存", {"uploaded_files": ["h3c.cfg"]})
    assert plan["planner_version"] == "v2.2.2"
    assert plan["mode"] in {"deterministic", "hybrid"}
    assert {"workspace", "network", "report_data"} <= set(plan["categories"])
    assert len(plan["tool_plan"]) >= 4
    assert {
        "workspace.file.read",
        "network.config.parse",
        "network.interface.extract",
        "network.route.extract",
        "report.markdown.render",
        "workspace.artifact.save",
    } <= set(plan["candidate_tools"])
    assert plan["tool_plan"][0]["tool_candidates"][0].startswith("workspace.file.")
    assert plan["tool_plan"][-1]["tool_candidates"][-1] == "workspace.artifact.save"


def test_host_ip_plan_excludes_network_parser():
    plan = _plan("本机 OS 的 IP 是多少")
    assert plan["primary_category"] == "host"
    assert {"host.shell.exec", "host.powershell.exec"} & set(plan["candidate_tools"])
    assert "network.config.parse" not in plan["candidate_tools"]


def test_official_docs_network_plan_combines_web_and_network():
    plan = _plan("根据官方文档看看这个 Cisco OSPF 配置有没有问题")
    assert {"web", "network"} <= set(plan["categories"])
    assert "web.docs.official_search" in plan["candidate_tools"]
    assert "network.config.parse" in plan["candidate_tools"]


def test_missing_path_requests_clarification_or_file_discovery():
    plan = _plan("帮我分析这个配置文件")
    assert plan["needs_clarification"] or {
        "workspace.file.list",
        "workspace.file.read",
        "workspace.file.preview",
    } & set(plan["candidate_tools"])


def test_validator_rejects_legacy_and_invented_tools():
    from agent.runtime.tool_planner import validate_tool_plan
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    available = set(TOOL_NAMESPACE)
    legacy_plan = {
        "candidate_tools": ["file.read"],
        "tool_plan": [{"step": 1, "goal": "read", "tool_candidates": ["file.read"], "required": True}],
        "categories": ["workspace"],
        "groups": {"workspace": ["file"]},
    }
    invented_plan = {
        "candidate_tools": ["network.device.login"],
        "tool_plan": [{"step": 1, "goal": "login", "tool_candidates": ["network.device.login"], "required": True}],
        "categories": ["network"],
        "groups": {"network": ["device"]},
    }
    assert validate_tool_plan(legacy_plan, available, user_input="读文件")[0] is False
    assert validate_tool_plan(invented_plan, available, user_input="登录设备")[0] is False


def test_validator_rejects_host_shell_for_network_config():
    from agent.runtime.tool_planner import validate_tool_plan
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    bad_plan = {
        "candidate_tools": ["network.config.parse", "host.shell.exec"],
        "tool_plan": [
            {"step": 1, "goal": "parse", "tool_candidates": ["network.config.parse"], "required": True},
            {"step": 2, "goal": "shell", "tool_candidates": ["host.shell.exec"], "required": False, "depends_on": [1]},
        ],
        "categories": ["network", "host"],
        "groups": {"network": ["config"], "host": ["shell"]},
    }
    valid, errors = validate_tool_plan(bad_plan, set(TOOL_NAMESPACE), user_input="分析 Cisco 配置")
    assert valid is False
    assert any("host" in e for e in errors)


def test_validator_rejects_invalid_dependencies_and_subsets():
    from agent.runtime.tool_planner import validate_tool_plan
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    bad_plan = {
        "candidate_tools": ["network.config.parse"],
        "tool_plan": [
            {"step": 1, "goal": "parse", "tool_candidates": ["network.route.extract"], "required": True, "depends_on": [2]},
        ],
        "categories": ["network"],
        "groups": {"network": ["config"]},
    }
    valid, errors = validate_tool_plan(bad_plan, set(TOOL_NAMESPACE), user_input="分析配置")
    assert valid is False
    assert errors


def test_context_builder_router_can_use_planner_candidates():
    plan = _plan("帮我分析上传的华三配置，并整理成报告保存", {"uploaded_files": ["h3c.cfg"]})
    router = ToolRouter.for_turn(
        default_runtime_services().tool_service.registry,
        allowed_tool_ids=plan["candidate_tools"],
    )
    names = {tool["function"]["name"] for tool in router.model_visible_tools()}
    assert to_llm_tool_name("network.config.parse") in names
    assert to_llm_tool_name("workspace.file.read") in names
    assert to_llm_tool_name("report.markdown.render") in names
    assert to_llm_tool_name("host.shell.exec") not in names
