"""LangGraph Runtime Activation tests — verify langgraph is the active runtime."""

import json, os, urllib.request, urllib.error, pytest, sys

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


# ═══════════ Dependency / Runtime ═══════════

class TestDependencyRuntime:
    def test_langgraph_import_succeeds(self):
        from langgraph.graph import StateGraph, END
        assert StateGraph is not None

    def test_build_graph_exists(self):
        from agent.graph import _build_langgraph
        app = _build_langgraph()
        assert app is not None

    def test_graph_compile_ok(self):
        from agent.graph import _build_langgraph
        app = _build_langgraph()
        nodes = list(app.get_graph().nodes.keys())
        assert len(nodes) >= 7

    def test_status_agent_runtime_langgraph(self):
        data = _get("/api/agent/status")
        assert data["agent_runtime"] == "langgraph"

    def test_status_langgraph_available_true(self):
        data = _get("/api/agent/status")
        assert data["langgraph_available"] is True

    def test_status_fallback_available_true(self):
        data = _get("/api/agent/status")
        assert data["fallback_available"] is True

    def test_status_llm_connected_false(self):
        data = _get("/api/agent/status")
        assert data["llm_connected"] is False

    def test_status_graph_compile_ok(self):
        data = _get("/api/agent/status")
        assert data["graph_compile_ok"] is True

    def test_graph_nodes_complete(self):
        data = _get("/api/agent/status")
        nodes = data.get("graph_nodes", [])
        required = ["router","context","planner","executor","verifier","composer","memory"]
        for n in required:
            assert n in nodes, f"missing graph node: {n}"


# ═══════════ Agent Run via LangGraph ═══════════

class TestAgentRunLangGraph:
    def test_runtime_mode_langgraph(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["runtime_mode"] == "langgraph"

    def test_result_deployable_config(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "deployable_config" in d["result"]

    def test_result_manual_review(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "manual_review" in d["result"]

    def test_result_audit(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "audit" in d["result"]

    def test_result_translator_entry(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["result"].get("translator_entry") == "translate_bundle"

    def test_active_module_config_translation(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["active_module"] == "config_translation"

    def test_selected_skill_config_translation(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["selected_skill"] == "config_translation"

    def test_verification_pass(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["verification"].get("status") == "pass"

    def test_final_response_exists(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d.get("final_response")

    def test_memory_written_true(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"},
            "workspace_id":"test-act"})
        assert d["memory_written"] is True


# ═══════════ Planned Intents via LangGraph ═══════════

class TestPlannedViaLangGraph:
    def test_topology_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"topology_draw","payload":{}})
        assert d["runtime_mode"] == "langgraph"
        assert "coming_soon" in (d.get("final_response","") + str(d.get("warnings",""))).lower()

    def test_inspection_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"inspection_analyze","payload":{}})
        assert d["runtime_mode"] == "langgraph"

    def test_knowledge_coming_soon(self):
        d = _post("/api/agent/run", {"intent":"knowledge_search","payload":{}})
        assert d["runtime_mode"] == "langgraph"

    def test_planned_no_fake_result(self):
        d = _post("/api/agent/run", {"intent":"topology_draw","payload":{}})
        assert "deployable_config" not in d.get("result",{})


# ═══════════ Boundary ═══════════

class TestBoundary:
    def test_executor_not_import_module_service(self):
        fp = os.path.join(ROOT, "agent", "nodes", "skill_executor.py")
        with open(fp, encoding="utf-8") as f:
            assert "modules.config_translation.backend.service" not in f.read()

    def test_agent_api_no_http_self(self):
        fp = os.path.join(ROOT, "backend", "api", "agent.py")
        with open(fp, encoding="utf-8") as f:
            assert "urllib" not in f.read()

    def test_no_old_translate_route(self):
        data = json.dumps({"source_config": "x"}).encode()
        req = urllib.request.Request(f"{BASE}/api/translate", data=data, headers={"Content-Type":"application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
            pytest.fail("/api/translate POST should not exist")
        except urllib.error.HTTPError as e:
            assert e.code in (404, 405), f"POST /api/translate returned {e.code}"

    def test_no_backend_services(self):
        assert not os.path.exists(os.path.join(ROOT, "backend","services","config_translation"))

    def test_no_external_path(self):
        for p in sys.path:
            assert "network-translator" not in str(p)

    def test_no_os_chdir(self):
        for root_dir in [os.path.join(ROOT, "agent"), os.path.join(ROOT, "modules")]:
            for dirpath, _, filenames in os.walk(root_dir):
                for f in filenames:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                            for line in fh.read().split("\n"):
                                s = line.strip()
                                if s.startswith("#") or s.startswith('"""'): continue
                                if "os.chdir(" in s:
                                    pytest.fail(f"os.chdir in {os.path.join(dirpath, f)}: {s}")

    def test_module_not_import_agent_llm(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    with open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                        assert "agent.llm" not in fh.read()

    def test_composer_not_call_llm(self):
        fp = os.path.join(ROOT, "agent", "nodes", "composer.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "LLMClient" not in content

    def test_frontend_calls_agent_api(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            assert "/api/agent/run" in f.read()

    def test_frontend_not_call_old_api(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            c = f.read()
        assert 'fetch("/api/translate"' not in c and "fetch('/api/translate'" not in c


# ═══════════ Fallback ═══════════

class TestFallback:
    def test_fallback_status_available(self):
        data = _get("/api/agent/status")
        assert data["fallback_available"] is True

    def test_fallback_can_run(self):
        """Verify graph.py _run_fallback is callable."""
        from agent.graph import _run_fallback
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config", payload={
            "source_config": SAMPLE, "source_vendor": "cisco", "target_vendor": "huawei"})
        result = _run_fallback(s)
        assert result.error is None or result.error == ""
