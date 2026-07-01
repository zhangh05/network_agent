"""Tests for LLM streaming scope isolation and direct-answer fast path.

v3.11: verifies that planner tokens do NOT leak to the user token
channel, direct-answer / finalizer tokens DO, and that the narrow
fast-path classifier correctly routes simple queries.
"""

import asyncio
import pytest
from unittest import mock
from types import SimpleNamespace

from speg_engine.fast_path import classify_direct_answer, FastPathDecision
from speg_engine import SPEGConfig, SPEGEngine
from speg_engine.models import StatelessContext, ExecutionNode, ExecutionDAG, ToolResult


# ============================================================================
# Fast-path classifier unit tests
# ============================================================================

class TestFastPathClassifier:
    """classify_direct_answer() standalone tests."""

    def test_greeting_gets_fast_path(self):
        d = classify_direct_answer("你好")
        assert d.enabled is True
        assert d.route == "greeting"

    def test_hellogets_fast_path(self):
        d = classify_direct_answer("hello")
        assert d.enabled is True

    def test_definition_gets_fast_path(self):
        d = classify_direct_answer("解释一下 OSPF 是什么")
        assert d.enabled is True
        assert d.route == "simple_question"

    def test_what_is_fast_path(self):
        d = classify_direct_answer("NAT 是什么")
        assert d.enabled is True

    def test_ospf_neighbor_down_rejects(self):
        d = classify_direct_answer("OSPF 邻居起不来，帮我排查")
        assert d.enabled is False

    def test_read_file_rejects(self):
        d = classify_direct_answer("帮我读取 README.md")
        assert d.enabled is False

    def test_check_health_rejects(self):
        d = classify_direct_answer("检查系统健康状态")
        assert d.enabled is False

    def test_ping_rejects(self):
        d = classify_direct_answer("ping 8.8.8.8")
        assert d.enabled is False

    def test_translate_fast_path(self):
        d = classify_direct_answer("翻译这段英语")
        assert d.enabled is True

    def test_rewrite_fast_path(self):
        d = classify_direct_answer("帮我润色一下这段话")
        assert d.enabled is True

    def test_empty_input(self):
        d = classify_direct_answer("")
        assert d.enabled is False

    def test_unknown_falls_through(self):
        """Anything that doesn't match a whitelist pattern falls through."""
        d = classify_direct_answer("请帮我检查 Kafka 延迟情况")
        assert d.enabled is False


# ============================================================================
# SPEG fast-path integration tests
# ============================================================================

class TestFastPathGenerator:
    """Test the _generate_direct_answer path through SPEGEngine."""

    @pytest.mark.asyncio
    async def test_fast_path_skips_planner(self):
        """'你好' uses fast path — planner never invoked."""
        planner_called = []

        def llm_mock(**kwargs):
            planner_called.append(kwargs.get("system", ""))
            return kwargs.get("user", "hello")

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = await engine.run(user_input="你好", workspace_id="test")
        assert result.success

        meta = result.metadata
        assert meta.get("fast_path") is True
        assert meta.get("planner_skipped") is True
        assert meta.get("used_tools") is False
        assert meta.get("route") == "greeting"
        assert meta.get("direct_answer_latency_ms", 0) > 0

    @pytest.mark.asyncio
    async def test_definition_skips_planner(self):
        """'解释一下 OSPF 是什么' uses fast path — planner never invoked."""
        planner_called = []

        def llm_mock(**kwargs):
            extra = kwargs.get("extra") or {}
            planner_called.append(extra.get("stream_scope", "unknown"))
            return "OSPF（开放式最短路径优先）是一种内部网关协议..."

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = await engine.run(
            user_input="解释一下 OSPF 是什么",
            workspace_id="test",
        )
        assert result.success

        meta = result.metadata
        assert meta.get("fast_path") is True
        assert meta.get("planner_skipped") is True
        assert meta.get("used_tools") is False
        assert meta.get("route") == "simple_question"

    @pytest.mark.asyncio
    async def test_ospf_neighbor_down_full_speg(self):
        """'OSPF 邻居起不来' rejets fast path — planner must run."""
        planner_called = []

        def llm_mock(**kwargs):
            planner_called.append(True)
            return '{"nodes": []}'  # planner returns no tools

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = await engine.run(
            user_input="OSPF 邻居起不来，帮我排查",
            workspace_id="test",
        )
        meta = result.metadata
        assert meta.get("fast_path") is False, "OSPF neighbor down should NOT fast-path"
        assert meta.get("planner_skipped") is False
        assert len(planner_called) >= 1, "planner should have been invoked"

    @pytest.mark.asyncio
    async def test_read_file_full_speg(self):
        """'帮我读取 README.md' rejects fast path."""
        planner_called = []

        def llm_mock(**kwargs):
            planner_called.append(True)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = await engine.run(
            user_input="帮我读取 README.md",
            workspace_id="test",
        )
        meta = result.metadata
        assert meta.get("fast_path") is False
        assert meta.get("planner_skipped") is False


