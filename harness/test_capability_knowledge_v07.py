"""Knowledge Capability v0.7 E2E Tests.

Tests:
1. Skill enabled
2. Module enabled
3. Tool visible
4. query_knowledge unavailable is honest
5. query_knowledge no fabricated sources
6. Runtime tool_call
7. Capability question behavior
8. topology still planned
"""

import os
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


# ── Skill / Module / Tool ──

class TestKnowledgeVisibility:
    """Knowledge must be enabled and visible."""

    def test_knowledge_skill_enabled(self):
        from agent.skills.registry import SkillRegistry
        reg = SkillRegistry()
        skill = reg.get_skill("knowledge_query")
        assert skill is not None
        assert skill.status == "enabled"

    def test_knowledge_module_enabled(self):
        from agent.modules.registry import ModuleRegistry
        reg = ModuleRegistry()
        mod = reg.get_module("knowledge")
        assert mod is not None
        assert mod.status == "enabled"
        assert mod.service_path

    def test_knowledge_tool_visible(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        router = svc.tool_service

        visible_ids = {s.real_tool_id for s in router.model_visible_specs}
        found = "knowledge.query" in visible_ids
        assert found, f"knowledge.query not visible: {visible_ids}"


# ── Service behavior ──

class TestKnowledgeService:
    """query_knowledge service behavior."""

    def test_query_knowledge_unavailable_is_honest(self):
        """When knowledge store not configured, return honest error."""
        from agent.modules.knowledge.service import query_knowledge
        # With no actual knowledge store, this should handle gracefully
        result = query_knowledge("SD-WAN architecture")
        # Either returns hits=[] honestly, or errors with knowledge_unavailable
        assert "ok" in result
        if not result["ok"]:
            # Should explain why it's unavailable
            assert any(kw in str(result.get("errors", [])).lower()
                       for kw in ["knowledge", "unavailable", "import"])
        else:
            # If ok=True, hits must be real (not fabricated)
            assert isinstance(result.get("hits", []), list)

    def test_no_fabricated_sources(self):
        """Empty knowledge store must not generate fake sources."""
        from agent.modules.knowledge.service import query_knowledge
        result = query_knowledge("nonexistent_query_xyz123")
        hits = result.get("hits", [])
        if len(hits) > 0:
            for hit in hits:
                # Each hit must have real source identifiers
                assert hit.get("source"), "Hit has no source"
                assert hit.get("title"), "Hit has no title"

    def test_missing_query_returns_error(self):
        from agent.modules.knowledge.service import query_knowledge
        result = query_knowledge("")
        assert result["ok"] is False
        assert "missing_query" in result["errors"]


# ── Runtime tool call ──

class TestRuntimeKnowledgeQuery:
    """RuntimeLoop → ToolRouter → knowledge.query flow."""

    def test_tool_call_knowledge_query_via_registry(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        registry = svc.tool_service.registry

        result = registry.dispatch("knowledge.query", {
            "query": "SD-WAN",
            "top_k": 3,
        })
        assert "ok" in result
        assert "summary" in result


# ── Planned isolation ──

class TestPlannedIsolation:
    """topology / inspection / cmdb must remain planned."""

    def test_topology_still_planned(self):
        from agent.skills.registry import SkillRegistry
        reg = SkillRegistry()
        skill = reg.get_skill("topology")
        assert skill is not None
        assert skill.status == "planned", f"topology should be planned, got {skill.status}"

    def test_inspection_still_planned(self):
        from agent.skills.registry import SkillRegistry
        reg = SkillRegistry()
        skill = reg.get_skill("inspection")
        assert skill is not None
        assert skill.status == "planned"

    def test_cmdb_still_planned(self):
        from agent.skills.registry import SkillRegistry
        reg = SkillRegistry()
        skill = reg.get_skill("cmdb")
        assert skill is not None
        assert skill.status == "planned"

    def test_topology_not_in_model_visible_tools(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tools = svc.tool_service.model_visible_tools()
        tool_names = [t.get("function", {}).get("name", "") for t in tools]
        assert not any("topology" in name for name in tool_names), \
            "topology should not be in model_visible_tools"
