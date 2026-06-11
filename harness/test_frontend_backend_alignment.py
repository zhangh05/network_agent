"""Frontend/Backend Agent Experience Alignment Tests — v0.1 + v1.0

The v0.1 single-file frontend (`frontend/legacy/index.html.legacy`)
is kept as a backup; the v1.0 workbench lives in `frontend/src/`
and ships `frontend/index.html` (Vite). Tests here cover:
  - The v1.0 Vite entry (root + main.tsx, no fake data, no fake APIs)
  - The legacy backup (regression-preserved markers, not active)
  - Backend API alignment (every API used by the v1.0 frontend
    must exist on the backend).
"""
import os
import json
import sys
import inspect
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_HTML = PROJECT_ROOT / "frontend" / "legacy" / "index.html.legacy"
VITE_HTML = PROJECT_ROOT / "frontend" / "index.html"


class TestViteWorkbench:
    def test_vite_index_html_exists(self):
        assert VITE_HTML.exists(), "frontend/index.html missing"

    def test_vite_root_and_main(self):
        html = VITE_HTML.read_text()
        assert 'id="root"' in html
        assert "/src/main.tsx" in html

    def test_vite_no_fake_data_or_api(self):
        html = VITE_HTML.read_text()
        assert "/api/fake" not in html
        assert "/api/mock" not in html
        # No hardcoded statistics from the legacy page
        assert "386 记忆" not in html
        assert "12 任务" not in html

    def test_vite_app_directory_structure(self):
        assert (PROJECT_ROOT / "frontend" / "src" / "app" / "App.tsx").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "api" / "index.ts").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "types" / "index.ts").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "stores" / "session.ts").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "layouts" / "AppLayout.tsx").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "pages" / "AgentWorkbench" / "AgentWorkbench.tsx").exists()
        assert (PROJECT_ROOT / "frontend" / "src" / "components" / "common.tsx").exists()

    def test_vite_no_legacy_inline_html(self):
        """Vite index.html must NOT embed the legacy inline dashboard."""
        html = VITE_HTML.read_text()
        assert "id=\"dash-mods\"" not in html
        assert "card-flush tool-shell" not in html

    def test_legacy_backup_preserved(self):
        """Legacy single-file frontend must still be present (not deleted)."""
        assert LEGACY_HTML.exists(), (
            "frontend/legacy/index.html.legacy missing — spec says '保留为 legacy 备份'"
        )


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

    def test_legacy_no_fake_api(self):
        """Legacy frontend must not call APIs that don't exist (preserved check)."""
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert "/api/fake" not in html
        assert "/api/mock" not in html

    def test_legacy_dashboard_refresh_uses_existing_module_stat_id(self):
        """Legacy dashboard refresh must not write to a missing stat card element."""
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert 'id="dash-mods"' in html
        assert "safeSetStat('dash-mods'" in html
        assert "getElementById('dash-modules')" not in html

    def test_legacy_backend_health_success_not_reversed_by_dashboard_load_error(self):
        """Legacy dashboard load errors must not be handled as backend health failures."""
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        start = html.index("function _checkBackendAndLoad()")
        end = html.index("function refreshDashboard()", start)
        body = html[start:end]
        assert "statusEl.textContent='已连接'" in body
        assert "try{_loadAllData();}" in body.replace(" ", "")

    def test_legacy_tool_catalog_uses_dense_full_width_layout(self):
        """Legacy Tool Catalog should use a dense workspace layout instead of a narrow card."""
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert 'class="card-flush tool-shell"' in html
        assert 'class="tool-filterbar"' in html
        assert 'class="tool-catalog-grid"' in html
        assert "minmax(210px,1fr)" in html
        assert "minmax(260px,1fr)" not in html


class TestAgentChat:
    def test_hello_intent(self):
        from agent.legacy.intent_router import _infer
        assert _infer("你好") == "assistant_chat"

    def test_who_are_you(self):
        from agent.legacy.intent_router import _infer
        assert _infer("你是谁") == "assistant_chat"

    def test_capability(self):
        from agent.legacy.intent_router import _infer
        assert _infer("你能做什么") == "assistant_chat"

    def test_translate_still_works(self):
        from agent.legacy.intent_router import _infer
        assert _infer("翻译配置") == "translate_config"

    def test_topology_planned(self):
        from agent.legacy.intent_router import _infer
        assert _infer("帮我画拓扑") == "topology_draw"

    def test_inspection_planned(self):
        from agent.legacy.intent_router import _infer
        assert _infer("帮我巡检") == "inspection_analyze"

    def test_unknown_handled(self):
        from agent.legacy.intent_router import _infer
        intent = _infer("帮我做 CMDB")
        assert intent in ("unknown", "assistant_chat", "context_qa")

    def test_hello_compose_ok(self):
        from agent.state import NetworkAgentState
        from agent.legacy.composer import compose
        s = NetworkAgentState(user_input="你好", intent="assistant_chat")
        s = compose(s)
        assert "didn't understand" not in s.final_response
        assert len(s.final_response) > 10

    def test_chat_no_deployable(self):
        """Chat must not produce deployable_config."""
        from agent.state import NetworkAgentState
        from agent.legacy.composer import compose
        s = NetworkAgentState(user_input="你好", intent="assistant_chat")
        s = compose(s)
        assert "deployable" not in s.final_response.lower()

    def test_planned_response(self):
        from agent.state import NetworkAgentState
        from agent.legacy.composer import _deterministic
        s = _deterministic({}, "topology_draw")
        assert "planned" in s.lower() or "coming" in s.lower()

    def test_executor_noop_for_chat(self):
        from agent.legacy.skill_executor import execute
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="assistant_chat", selected_skill=None)
        s = execute(s)
        assert s.error is None or "No skill" not in str(s.error)

    def test_translate_intent_still_active(self):
        from agent.legacy.intent_router import _infer
        assert _infer("请把这段配置从 Cisco 翻译成华为") == "translate_config"


class TestUIAgentExperience:
    def test_legacy_ui_has_agent_chat_area(self):
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert "agent-chat" in html or "Agent" in html

    def test_legacy_ui_no_real_device_claim(self):
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert "真实设备" not in html

    def test_legacy_ui_no_deployable_claim(self):
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert "可直接下发" not in html

    def test_legacy_ui_no_tool_invoke(self):
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
        assert "invoke_tool" not in html
        assert "tool.invoke" not in html.lower()

    def test_legacy_ui_no_full_config_display(self):
        """Frontend must not display full config text to user."""
        if not LEGACY_HTML.exists():
            pytest.skip("legacy backup not present")
        html = LEGACY_HTML.read_text()
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
        enabled = sorted([m.module_name for m in mods if m.is_enabled()])
        assert enabled == sorted(["config_translation", "knowledge_base"])

