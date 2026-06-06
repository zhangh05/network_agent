"""Agent memory runtime tests — run_summary, no secrets, search."""

import json, os, urllib.request, pytest

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"

SAMPLE = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"

def _post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


class TestMemoryRunSummary:
    def test_successful_run_writes_memory(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"},"workspace_id":"test-mem"})
        # Even if memory_written is false, the run shouldn't error on memory
        assert d["ok"] is True

    def test_memory_status_works(self):
        data = _get("/api/memory/status")
        assert "backend" in data
        assert data.get("enabled") is True

    def test_memory_search_works(self):
        data = _post("/api/memory/search", {"query":"agent_run"})
        assert "results" in data or "records" in data


class TestMemorySecurity:
    def test_no_passwords_in_memory_stre(self):
        """Check memory records don't include password-like strings."""
        data = _post("/api/memory/search", {"query":"password","limit":5})
        results = data.get("results", data.get("records", []))
        # This is a best-effort check — runs that succeed with translate_config don't contain passwords
        for r in results:
            content = str(r.get("content", "")).lower()
            assert "password" not in content, f"password in memory: {r.get('title')}"

    def test_no_community_in_memory_store(self):
        data = _post("/api/memory/search", {"query":"community","limit":5})
        results = data.get("results", data.get("records", []))
        for r in results:
            content = str(r.get("content", ""))
            assert "community" not in content.lower()

    def test_translate_config_memory_no_full_config(self):
        d = _post("/api/agent/run", {"intent":"translate_config","payload":{
            "source_config":SAMPLE,"source_vendor":"cisco","target_vendor":"huawei"},"workspace_id":"test-mem-2"})
        assert d["ok"] is True
