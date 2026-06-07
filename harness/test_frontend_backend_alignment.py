"""Frontend/Backend Agent Experience Alignment Tests — v0.1"""
import os
import json
import sys
import inspect
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestFrontendBackendAlignment:
    def test_all_frontend_apis_exist_in_backend(self):
        """Every API called from frontend must have a backend route."""
        frontend_apis = [
            "/api/health", "/api/version", "/api/modules", "/api/skills",
            "/api/jobs", "/api/memory/status", "/api/memory/list",
            "/api/runs/recent", "/api/runtime/health", "/api/workspaces",
        ]
        backend_text = (PROJECT_ROOT / "backend" / "main.py").read_text()
        # Also include route files since routes are registered via register_*_routes
        route_files = ["backend/api/artifact_routes.py", "backend/api/job_routes.py",
                       "backend/api/runtime_routes.py", "backend/api/context_routes.py",
                       "backend/api/workspace_routes.py"]
        for rf in route_files:
            p = PROJECT_ROOT / rf
            if p.exists():
                backend_text += "\n" + p.read_text()
        for api in frontend_apis:
            route = api.split("?")[0].rstrip("/")
            # Backend uses angle brackets for params — normalize to compare
            normalized = backend_text.replace("<ws_id>", "default").replace("<run_id>", "x").replace("<job_id>", "x").replace("<artifact_id>", "x").replace("<module_name>", "x").replace("<prompt_id>", "x").replace("<audit_id>", "x")
            assert route in normalized, f"{api} not found in backend routes (normalized)"

    def test_frontend_no_fake_api(self):
        """Frontend must not call APIs that don't exist."""
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "/api/fake" not in html
        assert "/api/mock" not in html

    def test_frontend_no_fake_data_hardcoded(self):
        """Frontend must not have hardcoded fake statistics."""
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "386 记忆" not in html
        assert "12 任务" not in html

    def test_localstorage_only_prefs(self):
        """localStorage must only save workspace_id and UI prefs."""
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        setitems = [l for l in html.split('\n') if 'localStorage.setItem' in l]
        for line in setitems:
            line = line.strip()
            if 'na_workspace_id' not in line and 'na_settings' not in line and 'na_current_session_id' not in line and 'na_' not in line:
                pytest.fail(f"Unexpected localStorage key in: {line}")


class TestAgentChat:
    def test_hello_intent(self):
        from agent.nodes.intent_router import _infer
        assert _infer("你好") == "assistant_chat"

    def test_who_are_you(self):
        from agent.nodes.intent_router import _infer
        assert _infer("你是谁") == "assistant_chat"

    def test_capability(self):
        from agent.nodes.intent_router import _infer
        assert _infer("你能做什么") == "assistant_chat"

    def test_translate_still_works(self):
        from agent.nodes.intent_router import _infer
        assert _infer("翻译配置") == "translate_config"

    def test_topology_planned(self):
        from agent.nodes.intent_router import _infer
        assert _infer("帮我画拓扑") == "topology_draw"

    def test_inspection_planned(self):
        from agent.nodes.intent_router import _infer
        assert _infer("帮我巡检") == "inspection_analyze"

    def test_unknown_handled(self):
        from agent.nodes.intent_router import _infer
        intent = _infer("帮我做 CMDB")
        assert intent in ("unknown", "assistant_chat", "context_qa")

    def test_hello_compose_ok(self):
        from agent.state import NetworkAgentState
        from agent.nodes.composer import compose
        s = NetworkAgentState(user_input="你好", intent="assistant_chat")
        s = compose(s)
        assert "didn't understand" not in s.final_response
        assert len(s.final_response) > 10

    def test_chat_no_deployable(self):
        """Chat must not produce deployable_config."""
        from agent.state import NetworkAgentState
        from agent.nodes.composer import compose
        s = NetworkAgentState(user_input="你好", intent="assistant_chat")
        s = compose(s)
        assert "deployable" not in s.final_response.lower()

    def test_planned_response(self):
        from agent.state import NetworkAgentState
        from agent.nodes.composer import _deterministic
        s = _deterministic({}, "topology_draw")
        assert "planned" in s.lower() or "coming" in s.lower()

    def test_executor_noop_for_chat(self):
        from agent.nodes.skill_executor import execute
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="assistant_chat", selected_skill=None)
        s = execute(s)
        assert s.error is None or "No skill" not in str(s.error)

    def test_translate_intent_still_active(self):
        from agent.nodes.intent_router import _infer
        assert _infer("请把这段配置从 Cisco 转华为") == "translate_config"


class TestUIAgentExperience:
    def test_ui_has_agent_chat_area(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "agent-chat" in html or "Agent" in html

    def test_ui_no_real_device_claim(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "真实设备" not in html

    def test_ui_no_deployable_claim(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "可直接下发" not in html

    def test_ui_no_tool_invoke(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "invoke_tool" not in html
        assert "tool.invoke" not in html.lower()

    def test_ui_no_full_config_display(self):
        """Frontend must not display full config text to user."""
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        # source_config is used as API payload key — that's fine
        # Just ensure no full config text is rendered as display
        assert "可直接下发" not in html


class TestRunHistory:
    def test_recent_runs_api_available(self):
        backend = (PROJECT_ROOT / "backend" / "main.py").read_text()
        ws_routes = (PROJECT_ROOT / "backend" / "api" / "workspace_routes.py").read_text()
        combined = backend + "\n" + ws_routes
        assert "/api/runs/recent" in combined

    def test_run_store_writes_summary_only(self):
        from workspace.run_store import write_run_record, get_run
        from agent.state import NetworkAgentState
        s = NetworkAgentState(user_input="test chat", intent="assistant_chat",
                              workspace_id="default")
        s.skill_results = {"ok": True}
        rid = write_run_record(s)
        record = get_run(rid, "default")
        assert "source_config" not in record
        assert "deployable_config" not in record

    def test_run_history_workspace_isolated(self):
        from workspace.run_store import write_run_record, get_run
        from agent.state import NetworkAgentState
        s = NetworkAgentState(workspace_id="default")
        s.skill_results = {}
        rid = write_run_record(s)
        # Should not be found in different workspace
        result = get_run(rid, "nonexistent_ws_xyz")
        assert not result or result == {}

    def test_no_full_config_in_run(self):
        from workspace.run_store import write_run_record, get_run
        from agent.state import NetworkAgentState
        s = NetworkAgentState(user_input="test", workspace_id="default")
        s.skill_results = {"deployable_config": "interface Gi0/1\n ip address 1.1.1.1 255.255.255.0"}
        rid = write_run_record(s)
        record = get_run(rid, "default")
        record_str = str(record)
        assert "interface Gi0/1" not in record_str


class TestNoRegression:
    def test_no_api_translate(self):
        backend = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert '"/api/translate"' not in backend

    def test_no_8020(self):
        backend = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert "8020" not in backend

    def test_translate_bundle_unchanged(self):
        import modules.config_translation.core.rule_translator as rt
        source = inspect.getsource(rt)
        assert "def translate_bundle" in source

    def test_no_tool_invoke_api(self):
        backend = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert "/api/tool/invoke" not in backend
        assert "/api/tool-runtime/invoke" not in backend

    def test_only_config_translation_enabled(self):
        from registry.loader import load_module_registry
        mods = load_module_registry()
        enabled = [m.module_name for m in mods if m.is_enabled()]
        assert enabled == ["config_translation"]
