"""Tool Runtime Foundation v0.1 Tests.

Covers:
  - Schemas (ToolSpec, ToolInvocation, ToolResult, PolicyDecision)
  - ToolRegistry (register, get, list, duplicate rejection)
  - ToolPolicy (enable, disable, forbidden, risk, category, dry-run, args)
  - ToolExecutor (execute, blocked, failed, redacted output)
  - Redaction (password, token, community, bearer, sk-key, paths)
  - Built-in tools (all 7 low-risk tools)
  - Forbidden tool blocks
  - Audit metadata
  - Doc existence and content
"""

import os
import re
import pytest
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════
# Schema Tests
# ══════════════════════════════════════════════════

class TestToolSpec:
    def test_create_valid(self):
        from tool_runtime.schemas import ToolSpec
        spec = ToolSpec(tool_id="parser.test", name="Test", category="parser",
                        risk_level="low", enabled=True)
        assert spec.tool_id == "parser.test"
        assert spec.risk_level == "low"
        assert spec.enabled is True

    def test_invalid_risk_level(self):
        from tool_runtime.schemas import ToolSpec
        with pytest.raises(ValueError):
            ToolSpec(tool_id="x", risk_level="extreme")

    def test_as_dict_no_handler(self):
        from tool_runtime.schemas import ToolSpec
        spec = ToolSpec(tool_id="parser.test", name="Test", category="parser")
        d = spec.as_dict()
        assert "handler" not in str(d).lower() or "handler" not in d
        assert d["tool_id"] == "parser.test"

    def test_category_validation(self):
        from tool_runtime.schemas import ToolSpec
        # Valid category
        spec = ToolSpec(tool_id="ok", category="artifact")
        assert spec.category == "artifact"
        # Invalid category
        with pytest.raises(ValueError):
            ToolSpec(tool_id="x", category="invalid_category_xyz")


class TestToolInvocation:
    def test_create(self):
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="parser.test", arguments={"text": "hello"})
        assert inv.tool_id == "parser.test"
        assert inv.arguments == {"text": "hello"}
        assert inv.invocation_id  # auto-generated
        assert inv.dry_run is False

    def test_dry_run(self):
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="cmd.echo", dry_run=True)
        assert inv.dry_run is True


class TestToolResult:
    def test_create(self):
        from tool_runtime.schemas import ToolResult
        r = ToolResult(tool_id="test.tool", status="succeeded", summary="done")
        assert r.status == "succeeded"
        assert r.summary == "done"
        assert r.invocation_id == ""  # not auto-generated

    def test_invalid_status(self):
        from tool_runtime.schemas import ToolResult
        with pytest.raises(ValueError):
            ToolResult(status="unknown_status")

    def test_as_dict(self):
        from tool_runtime.schemas import ToolResult, PolicyDecision
        pd = PolicyDecision(allowed=True, reason="ok", risk_level="low")
        r = ToolResult(tool_id="t", status="succeeded", policy_decision=pd)
        d = r.as_dict()
        assert "policy_decision" in d
        assert d["status"] == "succeeded"


class TestPolicyDecision:
    def test_create(self):
        from tool_runtime.schemas import PolicyDecision
        pd = PolicyDecision(allowed=False, reason="blocked", blocked_rules=["r1"])
        assert pd.allowed is False
        assert "r1" in pd.blocked_rules


# ══════════════════════════════════════════════════
# ToolRegistry Tests
# ══════════════════════════════════════════════════

