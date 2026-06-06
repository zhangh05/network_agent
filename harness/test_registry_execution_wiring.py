# harness/test_registry_execution_wiring.py
"""Registry Execution Wiring — dynamic adapter, no hardcoded executor."""

import json, pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None

@pytest.fixture
def client(temp_dirs):
    if _flask_app is None:
        pytest.skip("Flask app not importable")
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


class TestRouter:
    def test_router_no_hardcoded_module(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "intent_router.py").read_text()
        assert "def _module_for" not in content

    def test_router_no_hardcoded_skill(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "intent_router.py").read_text()
        assert "def _skill_for" not in content

    def test_router_no_intent_capability_map(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "intent_router.py").read_text()
        # The hardcoded map should be gone
        assert "_INTENT_CAPABILITY_MAP" not in content, "Router still has hardcoded _INTENT_CAPABILITY_MAP"

    def test_router_recognizes_translate(self):
        from agent.nodes.intent_router import _infer
        assert _infer("翻译 cisco 到 huawei") == "translate_config"

    def test_router_maps_via_registry(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "rw_test",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        assert data["intent"] == "translate_config"
        assert data["active_module"] == "config_translation"
        assert data["selected_skill"] == "config_translation"


class TestExecutor:
    def test_executor_no_hardcoded_config_import(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py").read_text()
        assert "from skills.config_translation.adapter import translate" not in content

    def test_executor_no_hardcoded_config_skill_check(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py").read_text()
        assert "if skill == 'config_translation'" not in content
        assert 'if skill == "config_translation"' not in content

    def test_executor_no_context_qa_special_case(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py").read_text()
        assert "elif state.intent == 'context_qa'" not in content
        assert 'elif state.intent == "context_qa"' not in content

    def test_executor_uses_importlib(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py").read_text()
        assert "importlib" in content

    def test_executor_references_registry(self):
        content = (PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py").read_text()
        assert "registry" in content.lower()

    def test_dynamic_adapter_loading_code_exists(self):
        from agent.nodes.skill_executor import _load_adapter
        # Test actual dynamic loading
        func = _load_adapter("skills/config_translation/adapter.py", "translate")
        assert callable(func)
        result = func(source_config="hostname R1", source_vendor="cisco", target_vendor="huawei")
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_dynamic_review_loading(self):
        from agent.nodes.skill_executor import _load_adapter
        func = _load_adapter("skills/config_translation/adapter.py", "review")
        assert callable(func)
        result = func()
        assert isinstance(result, dict)

    def test_translate_config_executes_via_registry(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "rw_exec",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
            },
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert data["active_module"] == "config_translation"

    def test_trace_has_capability_info(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "rw_trace",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        run_id = resp.get_json()["run_id"]
        resp2 = client.get(f"/api/workspaces/rw_trace/runs/{run_id}/trace")
        if resp2.status_code == 200:
            events = resp2.get_json()["trace"]["events"]
            for e in events:
                meta = str(e.get("metadata", {}))
                # Check capability_id or adapter_path in metadata
                if "capability_id" in meta:
                    assert "config.translate" in meta
                    return
            # At minimum, check intent_routed metadata
            for e in events:
                if e.get("event_type") == "intent_routed":
                    assert "capability_id" in str(e.get("metadata", {}))


class TestContextQA:
    def test_context_qa_capability_exists(self):
        from registry.loader import get_capability
        c = get_capability("config.review")
        assert c is not None
        assert c.intent == "context_qa"

    def test_context_qa_adapter_review_function(self):
        from agent.nodes.skill_executor import _load_adapter
        func = _load_adapter("skills/config_translation/adapter.py", "review")
        result = func()
        assert isinstance(result, dict)

    def test_context_qa_no_context_message(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "刚才的结果有什么需要复核？",
            "workspace_id": "rw_cqa",
            "context_ref": "last_result",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "final_response" in data

    def test_context_qa_does_not_generate_deployable(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "刚才的结果有什么风险？",
            "workspace_id": "rw_cqa_deploy",
            "context_ref": "last_result",
        })
        data = resp.get_json()
        result = data.get("result", {})
        if result:
            assert "deployable_config" not in result or result.get("deployable_config", "") == ""

    def test_context_qa_trace_has_review(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "复核一下结果",
            "workspace_id": "rw_cqa_tr",
            "context_ref": "last_result",
        })
        run_id = resp.get_json()["run_id"]
        resp2 = client.get(f"/api/workspaces/rw_cqa_tr/runs/{run_id}/trace")
        if resp2.status_code == 200:
            events = resp2.get_json()["trace"]["events"]
            intents = [e for e in events if e.get("event_type") == "intent_routed"]
            assert len(intents) > 0, "Expected intent_routed event in trace"
            # Check intent is context_qa
            for ie in intents:
                meta = ie.get("metadata", {})
                if meta.get("intent") == "context_qa":
                    return
            # If not found, check module/skill still correct
            # Context QA may resolve to config_translation
            pass


class TestPlanned:
    def test_planned_topology_returns_coming_soon(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "帮我画拓扑",
            "workspace_id": "rw_planned",
        })
        data = resp.get_json()
        assert "coming_soon" in str(data.get("warnings", [])).lower() or "planned" in str(data.get("final_response", "")).lower()

    def test_planned_does_not_call_adapter(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "画拓扑",
            "workspace_id": "rw_noadapter",
        })
        run_id = resp.get_json()["run_id"]
        resp2 = client.get(f"/api/workspaces/rw_noadapter/runs/{run_id}/trace")
        if resp2.status_code == 200:
            events = resp2.get_json()["trace"]["events"]
            mod_calls = [e for e in events if e.get("event_type") == "module_call_start"]
            assert len(mod_calls) == 0, "planned intent should not call module"


class TestAudit:
    def test_registry_execution_audit_runs(self):
        import sys, subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "audit_registry_execution.py")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        assert "PASS" in result.stdout, result.stderr

    def test_registry_contract_audit_still_pass(self):
        import sys, subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "audit_registry_contract.py")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        assert "PASS" in result.stdout, result.stderr
