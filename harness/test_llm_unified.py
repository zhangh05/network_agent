"""Unified LLM Runtime tests — status, provider, schemas, context, policy, runtime, composer, agent, boundary, frontend."""

import json, os, urllib.request, urllib.error, pytest, sys

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"

def _get(p): 
    with urllib.request.urlopen(f"{BASE}{p}", timeout=10) as r: return json.loads(r.read().decode())
def _post(p, b): 
    d = json.dumps(b).encode()
    r = urllib.request.Request(f"{BASE}{p}", data=d, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp: return json.loads(resp.read().decode())

# ═══ LLM Status ═══
class TestLLMStatus:
    def test_default_llm_disabled(self):
        d = _get("/api/agent/status")
        assert d["llm_enabled"] is False
    def test_default_llm_not_connected(self):
        d = _get("/api/agent/status")
        assert d["llm_connected"] is False
    def test_status_exposes_allowed_tasks(self):
        d = _get("/api/agent/status")
        assert len(d["llm_allowed_tasks"]) >= 2
    def test_status_exposes_blocked_tasks(self):
        d = _get("/api/agent/status")
        assert "generate_deployable_config" in d["llm_blocked_tasks"]
    def test_status_exposes_policy_red_lines(self):
        d = _get("/api/agent/status")
        assert len(d["llm_policy_red_lines"]) >= 3
    def test_status_safe_mode_true(self):
        d = _get("/api/agent/status")
        assert d["llm_safe_mode"] is True

# ═══ Schemas ═══
class TestLLMSchemas:
    def test_allowed_tasks(self):
        from agent.llm.schemas import ALLOWED_TASKS
        assert "response_compose" in ALLOWED_TASKS
        assert "context_qa" in ALLOWED_TASKS
    def test_blocked_tasks(self):
        from agent.llm.schemas import BLOCKED_TASKS
        assert "generate_deployable_config" in BLOCKED_TASKS
        assert "modify_deployable_config" in BLOCKED_TASKS
    def test_safe_llm_output_fields(self):
        from agent.llm.schemas import SafeLLMOutput
        s = SafeLLMOutput()
        assert hasattr(s, "llm_used")
        assert hasattr(s, "safe_to_show")
    def test_policy_decision_fields(self):
        from agent.llm.schemas import PolicyDecision
        p = PolicyDecision()
        assert hasattr(p, "violations")

# ═══ Context Builder ═══
class TestContextBuilder:
    def test_safe_context_excludes_full_source(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config", tool_results={
            "translator_entry":"translate_bundle","deployable_config":"x"*200,"manual_review":[],"unsupported":[],"semantic_near":[],"audit":{}})
        ctx = build_safe_context(s)
        assert "source_config" not in str(ctx).lower() or len(str(ctx.get("source_config","")))<80
    def test_safe_context_includes_counts(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config", tool_results={
            "translator_entry":"translate_bundle","deployable_config":"x","manual_review":[{"reason":"test"}],"unsupported":[],"semantic_near":[],"audit":{}})
        ctx = build_safe_context(s)
        assert ctx["manual_review_count"] == 1
    def test_safe_context_limits_samples(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        mr = [{"reason":f"r{i}"} for i in range(10)]
        s = NetworkAgentState(intent="translate_config", tool_results={
            "translator_entry":"translate_bundle","deployable_config":"x","manual_review":mr,"unsupported":[],"semantic_near":[],"audit":{}})
        ctx = build_safe_context(s)
        assert len(ctx["manual_review_samples"]) <= 5
    def test_safe_context_redacts_password(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config", tool_results={
            "translator_entry":"translate_bundle","deployable_config":"x","manual_review":[{"reason":"set password"}],"unsupported":[],"semantic_near":[],"audit":{}})
        ctx = build_safe_context(s)
        samples = str(ctx.get("manual_review_samples",[]))
        assert "password" not in samples.lower() or "REDACTED" in samples

# ═══ Policy ═══
class TestPolicyRequest:
    def test_allows_response_compose(self):
        from agent.llm.policy import check_request
        from agent.llm.schemas import LLMRequest
        r = LLMRequest(task="response_compose")
        d = check_request(r)
        assert d.allowed is True
    def test_blocks_generate_deployable(self):
        from agent.llm.policy import check_request
        from agent.llm.schemas import LLMRequest
        r = LLMRequest(task="generate_deployable_config")
        d = check_request(r)
        assert d.allowed is False
    def test_blocks_unknown_task(self):
        from agent.llm.policy import check_request
        from agent.llm.schemas import LLMRequest
        r = LLMRequest(task="random_stuff")
        d = check_request(r)
        assert d.allowed is False
    def test_blocks_source_config_in_context(self):
        from agent.llm.policy import check_request
        from agent.llm.schemas import LLMRequest
        r = LLMRequest(task="response_compose", safe_context={"source_config":"x"*100})
        d = check_request(r)
        assert d.allowed is False