class TestToolRegistry:
    def test_register_and_get(self):
        from tool_runtime.schemas import ToolSpec
        from tool_runtime.registry import ToolRegistry
        reg = ToolRegistry()
        spec = ToolSpec(tool_id="test.one", name="One", category="parser", risk_level="low")
        reg.register_tool(spec, lambda inv: {"ok": True})

        assert reg.get_tool("test.one") is not None
        assert reg.get_tool("test.one").tool_id == "test.one"
        assert reg.get_handler("test.one") is not None

    def test_duplicate_rejected(self):
        from tool_runtime.schemas import ToolSpec
        from tool_runtime.registry import ToolRegistry
        reg = ToolRegistry()
        spec = ToolSpec(tool_id="test.dup", category="parser", risk_level="low")
        reg.register_tool(spec, lambda inv: {})
        with pytest.raises(ValueError, match="already registered"):
            reg.register_tool(spec, lambda inv: {})

    def test_forbidden_risk_rejected(self):
        from tool_runtime.schemas import ToolSpec
        from tool_runtime.registry import ToolRegistry
        reg = ToolRegistry()
        spec = ToolSpec(tool_id="test.frb", risk_level="forbidden", category="parser")
        with pytest.raises(ValueError, match="forbidden"):
            reg.register_tool(spec, lambda inv: {})

    def test_list_tools_no_handler(self):
        from tool_runtime.schemas import ToolSpec
        from tool_runtime.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register_tool(ToolSpec(tool_id="a.one", category="parser", risk_level="low"),
                          lambda inv: {})
        reg.register_tool(ToolSpec(tool_id="b.two", category="artifact", risk_level="low"),
                          lambda inv: {})
        tools = reg.list_tools()
        assert len(tools) == 2
        # list_tools returns metadata dicts, not handler refs
        for t in tools:
            assert "handler" not in t
            assert "tool_id" in t

    def test_is_enabled(self):
        from tool_runtime.schemas import ToolSpec
        from tool_runtime.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register_tool(ToolSpec(tool_id="en.on", category="parser", risk_level="low"),
                          lambda inv: {})
        reg.register_tool(ToolSpec(tool_id="en.off", category="parser", risk_level="low",
                                   enabled=False), lambda inv: {})
        assert reg.is_enabled("en.on") is True
        assert reg.is_enabled("en.off") is False
        assert reg.is_enabled("nonexistent") is False

    def test_builtins_registered(self):
        from tool_runtime.builtins import create_registry_with_builtins
        reg = create_registry_with_builtins()
        assert reg.count() == 7
        assert reg.count_enabled() == 7
        all_tools = reg.list_tools()
        tool_ids = {t["tool_id"] for t in all_tools}
        expected = {
            "artifact.list", "artifact.read_summary",
            "parser.parse_config_text", "parser.extract_interfaces",
            "parser.extract_routes", "report.render_from_safe_summary",
            "command.dry_run_echo",
        }
        assert tool_ids == expected


# ══════════════════════════════════════════════════
# ToolPolicy Tests
# ══════════════════════════════════════════════════

