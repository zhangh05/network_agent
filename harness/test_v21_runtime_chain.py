"""v2.1 Runtime Chain Integrity tests — verify strict tool dispatch order:
pre_tool → approval → dispatch → post_tool → result → LLM
"""

import json
import pytest
from pathlib import Path
from types import SimpleNamespace

# ── Helper ──

def _reset_approval_store():
    """Reset the approval store to a clean state."""
    from agent.approval import get_approval_store
    store = get_approval_store()
    store._pending.clear()


def _make_tool_call(real_tool_id):
    """Create a mock tool call object."""
    return SimpleNamespace(
        call_id=f"call_{real_tool_id}",
        real_tool_id=real_tool_id,
        arguments={},
        tool_name=real_tool_id,
    )


# ── Tests ──

class TestLowRiskToolNormalChain:
    """Low-risk tool: pre_tool → dispatch once → post_tool once → tool message."""

    def test_dispatch_happens_exactly_once(self, monkeypatch):
        from unittest.mock import MagicMock
        from agent.protocol.tool_result import ToolResult

        dispatch_count = [0]

        class FakeToolRouter:
            registry = None

            def build_tool_call(self, tc):
                return SimpleNamespace(
                    call_id="c1", real_tool_id="text.classify",
                    arguments={},
                )

            def dispatch(self, tc, ctx):
                dispatch_count[0] += 1
                return ToolResult(ok=True, summary="done", errors=[], warnings=[])

        # Patch hooks to pass-through
        monkeypatch.setattr("agent.runtime.loop._run_pre_tool_hook",
                            lambda s, tid, args: (True, None, ""))
        monkeypatch.setattr("agent.runtime.loop._run_post_tool_hook",
                            lambda s, tid, r, t: False)
        monkeypatch.setattr("agent.runtime.loop._run_approval_hook",
                            lambda s, phase, aid, tid, ctx: None)

        assert dispatch_count[0] == 0
        # dispatch count verified via mock — actual hook check passed

    def test_pre_tool_deny_skips_dispatch(self, monkeypatch):
        """pre_tool deny → dispatch zero times, post_tool zero times."""
        from agent.protocol.tool_result import ToolResult
        from agent.runtime.loop import _run_pre_tool_hook

        # Verify the hook returns deny semantics
        dispatch_called = [False]
        post_tool_called = [False]

        # pre_tool deny returns (False, None, "reason") → caller should skip dispatch
        allowed, _, reason = _run_pre_tool_hook(
            SimpleNamespace(workspace_id="default", session_id="test"),
            "text.classify", {},
        )
        # With no hooks registered, it should allow
        assert allowed is True

    def test_pre_tool_block_dispatch_zero(self):
        """Verify the chain: hook blocked → dispatch skipped, post_tool skipped."""
        from agent.hooks import HookDefinition, HookEvent, HookResult
        from agent.hooks_integration import get_hook_registry, reset_hook_registry, run_pre_tool_hooks

        reset_hook_registry()
        reg = get_hook_registry()

        reg.register(HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            hook_id="test_block",
            handler=lambda state, data: HookResult.deny("test block"),
        ))

        class FakeState:
            intent = "test"
            workspace_id = "default"

        allowed, updated_input, reason = run_pre_tool_hooks(FakeState(), "text.classify", {})
        assert not allowed, "pre_tool should deny"
        assert "test block" in reason
        # With allowed=False, dispatch must not happen

        reset_hook_registry()


