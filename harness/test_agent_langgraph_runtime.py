"""Agent LangGraph runtime tests — status, workflow, state, nodes."""

import json, os, urllib.request, urllib.error, pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"

def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read().decode())

def _post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


class TestAgentStatus:
    def test_status_exists(self):
        data = _get("/api/agent/status")
        assert "agent_runtime" in data

    def test_status_reports_intents(self):
        data = _get("/api/agent/status")
        assert "supported_intents" in data
        assert "translate_config" in data["supported_intents"]

    def test_status_reports_skills(self):
        data = _get("/api/agent/status")
        assert "enabled_skills" in data
        assert "config_translation" in data["enabled_skills"]

    def test_status_reports_modules(self):
        data = _get("/api/agent/status")
        assert "enabled_modules" in data
        assert "config_translation" in data["enabled_modules"]

    def test_llm_connected_false(self):
        data = _get("/api/agent/status")
        assert data["llm_connected"] is False

    def test_fallback_available_true(self):
        data = _get("/api/agent/status")
        assert data["fallback_available"] is True


class TestLangGraphCode:
    def test_graph_module_exists(self):
        fp = os.path.join(ROOT, "agent", "graph.py")
        assert os.path.isfile(fp)

    def test_graph_exposes_run_agent(self):
        from agent.graph import run_agent
        assert callable(run_agent)

    def test_graph_exposes_get_runtime_status(self):
        from agent.graph import get_runtime_status
        assert callable(get_runtime_status)

    def test_graph_has_langgraph_or_fallback(self):
        from agent.graph import _LANGGRAPH_AVAILABLE, _run_fallback
        assert callable(_run_fallback)

    def test_state_has_required_fields(self):
        from agent.state import NetworkAgentState
        s = NetworkAgentState()
        required = ["request_id","intent","active_module","workspace_id","selected_skill",
                    "payload","plan","tool_calls","tool_results","verification","final_response",
                    "warnings","runtime_mode","created_at"]
        for f in required:
            assert hasattr(s, f), f"missing field: {f}"

    def test_no_global_state(self):
        import agent.nodes.intent_router as ir
        source = open(ir.__file__).read()
        assert "global" not in source


class TestAgentRunTranslate:
    def test_translate_succeeds(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["ok"] is True

    def test_result_has_deployable_config(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "deployable_config" in d["result"]

    def test_result_has_manual_review(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "manual_review" in d["result"]

    def test_result_has_audit(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "audit" in d["result"]

    def test_verification_exists(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "verification" in d

    def test_translator_entry_correct(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["result"].get("translator_entry") == "translate_bundle"

    def test_final_response_exists(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d.get("final_response")

    def test_active_module_is_config_translation(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["active_module"] == "config_translation"

    def test_selected_skill_is_config_translation(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["selected_skill"] == "config_translation"


class TestPlannedIntents:
    def test_topology_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"topology_draw","payload":{}})
        assert "coming_soon" in (d.get("final_response","") + str(d.get("warnings",""))).lower()

    def test_inspection_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"inspection_analyze","payload":{}})
        assert "coming_soon" in (d.get("final_response","") + str(d.get("warnings",""))).lower()

    def test_knowledge_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"knowledge_search","payload":{}})
        assert "coming_soon" in (d.get("final_response","") + str(d.get("warnings",""))).lower()

    def test_planned_no_fake_result(self):
        d = _post("/api/agent/run", {"intent":"topology_draw","payload":{}})
        assert "deployable_config" not in d.get("result",{})