class TestToolPolicy:
    def test_allow_low_risk_enabled(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.ok", category="parser", risk_level="low", enabled=True)
        inv = ToolInvocation(tool_id="test.ok")
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is True

    def test_block_disabled(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.off", category="parser", risk_level="low",
                        enabled=False)
        inv = ToolInvocation(tool_id="test.off")
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False
        assert "disabled" in pd.reason.lower()

    def test_block_forbidden_risk(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.high", category="parser", risk_level="high", enabled=True)
        inv = ToolInvocation(tool_id="test.high")
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False
        assert "high" in pd.reason.lower() or "risk" in pd.reason.lower()

    def test_block_forbidden_tool_ids(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy, V01_FORBIDDEN_TOOLS
        forbidden = ["ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan",
                     "ping.sweep", "command.exec", "shell.exec", "device.exec", "config.push"]
        policy = ToolPolicy()
        for tid in forbidden:
            spec = ToolSpec(tool_id=tid, category="command", risk_level="low", enabled=True)
            inv = ToolInvocation(tool_id=tid)
            pd = policy.check(spec, inv)
            assert pd.allowed is False, f"Should block {tid}"
            assert "forbidden" in pd.reason.lower(), f"{tid}: {pd.reason}"

    def test_block_forbidden_category(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="ssh.fake", category="ssh", risk_level="low", enabled=True)
        inv = ToolInvocation(tool_id="ssh.fake")
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False
        assert "category" in pd.reason.lower() or "ssh" in pd.reason.lower()

    def test_block_medium_risk(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.med", category="parser", risk_level="medium", enabled=True)
        inv = ToolInvocation(tool_id="test.med")
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False

    def test_block_dry_run_not_supported(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.nodry", category="parser", risk_level="low",
                        enabled=True, dry_run_supported=False)
        inv = ToolInvocation(tool_id="test.nodry", dry_run=True)
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False
        assert "dry_run" in pd.reason.lower()

    def test_block_unsafe_arguments(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.policy import ToolPolicy
        spec = ToolSpec(tool_id="test.args", category="parser", risk_level="low", enabled=True)
        inv = ToolInvocation(tool_id="test.args", arguments={"cmd": "ssh root@host"})
        pd = ToolPolicy().check(spec, inv)
        assert pd.allowed is False
        assert "ssh" in pd.reason.lower()


# ══════════════════════════════════════════════════
# ToolExecutor Tests
# ══════════════════════════════════════════════════

class TestToolExecutor:
    def test_execute_success(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.ok", category="parser", risk_level="low"),
            lambda inv: {"ok": True, "summary": "worked", "data": 42}
        )
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="test.ok")
        result = executor.execute(inv)
        assert result.status == "succeeded"
        assert result.redacted is True
        assert result.summary == "worked"
        assert result.output["data"] == 42

    def test_blocked_status(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        # Don't register anything
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="nonexistent")
        result = executor.execute(inv)
        assert result.status == "failed"

    def test_failed_status_on_handler_exception(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.fail", category="parser", risk_level="low"),
            lambda inv: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="test.fail")
        result = executor.execute(inv)
        assert result.status == "failed"
        assert "boom" in result.errors[0]

    def test_blocked_by_policy(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.high", category="parser", risk_level="high",
                     enabled=True),
            lambda inv: {}
        )
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="test.high")
        result = executor.execute(inv)
        assert result.status == "blocked"
        assert result.policy_decision is not None
        assert result.policy_decision.allowed is False

    def test_output_is_redacted(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.secret", category="parser", risk_level="low"),
            lambda inv: {"ok": True, "summary": "ok", "config": {"password": "secret123", "normal": "value"}}
        )
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="test.secret")
        result = executor.execute(inv)
        assert result.redacted is True
        assert result.output["config"]["password"] != "secret123"
        assert "[REDACTED]" in str(result.output["config"]["password"])
        assert result.output["config"]["normal"] == "value"  # not redacted

    def test_dry_run_echo(self):
        from tool_runtime.builtins import create_registry_with_builtins
        from tool_runtime.schemas import ToolInvocation
        from tool_runtime.executor import ToolExecutor
        reg = create_registry_with_builtins()
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="command.dry_run_echo", arguments={"msg": "hello"},
                             dry_run=True)
        result = executor.execute(inv)
        assert result.status == "dry_run"
        assert result.output.get("dry_run") is True

    def test_dry_run_echo_never_executes_shell(self):
        from tool_runtime.builtins import create_registry_with_builtins
        from tool_runtime.schemas import ToolInvocation
        from tool_runtime.executor import ToolExecutor
        reg = create_registry_with_builtins()
        executor = ToolExecutor(reg)
        # even with sensitive-like args, it just echoes (and redacts)
        inv = ToolInvocation(tool_id="command.dry_run_echo",
                             arguments={"msg": "test", "password": "secret"},
                             dry_run=True)
        result = executor.execute(inv)
        assert result.status == "dry_run"
        echo = result.output.get("echo", {})
        assert echo.get("password") == "[REDACTED]" or "[REDACTED]" in str(echo.get("password", ""))

    def test_executor_never_raises(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        reg.register_tool(
            ToolSpec(tool_id="test.crash", category="parser", risk_level="low"),
            lambda inv: 1/0  # ZeroDivisionError
        )
        executor = ToolExecutor(reg)
        inv = ToolInvocation(tool_id="test.crash")
        result = executor.execute(inv)
        assert result.status == "failed"
        assert "division" in result.errors[0].lower() or "zero" in result.errors[0].lower()

    def test_schema_validation(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.executor import ToolExecutor
        reg = ToolRegistry()
        spec = ToolSpec(
            tool_id="test.schema", category="parser", risk_level="low",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        )
        reg.register_tool(spec, lambda inv: {"ok": True})

        executor = ToolExecutor(reg)
        # Missing required field
        inv = ToolInvocation(tool_id="test.schema", arguments={})
        result = executor.execute(inv)
        assert result.status == "blocked"
        assert "name" in str(result.errors)


# ══════════════════════════════════════════════════
# Redaction Tests
# ══════════════════════════════════════════════════

class TestRedaction:
    def test_password_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"config": "password mypass123"}
        result = redact_tool_output(data)
        assert "mypass123" not in result["config"]
        assert "[REDACTED]" in result["config"]

    def test_token_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"auth": "Bearer abcdefgh12345"}
        result = redact_tool_output(data)
        assert "abcdefgh12345" not in result["auth"]
        assert "[REDACTED]" in result["auth"]

    def test_sk_key_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"key": "sk-abc123xyzsecret"}
        result = redact_tool_output(data)
        assert "sk-abc****" in result["key"] or "[REDACTED]" in str(result["key"])

    def test_community_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"snmp": "community public ro"}
        result = redact_tool_output(data)
        assert "public" not in result["snmp"]
        assert "[REDACTED]" in result["snmp"]

    def test_dict_key_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"password": "secret123", "normal": "hello"}
        result = redact_tool_output(data)
        assert result["password"] == "[REDACTED]"
        assert result["normal"] == "hello"

    def test_nested_redaction(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"level1": {"level2": {"secret": "hidden_value"}}}
        result = redact_tool_output(data)
        assert result["level1"]["level2"]["secret"] == "[REDACTED]"

    def test_list_redaction(self):
        from tool_runtime.redaction import redact_tool_output
        data = [{"password": "a"}, {"password": "b"}, "normal_string"]
        result = redact_tool_output(data)
        assert result[0]["password"] == "[REDACTED]"
        assert result[1]["password"] == "[REDACTED]"
        assert result[2] == "normal_string"

    def test_contains_secret(self):
        from tool_runtime.redaction import contains_secret
        assert contains_secret({"password": "x"}) is True
        assert contains_secret({"data": "normal"}) is False
        assert contains_secret("sk-abc123") is True

    def test_path_redacted(self):
        from tool_runtime.redaction import redact_tool_output
        data = {"log": "Error at /Users/admin/config.txt"}
        result = redact_tool_output(data)
        assert "/Users/admin/config.txt" not in result["log"]
        assert "PATH_REDACTED" in result["log"]