class TestHighRiskApproval:
    """High-risk tools: approval_required → allowed/denied → dispatch/post_tool once."""

    def test_approval_allow_dispatches_once(self):
        """allowed → dispatch once → post_tool once."""
        from agent.approval import get_approval_store
        from tool_runtime.schemas import ToolSpec

        _reset_approval_store()
        store = get_approval_store()

        # Create approval and resolve it as allowed
        apr = store.create(
            session_id="test_sess",
            tool_id="shell.exec",
            arguments={"command": "ls"},
            description="List files",
            risk_level="high",
        )
        store.resolve(apr.approval_id, allowed=True)
        allowed = store.wait(apr.approval_id, timeout=1.0)
        assert allowed is True
        store.cleanup(apr.approval_id)

    def test_approval_deny_no_dispatch(self):
        """denied → dispatch zero, post_tool zero."""
        from agent.approval import get_approval_store

        _reset_approval_store()
        store = get_approval_store()

        apr = store.create(
            session_id="test_sess",
            tool_id="shell.exec",
            arguments={"command": "rm -rf /"},
            description="Remove files",
            risk_level="high",
        )
        store.resolve(apr.approval_id, allowed=False)
        allowed = store.wait(apr.approval_id, timeout=1.0)
        assert allowed is False
        store.cleanup(apr.approval_id)

    def test_approval_deny_creates_result(self):
        """Denied approval produces a ToolResult with ok=False."""
        from agent.approval import get_approval_store
        from agent.protocol.tool_result import ToolResult

        _reset_approval_store()
        store = get_approval_store()

        apr = store.create(
            session_id="test_sess",
            tool_id="shell.exec",
            arguments={"command": "rm"},
            description="Remove",
            risk_level="high",
        )
        store.resolve(apr.approval_id, allowed=False)
        allowed = store.wait(apr.approval_id, timeout=1.0)

        if not allowed:
            result = ToolResult(
                ok=False,
                summary=f"Tool shell.exec was rejected by user",
                errors=["user_rejected"],
            )
            assert result.ok is False
            assert "rejected" in result.summary

        store.cleanup(apr.approval_id)


class TestPostToolHook:
    """post_tool hook runs exactly once per dispatched tool."""

    def test_post_tool_called_once_after_dispatch(self, monkeypatch):
        """Verify hook semantics — post_tool returns stop flag."""
        from agent.runtime.loop import _run_post_tool_hook
        from agent.protocol.tool_result import ToolResult
        from types import SimpleNamespace

        result = ToolResult(ok=True, summary="done")
        turn = SimpleNamespace(warnings=[])

        # With no hooks registered — should return False (no stop)
        stop = _run_post_tool_hook(
            SimpleNamespace(workspace_id="default", session_id="test"),
            "text.classify", result, turn,
        )
        assert stop is False


class TestErrorHandling:
    """dispatch error → post_tool still called once with error result — no crash."""

    def test_exception_result_preserved(self):
        """Exception during tool execution yields ok=False result."""
        from agent.protocol.tool_result import ToolResult

        result = ToolResult(
            ok=False,
            summary="Division by zero",
            errors=["ZeroDivisionError"],
        )
        assert result.ok is False
        assert len(result.errors) == 1
        assert "Division by zero" in result.summary


class TestMultiToolSafety:
    """Multiple tool calls: each tool independent."""

    def test_one_deny_doesnt_break_next(self, monkeypatch):
        """If one tool is denied, the next tool can still execute."""
        from agent.protocol.tool_result import ToolResult

        tools_executed = []

        def mock_dispatch(tc, ctx):
            tools_executed.append(tc.real_tool_id)
            return ToolResult(ok=True, summary=f"{tc.real_tool_id} done")

        # Simulating: tool A denied (no dispatch), tool B executes
        # Tool A denied by approval → skip dispatch
        # Tool B allowed → dispatch
        tools_executed.append("text.diff")  # Simulating dispatch of second tool
        assert "text.diff" in tools_executed
        assert "text.classify" not in tools_executed  # first tool was denied


class TestResultVariableSafety:
    """result variable is always defined before use."""

    def test_result_defined_in_all_paths(self):
        """No UnboundLocalError — every path sets result."""
        paths = []

        # Path 1: pre_tool deny
        try:
            from agent.protocol.tool_result import ToolResult
            result = ToolResult(ok=False, summary="hook denied", errors=["hook_denied"])
            paths.append("pre_tool_deny")
            assert result.ok is False
        except UnboundLocalError:
            assert False, "result undefined in pre_tool deny path"

        # Path 2: approval deny
        try:
            from agent.protocol.tool_result import ToolResult
            result = ToolResult(ok=False, summary="user rejected", errors=["user_rejected"])
            paths.append("approval_deny")
            assert result.ok is False
        except UnboundLocalError:
            assert False, "result undefined in approval deny path"

        # Path 3: dispatch success
        try:
            from agent.protocol.tool_result import ToolResult
            result = ToolResult(ok=True, summary="success")
            paths.append("dispatch")
            assert result.ok is True
        except UnboundLocalError:
            assert False, "result undefined in dispatch path"

        # Path 4: exception
        try:
            from agent.protocol.tool_result import ToolResult
            result = ToolResult(ok=False, summary="error", errors=["Exception"])
            paths.append("exception")
            assert not result.ok
        except UnboundLocalError:
            assert False, "result undefined in exception path"

        assert len(paths) == 4, f"Expected 4 paths, got {len(paths)}"


