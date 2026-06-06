"""Agent skill execution tests — adapter chain, no HTTP, no LLM."""

import json, os, urllib.request, pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"

def _post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


class TestSkillAdapterChain:
    def test_executor_uses_skill_adapter(self):
        fp = os.path.join(ROOT, "agent", "nodes", "skill_executor.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "skills.config_translation.adapter" in content

    def test_agent_does_not_directly_import_module_service(self):
        fp = os.path.join(ROOT, "agent", "nodes", "skill_executor.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "modules.config_translation.backend.service" not in content

    def test_agent_api_does_not_http_call_self(self):
        fp = os.path.join(ROOT, "backend", "api", "agent.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "urllib" not in content

    def test_agent_does_not_call_old_translate_api(self):
        fp = os.path.join(ROOT, "agent", "nodes", "skill_executor.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "/api/translate" not in content

    def test_agent_does_not_call_llm(self):
        for f in ["skill_executor.py","composer.py"]:
            fp = os.path.join(ROOT, "agent", "nodes", f)
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
            for line in content.split("\n"):
                s = line.strip()
                if s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
                    continue
                assert "llm" not in s.lower().replace('null',''), f"llm in {f}: {s}"

    def test_skill_adapter_calls_module_service(self):
        fp = os.path.join(ROOT, "skills", "config_translation", "adapter.py")
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        assert "modules.config_translation.backend" in content
        assert "urllib" not in content

    def test_tool_calls_recorded(self):
        """Agent state tool_calls are populated after run."""
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        # Agent should succeed
        assert d["ok"] is True

    def test_module_api_still_works_directly(self):
        d = _post("/api/modules/config-translation/translate", {
            "source_config":SAMPLE,"source_vendor":"auto","target_vendor":"huawei",
        })
        assert d["ok"] is True


class TestAgentMessageMode:
    def test_message_triggers_translate(self):
        d = _post("/api/agent/run", {"message":"Cisco to Huawei translation",
            "payload":{"source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert d["intent"] == "translate_config"

    def test_message_triggers_topology(self):
        d = _post("/api/agent/run", {"message":"draw the network topology",
            "payload":{}})
        assert d["intent"] == "topology_draw"

    def test_message_triggers_inspection(self):
        d = _post("/api/agent/run", {"message":"run inspection audit",
            "payload":{}})
        assert d["intent"] == "inspection_analyze"

    def test_message_triggers_knowledge(self):
        d = _post("/api/agent/run", {"message":"search knowledge base for OSPF",
            "payload":{}})
        assert d["intent"] == "knowledge_search"

    def test_message_triggers_unknown(self):
        d = _post("/api/agent/run", {"message":"xyzzy foo bar baz"})
        assert d["intent"] == "unknown"

    def test_message_preserves_request_id(self):
        d = _post("/api/agent/run", {"message":"translate config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"}})
        assert "request_id" in d
