# harness/test_tool_runtime_context.py
"""ToolRuntimeContext propagation tests.

Tests:
1. llm_orchestrator calls tool with ToolRuntimeContext containing workspace_id
2. trace_id/run_id/requested_by enter trace metadata or call context
3. Tool count unchanged
4. Does not bypass ToolPolicy
"""

import os
import json
from unittest.mock import patch, MagicMock, call
import pytest

@pytest.fixture
def mock_tool_runtime():
    """Mock ToolRuntimeClient to capture invoke() calls."""
    with patch("tool_runtime.integration.get_default_tool_runtime_client") as mock_get:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "succeeded"
        mock_result.summary = "test summary"
        mock_result.output = {}
        mock_result.errors = []
        mock_result.warnings = []
        mock_result.duration_ms = 100
        mock_client.invoke.return_value = mock_result
        mock_client.list_tools.return_value = [{"tool_id": "test_tool", "risk_level": "low", "category": "runtime"}]
        mock_client.tool_count = 1
        mock_get.return_value = mock_client
        yield mock_client

@pytest.fixture
def state_with_context():
    """Create a NetworkAgentState with full context."""
    from agent.state import NetworkAgentState
    state = NetworkAgentState(
        user_input="test input",
        intent="assistant_chat",
        payload={},
        workspace_id="test_ws",
        request_id="RUN-TEST-001",
        trace_id="TRACE-TEST-001",
    )
    return state

class TestToolInvocationHasWorkspaceID:
    """Test that ToolInvocation created by ToolRuntimeClient has workspace_id."""

    def test_tool_invocation_workspace_id(self, state_with_context):
        """ToolRuntimeClient should create ToolInvocation with workspace_id from context."""
        from tool_runtime.client import ToolRuntimeClient
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.context import ToolRuntimeContext
        from tool_runtime.schemas import ToolResult, ToolSpec

        # Create a real client with mocked executor
        registry = ToolRegistry()
        policy = ToolPolicy()
        client = ToolRuntimeClient(registry, policy)

        # Mock the executor to capture the invocation
        captured_invocation = None

        def mock_execute(invocation):
            nonlocal captured_invocation
            captured_invocation = invocation
            # Return a mock result
            return ToolResult(
                tool_id=invocation.tool_id,
                status="succeeded",
                summary="mock",
            )

        client._executor.execute = mock_execute

        # Register a dummy tool using register_tool
        spec = ToolSpec(
            tool_id="test_tool",
            name="test_tool",
            description="test",
            risk_level="low",
            category="runtime",
        )
        registry.register_tool(spec, lambda **kwargs: {"ok": True})

        # Invoke with context
        ctx = ToolRuntimeContext(
            workspace_id="test_ws",
            run_id="RUN-001",
            trace_id="TRACE-001",
            requested_by="test",
        )
        result = client.invoke("test_tool", {}, context=ctx)

        # Verify ToolInvocation has workspace_id
        assert captured_invocation is not None
        assert captured_invocation.workspace_id == "test_ws"
        assert captured_invocation.run_id == "RUN-001"
        assert captured_invocation.requested_by == "test"

class TestTraceMetadata:
    """Test that trace_id/run_id/requested_by enter trace metadata."""

    def test_trace_metadata_in_result(self, state_with_context):
        """ToolResult should contain trace metadata from context."""
        from tool_runtime.client import ToolRuntimeClient
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.context import ToolRuntimeContext
        from tool_runtime.schemas import ToolResult, ToolSpec

        registry = ToolRegistry()
        policy = ToolPolicy()
        client = ToolRuntimeClient(registry, policy)

        # Mock _append_trace_event to capture trace metadata
        captured_meta = {}

        def mock_append_trace(result, context):
            nonlocal captured_meta
            if context:
                captured_meta = {
                    "workspace_id": context.workspace_id,
                    "run_id": context.run_id,
                    "trace_id": context.trace_id,
                    "requested_by": context.requested_by,
                }

        client._append_trace_event = mock_append_trace

        # Register tool using register_tool
        spec = ToolSpec(
            tool_id="test_tool",
            name="test_tool",
            description="test",
            category="runtime",
            risk_level="low",
        )
        registry.register_tool(spec, lambda **kwargs: {"ok": True})

        # Invoke with context
        ctx = ToolRuntimeContext(
            workspace_id="ws1",
            run_id="RUN-1",
            trace_id="TRACE-1",
            requested_by="orchestrator:test",
        )
        client.invoke("test_tool", {}, context=ctx)

        # Verify trace metadata
        assert captured_meta.get("workspace_id") == "ws1"
        assert captured_meta.get("run_id") == "RUN-1"
        assert captured_meta.get("trace_id") == "TRACE-1"
        assert captured_meta.get("requested_by") == "orchestrator:test"

class TestToolPolicyNotBypassed:
    """ToolPolicy should not be bypassed when using ToolRuntimeContext."""

    def test_policy_still_enforced(self):
        """ToolRuntimeClient should still enforce ToolPolicy."""
        from tool_runtime.client import ToolRuntimeClient
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.context import ToolRuntimeContext
        from tool_runtime.schemas import ToolResult, PolicyDecision, ToolSpec

        # Create policy that denies everything
        class DenyAllPolicy(ToolPolicy):
            def check(self, invocation, tool_spec):
                return PolicyDecision(
                    allowed=False,
                    reason="denied by policy",
                    risk_level="high",
                )

        registry = ToolRegistry()
        policy = DenyAllPolicy()
        client = ToolRuntimeClient(registry, policy)

        # Register tool using register_tool
        spec = ToolSpec(
            tool_id="test_tool",
            name="test_tool",
            description="test",
            category="runtime",
            risk_level="low",
        )
        registry.register_tool(spec, lambda **kwargs: {"ok": True})

        # Invoke with context (should still be denied by policy)
        ctx = ToolRuntimeContext(workspace_id="test")
        result = client.invoke("test_tool", {}, context=ctx)

        # Should be denied (status is "blocked" when policy denies)
        assert result.status == "blocked"
        assert "denied by policy" in result.summary

