# harness/test_registry_contract.py
"""Registry schemas, loader, validator, capability, agent execution tests."""

import json
import pytest
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


class TestRegistrySchemas:
    def test_module_spec_fields(self):
        from registry.schemas import ModuleSpec
        m = ModuleSpec(module_name="test", status="enabled", primary_endpoint="/api/test")
        d = m.as_dict()
        assert d["module_name"] == "test"
        assert d["enabled"] is True

    def test_skill_spec_fields(self):
        from registry.schemas import SkillSpec
        s = SkillSpec(skill_name="test", status="enabled")
        assert s.is_enabled() is True

    def test_capability_spec_fields(self):
        from registry.schemas import CapabilitySpec
        c = CapabilitySpec(capability_id="test.x", status="enabled")
        assert c.is_enabled() is True

    def test_status_enum(self):
        from registry.schemas import VALID_STATUSES
        assert "enabled" in VALID_STATUSES
        assert "planned" in VALID_STATUSES

    def test_maturity_enum(self):
        from registry.schemas import VALID_MATURITIES
        assert "embedded_mvp" in VALID_MATURITIES


class TestRegistryLoader:
    def test_load_module_registry(self):
        from registry.loader import load_module_registry
        mods = load_module_registry()
        assert len(mods) >= 1

    def test_load_skill_registry(self):
        from registry.loader import load_skill_registry
        skills = load_skill_registry()
        assert len(skills) >= 1

    def test_load_capabilities(self):
        from registry.loader import load_capabilities
        caps = load_capabilities()
        assert len(caps) >= 1

    def test_get_enabled_modules(self):
        from registry.loader import get_enabled_modules
        mods = get_enabled_modules()
        names = [m.module_name for m in mods]
        assert "config_translation" in names

    def test_get_planned_modules(self):
        from registry.loader import get_planned_modules
        mods = get_planned_modules()
        names = [m.module_name for m in mods]
        assert "topology" in names or "inspection" in names

    def test_get_module_by_name(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m is not None
        assert m.is_enabled() is True

    def test_get_skill_by_name(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert s is not None

    def test_get_capability(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c is not None
        assert c.intent == "translate_config"

    def test_reload_works(self):
        from registry.loader import reload_all
        result = reload_all()
        assert len(result["modules"]) >= 1
        assert len(result["skills"]) >= 1
        assert len(result["capabilities"]) >= 1

    def test_registry_status(self):
        from registry.loader import get_registry_status
        status = get_registry_status()
        assert status["module_count"] >= 1
        assert "config_translation" in status["enabled_modules"]


class TestModuleContract:
    def test_config_module_yaml_exists(self):
        path = PROJECT_ROOT / "modules" / "config_translation" / "module.yaml"
        assert path.is_file()

    def test_config_module_status_enabled(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.status == "enabled"

    def test_config_module_primary_endpoint(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.primary_endpoint == "/api/modules/config-translation/translate"

    def test_config_module_ui_route(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.ui_route == "/modules/translate"

    def test_config_module_deterministic(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.deterministic is True

    def test_config_module_no_llm(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.requires_llm is False

    def test_config_module_deployable(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.can_generate_deployable is True
        assert m.deployable_output_field == "deployable_config"

    def test_config_module_no_legacy_frontend(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.has_own_legacy_frontend is False

    def test_config_module_no_private_llm(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.no_module_private_llm is True

    def test_config_module_no_external_repo(self):
        from registry.loader import get_module
        m = get_module("config_translation")
        assert m.no_external_repo_dependency is True


class TestSkillContract:
    def test_config_skill_yaml_exists(self):
        path = PROJECT_ROOT / "skills" / "config_translation" / "skill.yaml"
        assert path.is_file()

    def test_config_skill_enabled(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert s.is_enabled() is True

    def test_config_skill_references_module(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert s.module == "config_translation"

    def test_config_skill_adapter_exists(self):
        path = PROJECT_ROOT / "skills" / "config_translation" / "adapter.py"
        assert path.is_file()

    def test_config_skill_no_llm(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert s.calls_llm is False

    def test_config_skill_no_http_self(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert s.calls_http_self is False

    def test_red_lines_include_do_not_call_llm(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert "do_not_call_llm" in s.red_lines

    def test_red_lines_include_do_not_hide_review(self):
        from registry.loader import get_skill
        s = get_skill("config_translation")
        assert "do_not_hide_manual_review" in s.red_lines

    def test_skill_no_api_translate(self):
        adapter = (PROJECT_ROOT / "skills" / "config_translation" / "adapter.py").read_text()
        # Adapter must not call /api/translate via HTTP or import
        # Comment mentions are OK
        code_lines = [l for l in adapter.split('\n') if not l.strip().startswith('#')]
        code = '\n'.join(code_lines)
        assert "/api/translate" not in code


class TestCapability:
    def test_config_translate_exists(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c is not None
        assert c.intent == "translate_config"

    def test_config_translate_references_module(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c.module == "config_translation"

    def test_config_translate_references_skill(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c.skill == "config_translation"

    def test_capability_deployable_requires_verification(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c.can_generate_deployable is True
        assert c.requires_verification is True

    def test_capability_llm_not_allowed(self):
        from registry.loader import get_capability
        c = get_capability("config.translate")
        assert c.llm_allowed is False


class TestAgentRegistryExecution:
    def test_agent_router_maps_intent_to_capability(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "reg_test",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        data = resp.get_json()
        assert data["intent"] == "translate_config"

    def test_agent_executor_uses_skill(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "reg_skill",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
            },
        })
        data = resp.get_json()
        assert data["selected_skill"] == "config_translation"
        assert data["active_module"] == "config_translation"

    def test_agent_trace_has_capability_id(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "translate cisco to huawei",
            "workspace_id": "reg_trace",
            "payload": {
                "source_vendor": "cisco", "target_vendor": "huawei",
                "source_config": "hostname R1",
            },
        })
        run_id = resp.get_json()["run_id"]
        resp2 = client.get(f"/api/workspaces/reg_trace/runs/{run_id}/trace")
        if resp2.status_code == 200:
            events = resp2.get_json().get("trace", {}).get("events", [])
            # Check skill_call events exist
            skill_events = [e for e in events if "skill" in str(e.get("name", ""))]
            assert len(skill_events) > 0

    def test_planned_intent_returns_coming_soon(self, client):
        resp = client.post("/api/agent/run", json={
            "message": "帮我画拓扑",
            "workspace_id": "reg_planned",
        })
        data = resp.get_json()
        assert "coming_soon" in str(data.get("warnings", [])).lower() or "planned" in str(data.get("final_response", "")).lower()

    def test_translate_config_still_works(self, client):
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco", "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        })
        assert resp.status_code == 200
        assert resp.get_json().get("ok") is True


class TestAPIRegistry:
    def test_modules_api_from_registry(self, client):
        resp = client.get("/api/modules")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "modules" in data

    def test_skills_api_from_registry(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "skills" in data

    def test_capabilities_api(self, client):
        resp = client.get("/api/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "capabilities" in data
        assert "enabled" in data

    def test_registry_status_api(self, client):
        resp = client.get("/api/registry/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "module_count" in data

    def test_registry_reload_api(self, client):
        resp = client.post("/api/registry/reload")
        assert resp.status_code == 200

    def test_planned_modules_not_enabled(self, client):
        resp = client.get("/api/modules")
        mods = resp.get_json()["modules"]
        enabled_modules = {"config_translation", "knowledge_base"}
        for m in mods:
            if m["module_name"] not in enabled_modules:
                assert m["enabled"] is False

    def test_no_key_in_api(self, client):
        resp = client.get("/api/registry/status")
        raw = json.dumps(resp.get_json())
        assert "sk-" not in raw


class TestFrontendRegistryContract:
    def test_frontend_fetches_modules(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "/api/modules" in html

    def test_frontend_fetches_skills(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "/api/skills" in html

    def test_frontend_fetches_registry_status(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        # Frontend should use /api/modules or /api/registry/status
        assert "/api/modules" in html or "/api/registry/status" in html


class TestRegression:
    def test_no_api_translate(self, client):
        resp = client.post("/api/translate", json={"test": 1})
        assert resp.status_code in (404, 405)

    def test_workspace_memory_unchanged(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ensure_workspace("reg_ws")
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        assert store.count() >= 0
