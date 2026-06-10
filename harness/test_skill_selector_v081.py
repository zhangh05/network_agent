# harness/test_skill_selector_v081.py
"""Tests for SkillSelector + Dynamic Tool Visibility v0.8.1.

Coverage:
  1. config translation input → config_translation selected
  2. knowledge input → knowledge_query selected
  3. capability discovery → assistant_chat + capability_discovery
  4. no match → assistant_chat only
  5. planned skill is NOT injected as enabled
  6. config_translation scenario exposes only config_translation.translate_config
  7. knowledge scenario exposes only knowledge.query
  8. topology-style request does NOT expose topology tools
  9. forbidden / planned tools never appear in dynamic whitelist
  10. selector error → fallback to v0.8 behavior (no crash)
  11. RuntimeSnapshot records selected_skills / selected_visible_tools /
      dynamic_tool_visibility
  12. default_runtime_services exposes skill_selector
  13. per-turn state is independent: switching user message re-filters
"""

import pytest

from agent.capabilities import get_default_capability_registry
from agent.capabilities.builtin import reset_default_capability_registry_cache
from agent.skills.selector import SkillSelector, select_skills


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_default_capability_registry_cache()
    yield
    reset_default_capability_registry_cache()


@pytest.fixture
def reg():
    return get_default_capability_registry()


@pytest.fixture
def sel(reg):
    return SkillSelector(reg)


# ── 1. config translation input ──
class TestConfigTranslationSelection:
    def test_chinese_acl_translation_input_selects_config_translation(self, sel):
        skills = sel.select("请把 Cisco ACL 翻译成华为", capability_registry=sel.capability_registry)
        assert "assistant_chat" in skills
        assert "config_translation" in skills
        assert "knowledge_query" not in skills

    def test_english_translation_input_selects_config_translation(self, sel):
        skills = sel.select("Please translate this Cisco config to Huawei", capability_registry=sel.capability_registry)
        assert "config_translation" in skills


# ── 2. knowledge input ──
class TestKnowledgeSelection:
    def test_chinese_knowledge_query_selects_knowledge_query(self, sel):
        skills = sel.select("查一下知识库关于 OSPF 的内容", capability_registry=sel.capability_registry)
        assert "knowledge_query" in skills
        assert "config_translation" not in skills

    def test_english_lookup_selects_knowledge_query(self, sel):
        skills = sel.select("Please lookup the RFC for BGP", capability_registry=sel.capability_registry)
        assert "knowledge_query" in skills


# ── 3. capability discovery ──
class TestCapabilityDiscovery:
    def test_chinese_discovery_question(self, sel):
        skills = sel.select("你能做什么？", capability_registry=sel.capability_registry)
        assert "capability_discovery" in skills
        assert "assistant_chat" in skills
        # No business skills for a "what can you do" question
        assert "config_translation" not in skills
        assert "knowledge_query" not in skills

    def test_english_discovery_question(self, sel):
        skills = sel.select("What can you do?", capability_registry=sel.capability_registry)
        assert "capability_discovery" in skills

    def test_help_keyword_triggers_discovery(self, sel):
        skills = sel.select("help", capability_registry=sel.capability_registry)
        assert "capability_discovery" in skills


# ── 4. no match → assistant_chat only ──
class TestNoMatch:
    def test_unrelated_message_only_assistant_chat(self, sel):
        skills = sel.select("今天天气如何？", capability_registry=sel.capability_registry)
        assert skills == ["assistant_chat"]

    def test_empty_message_only_assistant_chat(self, sel):
        skills = sel.select("", capability_registry=sel.capability_registry)
        assert skills == ["assistant_chat"]


# ── 5. planned skill MUST NOT be injected as enabled ──
class TestPlannedNotInjected:
    @pytest.mark.parametrize("msg", [
        "请帮我画一下网络拓扑",
        "请做一次设备巡检",
        "查资产列表",
        "render the topology",
        "do a health check",
    ])
    def test_planned_keywords_do_not_select_planned_skill(self, sel, msg):
        skills = sel.select(msg, capability_registry=sel.capability_registry)
        # The planned skills are topology / inspection / cmdb
        assert "topology" not in skills
        assert "inspection" not in skills
        assert "cmdb" not in skills
        # and no business tool is exposed
        for s in skills:
            assert s in ("assistant_chat", "capability_discovery")


# ── 6. config translation scenario visible tools ──
class TestConfigTranslationVisibility:
    def test_only_config_translation_tool_visible(self):
        from agent.runtime.services import default_runtime_services
        tr = default_runtime_services().tool_service
        # Mirror the ContextBuilder flow: apply_dynamic_visibility with
        # the candidates from the selected skills.
        tr.apply_dynamic_visibility({"config_translation.translate_config"})
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        assert "config_translation__translate_config" in names
        assert "knowledge__query" not in names
        # All general tools are also hidden
        assert tr.dynamic_visibility is True
        # Reset for the next test
        tr.apply_dynamic_visibility([])


