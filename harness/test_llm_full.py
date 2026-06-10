"""Full LLM integration tests — key, config, provider, runtime, policy, context, composer, agent, API, boundary.

These tests require a LIVE server. Skip by default unless RUN_LIVE_TESTS=1.
Unit tests (config/static checks) run always.
"""

import json, os, sys, urllib.request, urllib.error, pytest

PORT=int(os.environ.get("NETWORK_AGENT_PORT","8010"))
BASE=f"http://127.0.0.1:{PORT}"
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE="interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"

# Skip live HTTP tests by default
_live = os.environ.get("RUN_LIVE_TESTS") == "1"

def _g(p):
    if not _live: pytest.skip("RUN_LIVE_TESTS=1 required for live API tests")
    with urllib.request.urlopen(f"{BASE}{p}",timeout=10) as r: return json.loads(r.read().decode())
def _p(p,b):
    if not _live: pytest.skip("RUN_LIVE_TESTS=1 required for live API tests")
    d=json.dumps(b).encode()
    r=urllib.request.Request(f"{BASE}{p}",data=d,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=30) as resp: return json.loads(resp.read().decode())

# ═══ Config ═══
class TestConfig:
    def test_example_yaml_exists(self):
        assert os.path.isfile(os.path.join(ROOT,"config","llm.example.yaml"))
    def test_yaml_exists(self):
        assert os.path.isfile(os.path.join(ROOT,"config","llm.yaml"))
    def test_local_yaml_ignored(self):
        gli=os.path.join(ROOT,".gitignore")
        with open(gli,encoding="utf-8") as f: assert "llm.local.yaml" in f.read()
    def test_no_key_in_llm_yaml(self):
        with open(os.path.join(ROOT,"config","llm.yaml"),encoding="utf-8") as f:
            c=f.read()
        assert "sk-" not in c and "eyJ" not in c
    def test_key_resolver_env_works(self):
        from agent.llm.key_resolver import resolve_api_key
        os.environ["TEST_KEY"]="test-key-value"
        k=resolve_api_key(env_name="TEST_KEY")
        assert k=="test-key-value"
        del os.environ["TEST_KEY"]
    def test_key_resolver_file_works(self):
        from agent.llm.key_resolver import resolve_api_key, _read_key_from_file
        import tempfile, pathlib
        with tempfile.NamedTemporaryFile(mode="w",suffix=".key",delete=False) as f:
            f.write("my-test-key-12345\n"); fp=f.name
        k=resolve_api_key(file_path=fp)
        assert k is not None
        os.unlink(fp)
    def test_mask_secret(self):
        from agent.llm.key_resolver import mask_secret
        m=mask_secret("abcdefghijklmnop")
        assert "****" in m
        assert len(m)<len("abcdefghijklmnop")
    def test_missing_key_handled(self):
        from agent.llm.key_resolver import resolve_api_key
        k=resolve_api_key(env_name="NONEXISTENT_KEY_12345")
        assert k is None

# ═══ Provider ═══
class TestProvider:
    def test_provider_config_exists(self):
        from agent.llm.provider import get_provider_config
        c=get_provider_config()
        assert "enabled" in c
    def test_health_hides_key(self):
        from agent.llm.provider import health
        h=health({"api_key":"sk-very-secret-key-12345","provider_type":"openai_compatible","base_url":"https://test.com","model":"test","default_provider":"test"})
        assert "sk-" not in str(h)
    def test_mock_works(self):
        from agent.llm.provider import _mock_generate
        from agent.llm.schemas import LLMRequest
        r=_mock_generate(LLMRequest(task="result_summarize",safe_context={"deployable_line_count":5}),{})
        assert r.content
    def test_disabled_provider_unavailable(self):
        from agent.llm.provider import generate
        from agent.llm.schemas import LLMRequest
        r=generate(LLMRequest(task="response_compose"))
        assert r.error is not None