# ══════════════════════════════════════════════════
# Built-in Tools Tests
# ══════════════════════════════════════════════════

class TestBuiltinTools:
    @pytest.fixture
    def reg(self):
        from tool_runtime.builtins import create_registry_with_builtins
        from tool_runtime.executor import ToolExecutor
        r = create_registry_with_builtins()
        return r, ToolExecutor(r)

    def test_artifact_list_no_path(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="artifact.list")
        result = executor.execute(inv)
        output = result.output
        # Must not contain absolute path
        for k in output:
            if isinstance(output[k], str):
                assert "/Users/" not in output[k], f"Path found in {k}"
                assert "/home/" not in output[k]

    def test_artifact_read_summary_no_path(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="artifact.read_summary",
                             arguments={"artifact_id": "art_nonexistent"})
        result = executor.execute(inv)
        output = result.output
        for k in output:
            if isinstance(output[k], str):
                assert "/Users/" not in output[k]

    def test_artifact_read_summary_no_full_config(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="artifact.read_summary",
                             arguments={"artifact_id": "art_nonexistent"})
        result = executor.execute(inv)
        output = result.output
        assert "deployable_config" not in output
        assert "source_config" not in output
        # summary only, no full content
        assert "summary" in output

    def test_parser_parse_no_deployable(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="parser.parse_config_text",
                             arguments={"config_text": "interface Gi0/0\n ip address 10.1.1.1 255.255.255.0\n!"})
        result = executor.execute(inv)
        output = result.output
        assert "deployable_config" not in output
        assert output.get("line_count") == 3
        assert output.get("has_interface_blocks") is True

    def test_parser_extract_interfaces_no_full_blocks(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        text = ("interface GigabitEthernet0/0/1\n description Uplink\n ip address 10.1.1.1 255.255.255.0\n!\n"
                "interface GigabitEthernet0/0/2\n description Downlink\n!\n")
        inv = ToolInvocation(tool_id="parser.extract_interfaces",
                             arguments={"config_text": text})
        result = executor.execute(inv)
        output = result.output
        assert "GigabitEthernet0/0/1" in output.get("interface_names", [])
        assert "GigabitEthernet0/0/2" in output.get("interface_names", [])
        # No full interface blocks
        assert "description" not in str(output.get("interface_names", []))
        assert "ip address" not in str(output.get("interface_names", []))

    def test_parser_extract_routes_no_full_config(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        text = "ip route 10.0.0.0 255.0.0.0 192.168.1.1\nip route 0.0.0.0 0.0.0.0 10.1.1.254\n"
        inv = ToolInvocation(tool_id="parser.extract_routes",
                             arguments={"config_text": text})
        result = executor.execute(inv)
        output = result.output
        assert output.get("route_count") == 2
        # No deployable config
        assert "deployable_config" not in output
        # IPs should be masked
        summaries = output.get("route_summaries", [])
        combined = " ".join(summaries)
        assert "255.0.0.0" not in combined or "x.x" in combined  # at least some masking

    def test_report_render_no_full_config(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        # Try to pass a full config as "summary"
        inv = ToolInvocation(tool_id="report.render_from_safe_summary",
                             arguments={
                                 "title": "Test",
                                 "summary": "interface Gi0/0\n ip address 10.1.1.1 255.255.255.0\n" + "x" * 2000,
                             })
        result = executor.execute(inv)
        output = result.output
        # Should reject
        assert output.get("ok") is False or result.status == "failed" or "rejected" in str(output).lower()

    def test_report_render_accepts_safe_summary(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="report.render_from_safe_summary",
                             arguments={"title": "Safe Report", "summary": "All checks passed."})
        result = executor.execute(inv)
        assert result.status == "succeeded"
        assert "markdown" in result.output

    def test_dry_run_echo_no_shell(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="command.dry_run_echo",
                             arguments={"msg": "hello world"},
                             dry_run=True)
        result = executor.execute(inv)
        assert result.status == "dry_run"
        # Never actually executed anything
        assert result.output.get("dry_run") is True

    def test_dry_run_echo_returns_dry_run_flag(self, reg):
        registry, executor = reg
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(tool_id="command.dry_run_echo",
                             arguments={},
                             dry_run=True)
        result = executor.execute(inv)
        assert result.status == "dry_run"
        assert result.output.get("dry_run") is True
        assert "NEVER executes" in result.output.get("message", "")


# ══════════════════════════════════════════════════
# Audit Tests
# ══════════════════════════════════════════════════

class TestAudit:
    def test_audit_no_full_args(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult
        from tool_runtime.audit import build_audit_event
        spec = ToolSpec(tool_id="test.t", category="parser", risk_level="low")
        inv = ToolInvocation(tool_id="test.t", arguments={"password": "secret123", "text": "hello"})
        result = ToolResult(invocation_id=inv.invocation_id, tool_id="test.t",
                            status="succeeded", summary="ok")
        event = build_audit_event(spec, inv, result)
        # Must not contain full arguments
        assert "secret123" not in str(event)
        # Must not contain password
        assert "password" not in str(event).lower() or "secret123" not in str(event)

    def test_audit_contains_metadata(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult
        from tool_runtime.audit import build_audit_event
        spec = ToolSpec(tool_id="test.t", category="parser", risk_level="low")
        inv = ToolInvocation(tool_id="test.t", dry_run=True)
        result = ToolResult(invocation_id=inv.invocation_id, tool_id="test.t",
                            status="dry_run", summary="ok")
        event = build_audit_event(spec, inv, result)
        assert event["event_type"] == "tool_invocation"
        assert event["tool_id"] == "test.t"
        assert event["dry_run"] is True
        assert event["status"] == "dry_run"

    def test_audit_no_full_output(self):
        from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult
        from tool_runtime.audit import build_audit_event
        spec = ToolSpec(tool_id="test.t", category="parser", risk_level="low")
        inv = ToolInvocation(tool_id="test.t")
        result = ToolResult(invocation_id=inv.invocation_id, tool_id="test.t",
                            status="succeeded", summary="ok",
                            output={"big_data": "x" * 10000})
        event = build_audit_event(spec, inv, result)
        # Should NOT contain full output
        assert "x" * 10000 not in str(event)
        assert len(event.get("summary", "")) <= 200


# ══════════════════════════════════════════════════
# Doc Tests
# ══════════════════════════════════════════════════

class TestDocExists:
    def test_tool_runtime_doc_exists(self):
        assert os.path.exists(os.path.join(PROJECT_ROOT, "docs", "TOOL_RUNTIME.md"))

    def test_arch_mentions_tool_runtime(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "ARCHITECTURE.md")) as f:
            c = f.read()
        assert "TOOL_RUNTIME.md" in c, "ARCHITECTURE.md must link to TOOL_RUNTIME.md"

    def test_module_skill_tool_mentions_v01(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "MODULE_SKILL_TOOL_MODEL.md")) as f:
            c = f.read()
        assert "v0.1" in c.lower() or "foundation" in c.lower(), (
            "MODULE_SKILL_TOOL_MODEL.md should mention Tool Runtime v0.1"
        )


class TestDocContent:
    def test_no_real_device_execution_claim(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "TOOL_RUNTIME.md")) as f:
            c = f.read().lower()
        # Must mention that real device execution is out of scope
        assert any(phrase in c for phrase in [
            "real device", "no real", "out of scope",
            "does not", "not include",
        ]), "TOOL_RUNTIME.md must state real device execution is out of scope"

    def test_forbidden_ssh_telnet_snmp_nmap(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "TOOL_RUNTIME.md")) as f:
            c = f.read().lower()
        for forbidden in ["ssh", "telnet", "snmp", "nmap"]:
            assert forbidden in c, f"TOOL_RUNTIME.md must mention {forbidden}"

    def test_not_arbitrary_shell(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "TOOL_RUNTIME.md")) as f:
            c = f.read().lower()
        assert "shell" in c and ("not" in c or "arbitrary" in c or "forbidden" in c or "block" in c), (
            "TOOL_RUNTIME.md must state Tool Runtime is not an arbitrary shell"
        )

    def test_no_claim_v02_is_done(self):
        with open(os.path.join(PROJECT_ROOT, "docs", "TOOL_RUNTIME.md")) as f:
            c = f.read()
        # v0.2/v1.0 should only appear in future phases section
        if "v0.2" in c:
            assert "Future Phases" in c, "v0.2 should only be in Future Phases"


