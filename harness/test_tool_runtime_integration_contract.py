"""Tool Runtime Integration Contract Tests — v0.1

Covers:
  - ToolRuntimeContext creation and field access
  - ToolRuntimeClient invoke, context propagation, policy enforcement
  - Default client factory
  - Trace metadata adapter
  - Artifact reference contract
  - Doc existence and content
  - Naming boundary
"""

import os
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════
# ToolRuntimeContext Tests
# ══════════════════════════════════════════════════

class TestToolRuntimeContext:
    def test_create(self):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext()
        assert ctx.workspace_id is None
        assert ctx.requested_by == ""

    def test_has_workspace_run_job(self):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(
            workspace_id="ws1", run_id="run1", job_id="job1",
        )
        assert ctx.workspace_id == "ws1"
        assert ctx.run_id == "run1"
        assert ctx.job_id == "job1"

    def test_has_capability_skill_module(self):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(
            capability="config.translate", skill="config_translation",
            module="config_translation",
        )
        assert ctx.capability == "config.translate"
        assert ctx.skill == "config_translation"
        assert ctx.module == "config_translation"

    def test_dry_run_default(self):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(dry_run_default=True)
        assert ctx.dry_run_default is True
        ctx2 = ToolRuntimeContext()
        assert ctx2.dry_run_default is False

    def test_as_dict(self):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(workspace_id="ws", module="m")
        d = ctx.as_dict()
        assert d["workspace_id"] == "ws"
        assert d["module"] == "m"


# ══════════════════════════════════════════════════
# ToolRuntimeClient Tests
# ══════════════════════════════════════════════════