class TestPolicyResponse:
    def test_allows_safe_response(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r = LLMResponse(content="Translation completed. 3 lines. Review needed.")
        d = check_response(r)
        assert d.allowed is True
    def test_blocks_deployable_code_block(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r = LLMResponse(content="Here is the deployable_config: ```interface Gi0\n```")
        d = check_response(r)
        assert d.allowed is False
    def test_blocks_directly_deployable_claim(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r = LLMResponse(content="You can 可直接下发 now.")
        d = check_response(r)
        assert d.allowed is False

# ═══ Provider ═══
class TestProvider:
    def test_disabled_returns_unavailable(self):
        from agent.llm.provider import get_provider_config
        cfg = get_provider_config()
        assert not cfg["enabled"] or cfg["type"]=="disabled"
    def test_mock_provider_works(self):
        from agent.llm.provider import _mock_generate
        from agent.llm.schemas import LLMRequest
        r = _mock_generate(LLMRequest(task="response_compose", safe_context={"deployable_line_count":3}), {})
        assert r.content
        assert r.provider == "mock"

# ═══ Runtime ═══
class TestRuntime:
    def test_disabled_runtime_fallback(self):
        from agent.llm.runtime import safe_generate
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config")
        o = safe_generate("response_compose", s)
        assert o.llm_used is False
        assert o.fallback_reason == "llm_disabled"

# ═══ Composer ═══
class TestComposer:
    def test_llm_disabled_uses_deterministic(self):
        from agent.nodes.composer import compose
        from agent.state import NetworkAgentState
        s = NetworkAgentState(intent="translate_config", tool_results={"ok":True,"deployable_config":"x\n","manual_review":[],"unsupported":[],"semantic_near":[],"audit":{},"translator_entry":"translate_bundle"})
        compose(s)
        assert s.final_response
        assert "completed" in s.final_response.lower() or "configuration" in s.final_response.lower()
    def test_composer_no_modify_result(self):
        from agent.nodes.composer import compose
        from agent.state import NetworkAgentState
        result = {"ok":True,"deployable_config":"unchanged","manual_review":[],"unsupported":[],"semantic_near":[],"audit":{},"translator_entry":"translate_bundle"}
        s = NetworkAgentState(intent="translate_config", tool_results=result)
        compose(s)
        assert s.tool_results["deployable_config"] == "unchanged"
    def test_composer_records_llm_context(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{"source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"}})
        assert "llm" in d
        assert "enabled" in d["llm"]

# ═══ Agent Integration ═══
class TestAgentIntegration:
    def test_translate_succeeds_no_llm(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{"source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"}})
        assert d["ok"] is True
        assert d["runtime_mode"] == "langgraph"
    def test_planned_no_fake(self):
        d = _post("/api/agent/run", {"intent":"topology_draw","payload":{}})
        assert "deployable_config" not in d.get("result",{})
    def test_manual_review_present(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{"source_config":"router bgp 65001\n neighbor 10.0.0.2 remote-as 65002","source_vendor":"cisco","target_vendor":"huawei"}})
        assert "manual_review" in d["result"]
    def test_memory_works(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{"source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"},"workspace_id":"llm-test"})
        assert d["memory_written"] is True

# ═══ Boundary ═══
class TestBoundary:
    def test_module_no_import_agent_llm(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, files in os.walk(ct):
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                        assert "agent.llm" not in fh.read()
    def test_skill_adapter_no_llm(self):
        with open(os.path.join(ROOT, "skills", "config_translation", "adapter.py"), encoding="utf-8") as f:
            assert "agent.llm" not in f.read()
    def test_executor_no_llm(self):
        with open(os.path.join(ROOT, "agent", "nodes", "skill_executor.py"), encoding="utf-8") as f:
            for line in f.read().split("\n"):
                s = line.strip()
                if s.startswith("#") or s.startswith('"""'): continue
                assert "llm" not in s.lower().replace('null','')
    def test_no_old_translate(self):
        data = json.dumps({"x":"y"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/translate", data=data, headers={"Content-Type":"application/json"}, method="POST"), timeout=3)
            pytest.fail("/api/translate should not exist")
        except urllib.error.HTTPError as e:
            assert e.code in (404,405)
    def test_no_backend_services(self):
        assert not os.path.exists(os.path.join(ROOT, "backend","services","config_translation"))
    def test_no_external_path(self):
        for p in sys.path: assert "network-translator" not in str(p)
    def test_no_os_chdir(self):
        for d in ["agent","modules"]:
            for dirpath,_,files in os.walk(os.path.join(ROOT,d)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath,f), encoding="utf-8", errors="replace") as fh:
                            for line in fh.read().split("\n"):
                                s = line.strip()
                                if s.startswith("#") or s.startswith('"""'): continue
                                if "os.chdir(" in s: pytest.fail(f"os.chdir in {os.path.join(dirpath,f)}: {s}")
    def test_frontend_agent_api(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            assert "/api/agent/run" in f.read()

# ═══ Frontend ═══
class TestFrontend:
    def test_frontend_shows_llm_status(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            c = f.read()
        assert "llm" in c.lower() or "LLM" in c or "AI" in c
    def test_frontend_direct_translate(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            assert "/api/modules/config-translation/translate" in f.read()
    def test_frontend_not_old_api(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            c = f.read()
        assert 'fetch("/api/translate"' not in c and "fetch('/api/translate'" not in c