# ============================================================================
# Stream scope tests
# ============================================================================

class TestStreamScope:
    """Verify stream_to_user / stream_scope reaching provider.py."""

    def test_planner_gets_stream_to_user_false(self):
        """_invoke_llm_for_speg with execution-planner system prompt
        must set stream_to_user=False so planner tokens never land
        in the user-facing token channel."""
        from agent.llm.runtime import invoke_llm

        req_meta = {}

        # Replace invoke_llm temporarily so we can capture the
        # LLMRequest metadata without actually calling an LLM API.
        original = invoke_llm

        def _capture(**ikwargs):
            # We cannot reach req.metadata from here because
            # invoke_llm creates the req internally, but we CAN
            # check what extra is being passed.
            extra_captured = ikwargs.get("extra") or {}
            req_meta["stream_to_user"] = extra_captured.get("stream_to_user")
            req_meta["stream_scope"] = extra_captured.get("stream_scope")
            req_meta["planner"] = extra_captured.get("planner")
            return type("FakeResp", (), {
                "content": "ok",
                "error": None,
            })()

        import agent.llm.runtime as runtime_mod
        runtime_mod.invoke_llm = _capture
        try:
            from agent.runtime.speg_adapter import _invoke_llm_for_speg
            # Simulate a planner call
            _invoke_llm_for_speg(
                system="You are an execution planner.",
                user="test",
            )
        finally:
            runtime_mod.invoke_llm = original

        assert req_meta.get("stream_to_user") is False, (
            "planner must have stream_to_user=False"
        )
        assert req_meta.get("stream_scope") == "planner"

    def test_finalizer_gets_stream_to_user_true(self):
        """_invoke_llm_for_speg with non-planner system prompt
        must set stream_to_user=True."""
        from agent.llm.runtime import invoke_llm

        req_meta = {}
        original = invoke_llm

        def _capture(**ikwargs):
            extra_captured = ikwargs.get("extra") or {}
            req_meta["stream_to_user"] = extra_captured.get("stream_to_user")
            req_meta["stream_scope"] = extra_captured.get("stream_scope")
            return type("FakeResp", (), {
                "content": "ok",
                "error": None,
            })()

        import agent.llm.runtime as runtime_mod
        runtime_mod.invoke_llm = _capture
        try:
            from agent.runtime.speg_adapter import _invoke_llm_for_speg
            # Simulate a finalizer call (no "execution planner" in system)
            _invoke_llm_for_speg(
                system="You are a helpful network assistant.",
                user="summarize results",
            )
        finally:
            runtime_mod.invoke_llm = original

        assert req_meta.get("stream_to_user") is True, (
            "finalizer must have stream_to_user=True"
        )
        assert req_meta.get("stream_scope") == "finalizer"

    def test_direct_answer_overrides_scope(self):
        """When caller provides extra, it overrides auto-detected scope."""
        from agent.llm.runtime import invoke_llm

        req_meta = {}
        original = invoke_llm

        def _capture(**ikwargs):
            extra_captured = ikwargs.get("extra") or {}
            req_meta["stream_to_user"] = extra_captured.get("stream_to_user")
            req_meta["stream_scope"] = extra_captured.get("stream_scope")
            return type("FakeResp", (), {
                "content": "ok",
                "error": None,
            })()

        import agent.llm.runtime as runtime_mod
        runtime_mod.invoke_llm = _capture
        try:
            from agent.runtime.speg_adapter import _invoke_llm_for_speg
            _invoke_llm_for_speg(
                system="Direct answer prompt",
                user="what is OSPF",
                extra={
                    "runtime_engine": "speg",
                    "stream_scope": "direct_answer",
                    "stream_to_user": True,
                },
            )
        finally:
            runtime_mod.invoke_llm = original

        assert req_meta.get("stream_to_user") is True
        assert req_meta.get("stream_scope") == "direct_answer"