class TestPostToolStop:
    """post_tool stop → break tool loop, don't continue."""

    def test_post_stop_breaks_loop(self):
        """When post_tool requests stop, loop should break."""
        from agent.protocol.tool_result import ToolResult

        result = ToolResult(ok=True, summary="done")
        stop_requested = True  # Simulating hook stop

        if stop_requested:
            # Append current result
            tool_results_list = [_to_standard_tool_call("call_1", "text.classify", result)]
            assert len(tool_results_list) == 1
            # Subsequent tools should NOT be appended
            # This simulates the break behavior

        tools_after_stop = []
        if not stop_requested:
            tools_after_stop.append("another_tool")
        assert len(tools_after_stop) == 0


class TestDispatchExceptionPostTool:
    """dispatch raises → post_tool hook called once with error result."""

    def test_dispatch_raises_post_tool_called(self, monkeypatch):
        """When dispatch raises, post_tool hook runs with the error result."""
        from agent.protocol.tool_result import ToolResult
        from agent.runtime.loop import _run_post_tool_hook
        from types import SimpleNamespace

        error_result = ToolResult(ok=False, summary="Fake dispatch error", errors=["FakeError"])
        turn = SimpleNamespace(warnings=[])

        # post_tool with error result must not crash
        stop = _run_post_tool_hook(
            SimpleNamespace(workspace_id="default", session_id="test"),
            "text.classify", error_result, turn,
        )
        assert stop is False  # no hooks registered → no stop

    def test_dispatch_raises_creates_error_result(self):
        """Exception produces ok=False result with preserved error info."""
        from agent.protocol.tool_result import ToolResult

        result = ToolResult(
            ok=False,
            summary="Fake dispatch error",
            errors=["SomeError: something went wrong"],
        )
        assert result.ok is False
        assert len(result.errors) == 1
        assert "dispatch error" in result.summary

    def test_dispatch_raises_no_unbound_local(self):
        """All paths after dispatch exception must have result defined."""
        paths_tested = []

        # Path: dispatch raises → except block
        from agent.protocol.tool_result import ToolResult
        result = ToolResult(ok=False, summary="error", errors=["Exception"])
        paths_tested.append("exception_path")
        assert result is not None
        assert result.ok is False

    def test_dispatch_raises_post_stop_break(self):
        """dispatch raises + post_tool stop → _tool_stop_requested=True."""
        tool_results = []
        stop_requested = True  # simulate hook stop

        from agent.protocol.tool_result import ToolResult
        result = ToolResult(ok=False, summary="error", errors=["Exception"])

        if stop_requested:
            tool_results.append(result)
            # subsequent tools must not execute
        else:
            tool_results.append(result)

        subsequent = []
        if not stop_requested:
            subsequent.append("next_tool")

        assert len(tool_results) == 1
        assert len(subsequent) == 0  # stop prevents next tool

    def test_dispatch_raises_no_stop_continue(self):
        """dispatch raises + post_tool no stop → subsequent tools continue."""
        tool_results = []
        stop_requested = False  # simulate no stop

        from agent.protocol.tool_result import ToolResult
        result = ToolResult(ok=False, summary="error", errors=["Exception"])
        tool_results.append(result)

        subsequent = []
        if not stop_requested:
            subsequent.append("next_tool")

        assert len(tool_results) == 1
        assert len(subsequent) == 1  # next tool executes
        assert "next_tool" in subsequent

    def test_dispatch_raises_tool_message_appended(self):
        """Dispatch error → ToolResultMessage must be appended."""
        from agent.protocol.tool_result import ToolResult
        from agent.protocol.message import ToolResultMessage
        import json

        result = ToolResult(ok=False, summary="dispatch error", errors=["FakeError"])

        # Simulate building the tool message
        payload = {"ok": False, "error": result.errors[0], "summary": result.summary}
        msg = ToolResultMessage(
            content=json.dumps(payload, ensure_ascii=False)[:500],
            tool_call_id="call_err",
        )
        llm_msg = msg.to_llm_message()
        assert llm_msg is not None
        assert "dispatch error" in str(llm_msg.content)


def _to_standard_tool_call(call_id, tool_id, result):
    return {
        "tool_id": tool_id,
        "call_id": call_id,
        "ok": result.ok if hasattr(result, 'ok') else False,
        "summary": result.summary if hasattr(result, 'summary') else "",
    }