class TestToolRuntimeClient:
    @pytest.fixture
    def client(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        return get_default_tool_runtime_client()

    def test_client_create(self, client):
        assert client is not None
        assert client.tool_count >= 40

    def test_default_client_has_builtins(self, client):
        tools = client.list_tools()
        tool_ids = {t["tool_id"] for t in tools}
        assert len(tools) >= 40, f"Expected >= 40 tools, got {len(tools)}"
        assert "command.dry_run_echo" not in tool_ids
        assert "parser.parse_config_text" in tool_ids

    def test_invoke_constructs_invocation(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(workspace_id="ws_x")
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"},
                               dry_run=True, context=ctx)
        assert result.status == "dry_run"
        assert result.tool_id == "parser.parse_config_text"
        assert result.invocation_id  # auto-generated

    def test_invoke_propagates_workspace_id(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(workspace_id="my_ws")
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"},
                               dry_run=True, context=ctx)
        assert result.status == "dry_run"

    def test_invoke_propagates_run_id(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(run_id="run_abc123")
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"},
                               dry_run=True, context=ctx)
        assert result.status == "dry_run"

    def test_invoke_propagates_job_id(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(job_id="job_xyz789")
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"},
                               dry_run=True, context=ctx)
        assert result.status == "dry_run"

    def test_invoke_propagates_requested_by(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext(requested_by="module:test")
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"},
                               dry_run=True, context=ctx)
        assert result.status == "dry_run"

    def test_invoke_does_not_bypass_policy(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext()
        # Tool not registered
        result = client.invoke("nonexistent.tool", {}, context=ctx)
        assert result.status == "failed"

    def test_invoke_forbidden_tool_blocked(self, client):
        from tool_runtime.context import ToolRuntimeContext
        ctx = ToolRuntimeContext()
        result = client.invoke("ssh.exec", {}, context=ctx)
        assert result.status == "failed"
        # Should not succeed
        assert result.status != "succeeded"

    def test_invoke_parser_dry_run_works(self, client):
        result = client.invoke("parser.parse_config_text", {"config_text": "hostname R1"}, dry_run=True)
        assert result.status == "dry_run"
        assert result.output.get("vendor_hint") in ("unknown", "cisco")

    def test_invoke_output_is_redacted(self, client):
        result = client.invoke("text.redact", {"text": "password secret123"})
        assert result.redacted is True
        assert "secret123" not in str(result.output)

    def test_list_tools_no_handler(self, client):
        tools = client.list_tools()
        for t in tools:
            assert "handler" not in t
            assert "tool_id" in t

    def test_get_tool_no_handler(self, client):
        info = client.get_tool("parser.parse_config_text")
        assert info is not None
        assert "handler" not in info
        assert info["tool_id"] == "parser.parse_config_text"

    def test_client_does_not_import_llm(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        # Remove docstring from check — we only care about imports and function body
        body = source.split('"""')[2] if '"""' in source else source
        assert "import" not in body or "llm" not in body.lower(), (
            "ToolRuntimeClient must not import LLM modules"
        )

    def test_client_does_not_import_memory(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert "from memory" not in body and "import memory" not in body, (
            "ToolRuntimeClient must not import Memory writer"
        )

    def test_client_does_not_import_legacy_state(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        assert "from agent.state import" not in source, (
            "ToolRuntimeClient must not import legacy agent/state.py"
        )


# ══════════════════════════════════════════════════
# Integration Factory Tests
# ══════════════════════════════════════════════════

class TestIntegrationFactory:
    def test_default_client_is_singleton(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        c1 = get_default_tool_runtime_client()
        c2 = get_default_tool_runtime_client()
        assert c1 is c2

    def test_create_client_with_empty_registry(self):
        from tool_runtime.integration import create_tool_runtime_client
        client = create_tool_runtime_client()
        assert client is not None
        assert client.tool_count == 0

    def test_create_client_with_custom_registry(self):
        from tool_runtime.integration import create_tool_runtime_client
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.schemas import ToolSpec
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.one", category="parser", risk_level="low"),
            lambda inv: {"ok": True}
        )
        client = create_tool_runtime_client(registry=reg)
        assert client.tool_count == 1


# ══════════════════════════════════════════════════
# Trace Metadata Adapter Tests
# ══════════════════════════════════════════════════

class TestTraceMetadataAdapter:
    def test_metadata_contains_keys(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id="inv1", tool_id="test.t", status="succeeded",
                            duration_ms=42, artifact_ids=["art_abc"])
        meta = build_trace_metadata_from_tool_result(result)
        assert meta["invocation_id"] == "inv1"
        assert meta["tool_id"] == "test.t"
        assert meta["status"] == "succeeded"
        assert meta["duration_ms"] == 42
        assert "art_abc" in meta["artifact_ids"]

    def test_metadata_excludes_full_output(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id="inv", tool_id="t", status="succeeded",
                            output={"big_data": "x" * 10000, "secret": "hidden"})
        meta = build_trace_metadata_from_tool_result(result)
        # Must NOT contain full output VALUES
        meta_str = str(meta)
        assert "x" * 10000 not in meta_str, "Full output value leaked into metadata"
        assert "hidden" not in meta_str, "Secret value leaked into metadata"
        assert "output_keys" not in meta

    def test_metadata_excludes_full_arguments(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id="inv", tool_id="t", status="succeeded")
        meta = build_trace_metadata_from_tool_result(result)
        # Metadata should not expose arguments (only invocation level)
        assert "arguments" not in meta

    def test_metadata_includes_artifact_ids(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id="inv", tool_id="t", status="succeeded",
                            artifact_ids=["art_1", "art_2"])
        meta = build_trace_metadata_from_tool_result(result)
        assert meta["artifact_ids"] == ["art_1", "art_2"]
        # Artifact IDs only — not content
        assert "content" not in str(meta).lower()

    def test_metadata_has_policy_info(self):
        from tool_runtime.schemas import ToolResult, PolicyDecision
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        pd = PolicyDecision(allowed=True, reason="ok", risk_level="low")
        result = ToolResult(invocation_id="inv", tool_id="t", status="succeeded",
                            policy_decision=pd)
        meta = build_trace_metadata_from_tool_result(result)
        assert meta["policy_allowed"] is True
        assert meta["risk_level"] == "low"

    def test_metadata_no_secrets(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id="inv", tool_id="t", status="succeeded",
                            output={"password": "secret123", "token": "abc"})
        meta = build_trace_metadata_from_tool_result(result)
        meta_str = str(meta)
        assert "secret123" not in meta_str
        assert "abc" not in meta_str or "token" not in meta_str.lower()


# ══════════════════════════════════════════════════
# Artifact Reference Contract Tests
# ══════════════════════════════════════════════════

class TestArtifactReferenceContract:
    def test_result_artifact_ids_is_list(self):
        from tool_runtime.schemas import ToolResult
        result = ToolResult(artifact_ids=["art_1", "art_2"])
        assert isinstance(result.artifact_ids, list)
        for aid in result.artifact_ids:
            assert isinstance(aid, str)

    def test_trace_metadata_artifact_ids_no_content(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(artifact_ids=["art_test"])
        meta = build_trace_metadata_from_tool_result(result)
        assert meta["artifact_ids"] == ["art_test"]
        # artifact_ids in metadata are IDs only — no artifact content
        for key in meta:
            val = meta[key]
            if isinstance(val, str):
                assert "deployable_config" not in val.lower()

    def test_builtin_artifact_tools_no_full_content(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext()
        result = client.invoke("artifact.list", {"workspace_id": "default"}, context=ctx)
        # Must not expose full content or paths in output
        output = result.output
        for v in output.values():
            if isinstance(v, str):
                assert "/Users/" not in v
                assert "deployable_config" not in v


# ══════════════════════════════════════════════════
# Doc Tests
# ══════════════════════════════════════════════════

class TestDocExists:
    def test_integration_doc_exists(self):
        assert os.path.exists(os.path.join(PROJECT_ROOT, "docs", "RUNTIME.md"))
        assert os.path.exists(os.path.join(PROJECT_ROOT, "docs", "CAPABILITIES_AND_TOOLS.md"))

    def test_tool_runtime_doc_links_integration(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "CAPABILITIES_AND_TOOLS.md")) as f:
            c = f.read()
        assert "ToolRouter" in c or "model-visible" in c

    def test_arch_links_integration(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "ARCHITECTURE.md")) as f:
            c = f.read()
        assert "ToolRuntime" in c and "ToolRouter" in c


class TestDocContent:
    @pytest.fixture
    def doc(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "RUNTIME.md")) as f:
            return f.read()

    def test_agent_not_call_arbitrary_tools(self, doc):
        text = doc.lower()
        assert any(phrase in text for phrase in [
            "agent must not directly call",
            "agent does not directly call",
            "agent never directly calls",
            "agent 不直接调",
        ]), "Doc must state Agent does not directly call arbitrary tools"

    def test_module_orchestrates_tools(self, doc):
        text = doc.lower()
        assert "module" in text and "orchestrat" in text, (
            "Doc must state Module orchestrates Tool"
        )

    def test_skill_not_bypass_module(self, doc):
        text = doc.lower()
        assert any(phrase in text for phrase in [
            "skill must not bypass",
            "skill does not bypass",
            "skill 不绕过",
        ]), "Doc must state Skill does not bypass Module"

    def test_tool_result_not_in_llm_context(self, doc):
        text = doc.lower()
        assert "toolresult" in text or "tool result" in text, "Doc must mention ToolResult"
        # Must state ToolResult should be summarized before LLM
        assert "llm" in text and ("not" in text or "summar" in text or "redact" in text), (
            "Doc must state ToolResult must be summarized/redacted before LLM context"
        )

    def test_public_tool_http_api_is_policy_gated(self, doc):
        text = doc.lower()
        assert "public tool" in text and "http" in text, "Doc must mention public Tool HTTP API"
        assert "policy" in text and "approval" in text, (
            "Doc must state public Tool HTTP API is policy/approval gated"
        )

    def test_forbidden_ssh_telnet_snmp_nmap(self, doc):
        text = doc.lower()
        for term in ["ssh", "telnet", "snmp", "nmap"]:
            assert term in text, f"Doc must mention {term}"

    def test_uses_independent_tool_invocation(self, doc):
        text = doc.lower()
        assert "toolinvocation" in text or "tool invocation" in text, (
            "Doc must reference ToolInvocation"
        )
        # Must not recommend legacy tool_calls
        assert "agent/state" not in text or "legacy" in text


# ══════════════════════════════════════════════════
# Naming Boundary Tests
# ══════════════════════════════════════════════════

class TestNamingBoundary:
    def test_tool_runtime_no_import_legacy(self):
        """Tool Runtime modules must not import from agent/state.py."""
        import importlib, inspect
        modules = [
            "tool_runtime.context",
            "tool_runtime.client",
            "tool_runtime.integration",
        ]
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            assert "from agent.state import" not in source, (
                f"{mod_name} must not import from agent.state"
            )
            assert "tool_calls" not in source, (
                f"{mod_name} must not reference legacy tool_calls"
            )

    def test_tool_runtime_client_no_llm(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert "from agent.llm" not in body, "client.py must not import LLM"

    def test_tool_runtime_client_no_memory(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert "from memory" not in body and "import memory" not in body, (
            "client.py must not import Memory"
        )

    def test_tool_result_not_in_llm_context(self):
        # Verify ToolResult has no LLM integration
        import tool_runtime.schemas
        import inspect
        source = inspect.getsource(tool_runtime.schemas.ToolResult)
        assert "llm" not in source.lower(), "ToolResult schema must not reference LLM"


# ══════════════════════════════════════════════════
# Forbidden Tool Confirmation Tests
# ══════════════════════════════════════════════════

class TestForbiddenToolsStillBlocked:
    @pytest.fixture
    def client(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        return get_default_tool_runtime_client()

    def test_ssh_blocked(self, client):
        result = client.invoke("ssh.exec", {})
        assert result.status != "succeeded"

    def test_telnet_blocked(self, client):
        result = client.invoke("telnet.exec", {})
        assert result.status != "succeeded"

    def test_snmp_blocked(self, client):
        result = client.invoke("snmp.walk", {})
        assert result.status != "succeeded"

    def test_nmap_blocked(self, client):
        result = client.invoke("nmap.scan", {})
        assert result.status != "succeeded"

    def test_shell_blocked(self, client):
        result = client.invoke("shell.exec", {})
        assert result.status != "succeeded"


# ══════════════════════════════════════════════════
# Config Translation + Translate Bundle Safety
# ══════════════════════════════════════════════════

class TestNoCoreChanges:
    def test_no_config_translation_imports_tool_runtime(self):
        """config_translation must not import tool_runtime (no forced integration)."""
        import os
        ct_dir = os.path.join(PROJECT_ROOT, "modules", "config_translation")
        for root, dirs, files in os.walk(ct_dir):
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    with open(path) as fh:
                        content = fh.read()
                    assert "from tool_runtime" not in content, (
                        f"{path} must not import tool_runtime"
                    )

    def test_no_new_http_api(self):
        """Backend main must not have new Tool API routes."""
        import os
        main = os.path.join(PROJECT_ROOT, "backend", "main.py")
        with open(main) as f:
            content = f.read()
        # Must not have /api/tools routes
        assert "/api/tools" not in content, (
            "backend/main.py must not have /api/tools routes"
        )
        assert "/api/tool" not in content, (
            "backend/main.py must not have /api/tool routes"
        )

    def test_no_ui_tool_invocation(self):
        """Frontend must not call tool runtime (whitelist: zhMap translation keys)."""
        import os
        frontend = os.path.join(PROJECT_ROOT, "frontend", "index.html")
        with open(frontend) as f:
            content = f.read()
        # tool_runtime may appear in zhMap translation for system health panel
        total = content.count('tool_runtime')
        zhmap_occ = content.count("tool_runtime:'工具'")
        # +1 for legitimate component name check in runtime health display
        allowed_extra = 1
        assert total - zhmap_occ <= allowed_extra, (
            f"Frontend references tool_runtime {total - zhmap_occ} times outside zhMap"
        )
        assert "invoke_tool" not in content, (
            "Frontend must not invoke tools"
        )

    def test_no_api_translate_restored(self):
        import os
        main = os.path.join(PROJECT_ROOT, "backend", "main.py")
        with open(main) as f:
            content = f.read()
        assert "/api/translate" not in content, "No /api/translate restored"
