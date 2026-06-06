"""Agent LLM policy tests — skeleton, no real LLM, red lines."""

import json, os, urllib.request, pytest

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


class TestLLMSkeleton:
    def test_llm_provider_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "agent", "llm", "provider.py"))

    def test_llm_client_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "agent", "llm", "client.py"))

    def test_llm_schemas_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "agent", "llm", "schemas.py"))

    def test_llm_policy_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "agent", "llm", "policy.py"))

    def test_llm_status_connected_false(self):
        data = _get("/api/agent/status")
        assert data["llm_connected"] is False

    def test_llm_client_not_connected(self):
        from agent.llm.client import LLMClient
        c = LLMClient()
        assert c.is_connected() is False

    def test_policy_contains_red_lines(self):
        from agent.llm.policy import LLM_POLICY
        must_not = LLM_POLICY["must_not"]
        assert "modify_deployable_config" in must_not
        assert "generate_deployable_config" in must_not

    def test_policy_check_valid(self):
        from agent.llm.policy import check_policy
        assert check_policy("explain_configuration") is True

    def test_policy_check_invalid(self):
        from agent.llm.policy import check_policy
        assert check_policy("modify_deployable_config") is False


class TestModuleLLMBoundary:
    def test_config_translation_not_import_agent_llm(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    fp = os.path.join(dirpath, f)
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    assert "agent.llm" not in content, f"agent.llm in {fp}"

    def test_composer_not_call_real_llm(self):
        fp = os.path.join(ROOT, "agent", "nodes", "composer.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "LLMClient" not in content
        assert "chat(" not in content


class TestArchitectureRegression:
    def test_no_backend_services_config_translation(self):
        assert not os.path.exists(os.path.join(ROOT, "backend", "services", "config_translation"))

    def test_no_apps_formal_service(self):
        assert not os.path.isdir(os.path.join(ROOT, "apps"))

    def test_no_external_network_translator_in_sys_path(self):
        import sys
        for p in sys.path:
            assert "network-translator" not in str(p)

    def test_no_os_chdir_in_agent_or_module(self):
        for root_dir in [os.path.join(ROOT, "agent"), os.path.join(ROOT, "modules")]:
            if not os.path.isdir(root_dir): continue
            for dirpath, _, filenames in os.walk(root_dir):
                for f in filenames:
                    if f.endswith(".py"):
                        fp = os.path.join(dirpath, f)
                        with open(fp, encoding="utf-8", errors="replace") as fh:
                            content = fh.read()
                        for line in content.split("\n"):
                            s = line.strip()
                            if s.startswith("#") or s.startswith('"""'): continue
                            if "os.chdir(" in s:
                                pytest.fail(f"os.chdir in {fp}: {s}")

    def test_no_graph_agent_in_module(self):
        ct = os.path.join(ROOT, "modules", "config_translation")
        for dirpath, _, filenames in os.walk(ct):
            for f in filenames:
                if f.endswith(".py"):
                    fp = os.path.join(dirpath, f)
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    for line in content.split("\n"):
                        s = line.strip()
                        if s.startswith("#") or s.startswith('"""'): continue
                        if "GraphAgent" in s:
                            pytest.fail(f"GraphAgent in {fp}: {s}")

    def test_no_legacy_rule_translator(self):
        import glob
        for pattern in ["agent/**/*.py", "modules/config_translation/**/*.py"]:
            for fp in glob.glob(os.path.join(ROOT, pattern), recursive=True):
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                for line in content.split("\n"):
                    s = line.strip()
                    if s.startswith("#") or s.startswith('"""'): continue
                    if "legacy_rule_translator" in s:
                        pytest.fail(f"legacy_rule_translator in {fp}: {s}")


class TestFrontendContract:
    def test_frontend_calls_agent_api(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "/api/agent/run" in content

    def test_frontend_calls_module_api(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "/api/modules/config-translation/translate" in content

    def test_frontend_not_call_old_translate(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert 'fetch("/api/translate"' not in content and "fetch('/api/translate'" not in content

    def test_frontend_has_planned_labels(self):
        fp = os.path.join(ROOT, "frontend", "index.html")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "规划中" in content

    def test_agent_run_from_status(self):
        """Full end-to-end: status → run → verify."""
        status = _get("/api/agent/status")
        assert status["agent_runtime"] in ("langgraph", "fallback")

        run = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei"}})
        assert run["ok"] is True
        assert run["result"]["translator_entry"] == "translate_bundle"