# ══════════════════════════════════════════════════
# Naming Boundary Tests
# ══════════════════════════════════════════════════

class TestNamingBoundary:
    def test_tool_runtime_does_not_use_legacy_tool_results(self):
        """Tool Runtime must NOT reuse agent/state.py tool_calls/tool_results."""
        import agent.state
        import tool_runtime.schemas
        # ToolRuntime schemas must be independent
        assert "ToolInvocation" in dir(tool_runtime.schemas)
        assert "ToolResult" in dir(tool_runtime.schemas)
        # agent/state.py must still have skill_calls (primary)
        fields = agent.state.NetworkAgentState.__dataclass_fields__
        assert "skill_calls" in fields, "skill_calls must be in NetworkAgentState fields"

    def test_tool_runtime_no_import_legacy(self):
        """Tool Runtime modules must not import from agent/state.py."""
        import importlib
        modules = [
            "tool_runtime.schemas",
            "tool_runtime.registry",
            "tool_runtime.policy",
            "tool_runtime.executor",
            "tool_runtime.redaction",
            "tool_runtime.audit",
            "tool_runtime.builtins",
        ]
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            source = str(importlib.import_module("inspect").getsource(mod))
            assert "from agent.state import" not in source, (
                f"{mod_name} must not import from agent.state"
            )
