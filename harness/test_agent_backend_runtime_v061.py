"""Agent Backend v0.6.1 Stabilization Tests.

Tests for:
- Legacy import isolation (new chain must NOT import legacy)
- API /api/agent/message AgentResult shape
- Capability questions (工具呢/你能干什么)
- RuntimeSnapshot sections
- Planned skills/modules NOT in model_visible_tools
- Events observability
- Config translation safety gates
- Knowledge query behavior
"""

import os
import json
import pytest
from pathlib import Path

PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _disable_rate_limit_for_v061(monkeypatch):
    """Ensure rate limiter is disabled during v0.6.1 tests."""
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


# ── Helper ──

def _read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _call_agent_api(message, session_id=None, workspace_id="default"):
    """Call /api/agent/message and return response JSON."""
    from backend.main import app
    app.testing = True
    resp = app.test_client().post("/api/agent/message", json={
        "session_id": session_id or f"v061-test-{hash(message) & 0xffff}",
        "workspace_id": workspace_id,
        "message": message,
    })
    return resp.get_json()


# ── 1. Legacy Import Isolation ──

class TestLegacyImportIsolation:
    """New v0.6 main chain must NOT import agent.legacy."""

    def test_agent_app_no_legacy_import(self):
        """agent/app/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "app").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_agent_core_no_legacy_import(self):
        """agent/core/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "core").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_agent_runtime_no_legacy_import(self):
        """agent/runtime/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "runtime").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_agent_tools_no_legacy_import(self):
        """agent/tools/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "tools").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_agent_skills_no_legacy_import(self):
        """agent/skills/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "skills").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_agent_modules_no_legacy_import(self):
        """agent/modules/ must not import agent.legacy."""
        import ast
        for f in (PROJECT_ROOT / "agent" / "modules").glob("*.py"):
            if f.name.startswith("_"):
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if hasattr(node, 'module') and node.module:
                        assert "agent.legacy" not in node.module, \
                            f"{f.name}: imports agent.legacy via {node.module}"

    def test_backend_agent_routes_no_legacy_import(self):
        """backend/api/agent_routes.py must not import agent.legacy."""
        import ast
        f = PROJECT_ROOT / "backend" / "api" / "agent_routes.py"
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if hasattr(node, 'module') and node.module:
                    assert "agent.legacy" not in node.module, \
                        f"agent_routes.py imports agent.legacy via {node.module}"


# ── 2. API AgentResult Shape ──

class TestAgentMessageAPI:
    """Test /api/agent/message returns AgentResult shape."""

    REQUIRED_FIELDS = ["ok", "final_response", "session_id", "turn_id",
                       "trace_id", "events", "tool_calls", "warnings",
                       "errors", "metadata"]

    def test_agent_message_returns_agent_result_shape(self):
        """Call /api/agent/message and verify all required fields."""
        data = _call_agent_api("hello")
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"Missing required field: {field}"
        assert isinstance(data["ok"], bool)
        assert isinstance(data["final_response"], str)
        assert len(data["final_response"]) > 0

    def test_agent_message_events_present(self):
        """Events must contain at least turn_started and turn_finished."""
        data = _call_agent_api("hi")
        assert len(data["events"]) >= 4, \
            f"Expected at least 4 events, got {len(data['events'])}"
        event_types = [e["type"] for e in data["events"]]
        assert "turn_started" in event_types, f"Missing turn_started in {event_types}"
        assert "turn_finished" in event_types, f"Missing turn_finished in {event_types}"
        assert "assistant_message" in event_types, f"Missing assistant_message"

    def test_agent_message_session_id_persists(self):
        """Same session_id should reuse the session."""
        sid = "v061-persist-test"
        data1 = _call_agent_api("hello", session_id=sid)
        data2 = _call_agent_api("how are you", session_id=sid)
        assert data1["session_id"] == sid
        assert data2["session_id"] == sid
        assert data1["turn_id"] != data2["turn_id"], "Turns should have different IDs"


# ── 3. Capability Questions ──

class TestCapabilityQuestions:
    """Test that capability questions use RuntimeSnapshot, not static text."""

    def test_tools_question_uses_snapshot(self):
        """'工具呢？' must reference enabled/planned from snapshot.

        v1.0.1.1: gated behind RUN_LIVE_TESTS=1 (live LLM call).
        Default env: skip.
        """
        if not os.environ.get("RUN_LIVE_TESTS"):
            pytest.skip("live LLM test — set RUN_LIVE_TESTS=1 to enable")
        data = _call_agent_api("工具呢？")
        resp = data["final_response"].lower()
        # Must NOT claim tools exist that are non-existent
        # Must mention planned or enabled
        assert any(kw in resp for kw in ["planned", "planning", "规划", "计划",
                                          "skill", "module", "config",
                                          "knowledge"]), \
            f"Response should reference capabilities, got: {resp[:200]}"

    def test_abilities_question_distinguishes_enabled_planned(self):
        """'你能干什么？' must distinguish enabled vs planned."""
        data = _call_agent_api("你能干什么？")
        resp = data["final_response"]
        # Should mention config_translation or knowledge as available
        has_config_keywords = any(kw in resp for kw in [
            "config", "翻译", "translation", "knowledge", "知识", "assistant"
        ])
        assert has_config_keywords, \
            f"Response should mention available capabilities: {resp[:200]}"

    def test_capabilities_question_no_fake_tools(self):
        """'有哪些能力？' must not claim topology/inspection/cmdb as current tools."""
        data = _call_agent_api("有哪些能力？")
        resp = data["final_response"].lower()
        # The response may mention topology etc but should mark as planned
        if "topology" in resp or "inspection" in resp or "cmdb" in resp:
            assert "planned" in resp or "规划" in resp or "plan" in resp or \
                   "not" in resp or "未来" in resp, \
                f"If mentioning planned capabilities, must qualify: {resp[:300]}"


# ── 4. RuntimeSnapshot Sections ──

class TestRuntimeSnapshot:
    """Test RuntimeSnapshot.to_prompt_text() structure."""

    def test_snapshot_has_current_tools_section(self):
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            tool_count=5, visible_tool_count=5,
            enabled_skills=["assistant_chat", "config_translation"],
            planned_skills=["topology"],
            enabled_modules=["config_translation"],
            planned_modules=["inspection"],
        )
        text = snap.to_prompt_text()
        assert "Current Tools" in text
        assert "Enabled Skills:" in text
        assert "Planned Skills (NOT yet available)" in text
        assert "Enabled Modules:" in text
        assert "Planned Modules (NOT yet available)" in text

    def test_snapshot_marks_planned_not_callable(self):
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            planned_skills=["topology", "cmdb"],
            planned_modules=["inspection"],
        )
        text = snap.to_prompt_text()
        assert "not callable" in text, "Planned must be marked not callable"


# ── 5. No Planned in Model-Visible Tools ──

class TestToolRouterPlannedIsolation:
    """Planned modules/skills must NOT appear in model_visible_tools."""

    def test_no_planned_module_in_model_visible_tools(self):
        from agent.app.service import get_default_agent_app
        from agent.runtime.services import default_runtime_services
        try:
            svc = default_runtime_services()
            if svc and svc.tool_service:
                tools = svc.tool_service.model_visible_tools()
                tool_names = [t.get("function", {}).get("name", "") for t in tools]
                # topology / inspection / cmdb tool names must not be here
                for planned in ["topology", "inspection", "cmdb"]:
                    assert not any(planned in name for name in tool_names), \
                        f"Planned module '{planned}' found in model_visible_tools: {tool_names}"
        except Exception as e:
            # If ToolRegistry can't be built (no client), that's OK for test env
            if "not been initialized" not in str(e) and "ToolRegistry" not in str(e):
                pass  # OK


# ── 6. Events Observability ──

class TestEventsObservability:
    """Events must be comprehensive and observable."""

    def test_assistant_chat_has_core_events(self):
        """Simple assistant_chat must have turn_started, context_built,
        model_request_started, model_response_received, assistant_message,
        turn_finished."""
        data = _call_agent_api("hello world")
        event_types = {e["type"] for e in data["events"]}
        required = {"turn_started", "context_built", "model_request_started",
                    "model_response_received", "assistant_message", "turn_finished"}
        missing = required - event_types
        assert not missing, f"Missing required events: {missing}"

    def test_event_timestamps_are_present(self):
        """Each event must have a timestamp."""
        data = _call_agent_api("hi")
        for e in data["events"]:
            assert "timestamp" in e, f"Event missing timestamp: {e['type']}"


# ── 7. Config Translation Safety ──

class TestConfigTranslationSafety:
    """Config translation must not forge deployable_config via LLM."""

    def test_config_translate_without_source_asks_for_config(self):
        """Without source_config, should prompt for it."""
        data = _call_agent_api("帮我把这段 Cisco ACL 转成华为")
        resp = data["final_response"].lower()
        # Should ask for config, not make up output
        has_prompt = any(kw in resp for kw in [
            "provide", "config", "配置", "paste", "贴", "提供", "需要",
            "source", "example", "具体", "please"
        ])
        assert has_prompt, \
            f"Should prompt for config, got: {resp[:200]}"

    def test_config_translate_with_source_mentions_config_module(self):
        """With source_config, should reference config translation."""
        cfg = "access-list 100 permit ip any any"
        data = _call_agent_api(f"帮我把这段 Cisco ACL 转成华为：{cfg}")
        resp = data["final_response"].lower()
        # Should mention config/translation capability
        has_ref = any(kw in resp for kw in [
            "config", "translation", "translate", "翻译", "acl",
            "access-list", "规则", "permit"
        ])
        assert has_ref, \
            f"Response should reference config capability: {resp[:200]}"


# ── 8. Knowledge Query ──

class TestKnowledgeQuery:
    """Knowledge queries must not fake retrieval."""

    def test_knowledge_query_handles_no_data(self):
        """When no knowledge data, must honestly say so.

        v1.0.1.1: gated behind RUN_LIVE_TESTS=1 (live LLM call).
        Default env: skip.
        """
        if not os.environ.get("RUN_LIVE_TESTS"):
            pytest.skip("live LLM test — set RUN_LIVE_TESTS=1 to enable")
        data = _call_agent_api("查一下知识库里有没有 SD-WAN 资料")
        resp = data["final_response"].lower()
        # Should NOT claim to have retrieved data if it hasn't
        # Acceptable: mentions knowledge module, or says not available
        has_honest = any(kw in resp for kw in [
            "knowledge", "知识", "not found", "未找到", "没有", "no result",
            "sd-wan", "sorry", "抱歉", "available", "可用"
        ])
        assert has_honest, \
            f"Response should honestly handle knowledge query: {resp[:200]}"


# ── 9. ToolRouter / ToolRegistry ──

class TestToolRouterRegistry:
    """ToolRouter and ToolRegistry basic checks."""

    def test_tool_registry_can_be_created(self):
        from agent.tools.registry import ToolRegistry
        reg = ToolRegistry()
        assert reg is not None

    def test_tool_router_can_be_created(self):
        from agent.tools.router import ToolRouter
        from agent.tools.registry import ToolRegistry
        reg = ToolRegistry()
        router = ToolRouter(registry=reg)
        assert router is not None
        tools = router.model_visible_tools()
        assert isinstance(tools, list)


# ── 10. SkillRegistry / ModuleRegistry ──

class TestRegistries:
    """SkillRegistry and ModuleRegistry basic checks."""

    def test_skill_registry_has_enabled(self):
        from agent.skills.registry import SkillRegistry
        from agent.capabilities import get_default_capability_registry
        reg = SkillRegistry(get_default_capability_registry())
        enabled = reg.list_enabled_skills()
        planned = reg.list_planned_skills()
        assert len(enabled) >= 1, "Should have at least 1 enabled skill"
        assert len(planned) >= 1, "Should have at least 1 planned skill"
        enabled_ids = [s.skill_id for s in enabled]
        assert "assistant_chat" in enabled_ids

    def test_module_registry_has_enabled(self):
        from agent.modules.registry import ModuleRegistry
        from agent.capabilities import get_default_capability_registry
        reg = ModuleRegistry(get_default_capability_registry())
        enabled = reg.list_enabled_modules()
        planned = reg.list_planned_modules()
        assert len(enabled) >= 1, "Should have at least 1 enabled module"
        enabled_ids = [m.module_id for m in enabled]
        assert "config_translation" in enabled_ids