# ── 7. knowledge scenario visible tools ──
class TestKnowledgeVisibility:
    def test_only_knowledge_tool_visible(self):
        from agent.runtime.services import default_runtime_services
        tr = default_runtime_services().tool_service
        tr.apply_dynamic_visibility({"knowledge.query"})
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        assert "knowledge__query" in names
        assert "config_translation__translate_config" not in names
        # Reset
        tr.apply_dynamic_visibility([])


# ── 8. topology-style request does NOT expose topology tools ──
class TestTopologyBlocked:
    def test_topology_tool_id_not_visible_even_if_caller_passes_it(self):
        from agent.runtime.services import default_runtime_services
        tr = default_runtime_services().tool_service
        # Caller attempts to inject topology tool (would happen if the
        # selector mistakenly selected a planned skill). The safety
        # filter in ToolRegistry MUST reject it.
        tr.apply_dynamic_visibility({
            "topology.extract", "topology.render",
            "inspection.analyze_outputs", "cmdb.query_assets",
        })
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        assert "topology__extract" not in names
        assert "topology__render" not in names
        assert "inspection__analyze_outputs" not in names
        assert "cmdb__query_assets" not in names
        # Reset
        tr.apply_dynamic_visibility([])


# ── 9. forbidden tools never visible ──
class TestForbiddenToolsNeverVisible:
    def test_config_push_not_visible_even_if_caller_passes_it(self):
        from agent.runtime.services import default_runtime_services
        tr = default_runtime_services().tool_service
        tr.apply_dynamic_visibility({"config.push", "ssh.exec", "telnet.exec", "nmap.scan"})
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        for forbidden in ("config__push", "ssh__exec", "telnet__exec", "nmap__scan"):
            assert forbidden not in names
        # Reset
        tr.apply_dynamic_visibility([])


# ── 10. selector error → fallback to v0.8 (no crash) ──
class TestSelectorErrorFallback:
    def test_broken_capability_registry_falls_back_to_base(self):
        class _Boom:
            def list_enabled(self):
                raise RuntimeError("intentional boom")
        sel = SkillSelector(capability_registry=_Boom())
        skills = sel.select("translate cisco to huawei", capability_registry=_Boom())
        # Fallback returns base only
        assert skills == ["assistant_chat"]
        # No exception propagated

    def test_select_skills_function_never_raises(self):
        # Functional API with broken registry
        class _Boom:
            def list_enabled(self):
                raise RuntimeError("intentional boom")
        out = select_skills("translate", _Boom())
        assert out == ["assistant_chat"]


# ── 11. RuntimeSnapshot records per-turn fields ──
class TestRuntimeSnapshotPerTurnFields:
    def test_snapshot_records_selected_skills_and_visible_tools(self, reg):
        from agent.context.snapshot import build_runtime_snapshot
        snap = build_runtime_snapshot(
            tool_count=57,
            visible_tool_count=1,
            workspace_id="demo",
            session_id="s1",
            model="test",
            capability_registry=reg,
            base_enabled_skills=["assistant_chat"],
            selected_skills=["assistant_chat", "config_translation"],
            selected_visible_tools=["config_translation.translate_config"],
            dynamic_tool_visibility=True,
        )
        assert snap.selected_skills == ["assistant_chat", "config_translation"]
        assert snap.selected_visible_tools == ["config_translation.translate_config"]
        assert snap.dynamic_tool_visibility is True
        d = snap.to_dict()
        assert d["selected_skills"] == ["assistant_chat", "config_translation"]
        assert d["dynamic_tool_visibility"] is True
        # And to_prompt_text() shows the per-turn section
        text = snap.to_prompt_text()
        assert "Selected skills for this turn:" in text
        assert "Visible tools for this turn" in text
        assert "Planned capabilities are NOT callable." in text


# ── 12. default_runtime_services exposes skill_selector ──
class TestRuntimeServicesExposesSelector:
    def test_default_runtime_services_has_skill_selector(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        assert hasattr(svc, "skill_selector")
        assert svc.skill_selector is not None
        from agent.skills.selector import SkillSelector
        assert isinstance(svc.skill_selector, SkillSelector)


# ── 13. per-turn state is independent (re-applying visibility works) ──
class TestPerTurnReApplication:
    def test_applying_different_visibility_in_sequence(self):
        from agent.runtime.services import default_runtime_services
        tr = default_runtime_services().tool_service

        # Turn 1: config translation
        tr.apply_dynamic_visibility({"config_translation.translate_config"})
        assert tr.dynamic_visibility is True
        v1 = {t["function"]["name"] for t in tr.model_visible_tools()}
        assert v1 == {"config_translation__translate_config"}

        # Turn 2: knowledge
        tr.apply_dynamic_visibility({"knowledge.query"})
        assert tr.dynamic_visibility is True
        v2 = {t["function"]["name"] for t in tr.model_visible_tools()}
        assert v2 == {"knowledge__query"}

        # Turn 3: empty (chat) — fall back to v0.8 (full set)
        tr.apply_dynamic_visibility([])
        assert tr.dynamic_visibility is False
        assert tr.allowed_tool_ids is None
        v3 = {t["function"]["name"] for t in tr.model_visible_tools()}
        # v0.8 fallback: 55 visible (53 enabled general + 2 capability)
        assert len(v3) == 55