# ═══ Runtime ═══
class TestRuntime:
    def test_disabled_fallback(self, monkeypatch, tmp_path):
        import agent.llm.settings as settings_mod
        from agent.llm.runtime import safe_generate
        from agent.state import NetworkAgentState
        settings_path = tmp_path / "LLM_setting.json"
        settings_path.write_text(json.dumps({
            "enabled": False,
            "provider": "disabled",
            "safe_mode": True,
        }))
        monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)
        s=NetworkAgentState(intent="translate_config")
        o=safe_generate("response_compose",s)
        assert o.llm_used is False
    def test_safe_generate_never_raises(self):
        from agent.llm.runtime import safe_generate
        from agent.state import NetworkAgentState
        s=NetworkAgentState(intent="translate_config")
        try:
            safe_generate("response_compose",s)
        except:
            pytest.fail("safe_generate raised an exception")

# ═══ Policy ═══
class TestPolicy:
    def test_request_blocks_source_config(self):
        from agent.llm.policy import check_request
        from agent.llm.schemas import LLMRequest
        r=LLMRequest(task="response_compose",safe_context={"source_config":"x"*100})
        d=check_request(r)
        assert d.allowed is False
    def test_response_blocks_deployable_code(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r=LLMResponse(content="deployable_config: ```int gi0/1```")
        d=check_response(r)
        assert d.allowed is False
    def test_response_blocks_directly_deployable(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r=LLMResponse(content="可直接下发 now")
        d=check_response(r)
        assert d.allowed is False
    def test_response_allows_safe(self):
        from agent.llm.policy import check_response
        from agent.llm.schemas import LLMResponse
        r=LLMResponse(content="Translation done. 3 lines, 1 needs review.")
        d=check_response(r)
        assert d.allowed is True

# ═══ Context ═══
class TestSafeContext:
    def test_no_source_config(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        s=NetworkAgentState(intent="translate_config",tool_results={"translator_entry":"translate_bundle","deployable_config":"x"*200,"manual_review":[],"unsupported":[],"semantic_near":[],"audit":{}})
        c=build_safe_context(s)
        assert "source_config" not in str(c)
    def test_includes_counts(self):
        from agent.llm.context_builder import build_safe_context
        from agent.state import NetworkAgentState
        s=NetworkAgentState(intent="translate_config",tool_results={"translator_entry":"translate_bundle","deployable_config":"x","manual_review":[{"r":"a"}],"unsupported":[],"semantic_near":[],"audit":{}})
        c=build_safe_context(s)
        assert c["manual_review_count"]==1
    def test_redacts_password(self):
        from agent.llm.context_builder import build_safe_context, _redact_samples
        samples=_redact_samples([{"reason":"set password abc123"}])
        s=str(samples).lower()
        assert "redacted" in s or "password" not in s

# ═══ Composer ═══
class TestComposer:
    def test_deterministic_when_disabled(self):
        from agent.legacy.composer import compose
        from agent.state import NetworkAgentState
        s=NetworkAgentState(intent="translate_config",tool_results={"ok":True,"deployable_config":"x","manual_review":[],"unsupported":[],"semantic_near":[],"audit":{},"translator_entry":"translate_bundle"})
        compose(s)
        assert s.final_response
    def test_no_modify_result(self):
        from agent.legacy.composer import compose
        from agent.state import NetworkAgentState
        r={"ok":True,"deployable_config":"keep","manual_review":[],"unsupported":[],"semantic_near":[],"audit":{},"translator_entry":"translate_bundle"}
        s=NetworkAgentState(intent="translate_config",tool_results=r)
        compose(s)
        assert s.tool_results["deployable_config"]=="keep"

# ═══ API ═══
class TestAPI:
    def test_llm_status_endpoint(self):
        d=_g("/api/agent/llm/status")
        assert "enabled" in d
        assert "key_loaded" in d
        assert "key_source" in d
    def test_llm_test_endpoint(self):
        d=_p("/api/agent/llm/test",{"task":"result_summarize","message":"hello"})
        assert "ok" in d
        assert "llm_used" in d
    def test_agent_status_llm(self):
        d=_g("/api/agent/status")
        assert "llm_enabled" in d or "llm" in str(d).lower()
    def test_agent_run_llm_metadata(self):
        d=_p("/api/agent/run",{"intent":"translate_config","payload":{"source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"}})
        assert "llm" in d
        assert d["ok"] is True
    def test_key_not_returned(self):
        d=_g("/api/agent/llm/status")
        s=str(d)
        # Key preview is allowed (masked), full key is not
        assert "eyj" not in s.lower()
        # key_preview contains **** so it's safe
        assert "****" in str(d.get("key_preview", ""))

# ═══ Agent ═══
class TestAgent:
    def test_translate_via_langgraph(self):
        d=_p("/api/agent/run",{"intent":"translate_config","payload":{"source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"}})
        assert d["ok"] is True
        assert d["runtime_mode"]=="langgraph"
    def test_planned_intents(self):
        for i in ["topology_draw","inspection_analyze","knowledge_search"]:
            d=_p("/api/agent/run",{"intent":i,"payload":{}})
            assert "deployable_config" not in d.get("result",{})

# ═══ Boundary ═══
class TestBoundary:
    def test_module_no_llm(self):
        ct=os.path.join(ROOT,"modules","config_translation")
        for dirpath,_,files in os.walk(ct):
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(dirpath,f),encoding="utf-8",errors="replace") as fh:
                        assert "agent.llm" not in fh.read()
    def test_skill_no_llm(self):
        with open(os.path.join(ROOT,"skills","config_translation","adapter.py"),encoding="utf-8") as f:
            assert "agent.llm" not in f.read()
    def test_executor_no_llm(self):
        """Executor must not import agent.llm or call LLM APIs directly.
        Passing state.context llm metadata is allowed (read-only aggregation)."""
        fp=os.path.join(ROOT,"agent","legacy","skill_executor.py")
        with open(fp,encoding="utf-8") as f:
            content = f.read()
        # Must not import agent.llm
        assert "from agent.llm" not in content
        assert "import agent.llm" not in content
        # Must not call LLM runtime
        assert "safe_generate" not in content
        assert "llm_client" not in content.lower()
    def test_no_old_translate(self):
        d=json.dumps({"x":"y"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/translate",data=d,headers={"Content-Type":"application/json"},method="POST"),timeout=3)
            pytest.fail("/api/translate exists")
        except urllib.error.HTTPError as e:
            assert e.code in (404,405)
    def test_no_backend_services(self):
        assert not os.path.exists(os.path.join(ROOT,"backend","services","config_translation"))
    def test_no_external_path(self):
        for p in sys.path: assert "network-translator" not in str(p)
    def test_no_os_chdir(self):
        for d in ["agent","modules"]:
            for dirpath,_,files in os.walk(os.path.join(ROOT,d)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath,f),encoding="utf-8",errors="replace") as fh:
                            for l in fh.read().split("\n"):
                                s=l.strip()
                                if s.startswith("#") or s.startswith('"""'): continue
                                if "os.chdir(" in s: pytest.fail(f"os.chdir in {os.path.join(dirpath,f)}")
    def test_frontend_has_agent_api(self):
        with open(os.path.join(ROOT,"frontend","index.html"),encoding="utf-8") as f:
            assert "/api/agent/run" in f.read()

# ═══ Security Audit ═══
class TestSecurityAudit:
    def test_audit_script_runs(self):
        import subprocess
        r=subprocess.run([sys.executable,os.path.join(ROOT,"scripts","audit_llm_security.py")],cwd=ROOT,capture_output=True,text=True)
        assert r.returncode==0,f"Audit failed: {r.stderr}"
    def test_audit_json_generated(self):
        assert os.path.isfile(os.path.join(ROOT,"reports","llm_security_audit.json"))
    def test_audit_md_generated(self):
        assert os.path.isfile(os.path.join(ROOT,"reports","LLM_SECURITY_AUDIT.md"))
