# harness/test_capability_manifest_v08.py
"""Tests for Capability Layer v0.8 (CapabilityManifest + CapabilityRegistry).

These tests verify that:
- the default CapabilityRegistry carries exactly the 5 v0.8 capabilities
- enabled vs planned views are correct
- planned capabilities expose no enabled / callable_by_llm tools
- ModuleRegistry / SkillRegistry / ToolRegistry can derive from the registry
- default_runtime_services wires the registry
- RuntimeSnapshot uses the registry when available
- Tool count remains 57
"""

import pytest

from agent.capabilities import (
    CapabilityRegistry,
    get_default_capability_registry,
)
from agent.capabilities.builtin import reset_default_capability_registry_cache
from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


@pytest.fixture(autouse=True)
def _reset_capability_registry_cache():
    """Ensure each test gets a fresh default registry."""
    reset_default_capability_registry_cache()
    yield
    reset_default_capability_registry_cache()


# ── 1. default registry has the five v0.8 capabilities ──
class TestDefaultRegistryContents:
    def test_default_registry_contains_all_seven_capabilities_v09(self):
        # v0.9 added 'artifact' and 'review' (both enabled).
        reg = get_default_capability_registry()
        ids = {m.capability_id for m in reg.list_all()}
        assert ids == {
            "config_translation", "knowledge",
            "artifact", "review",
            "topology", "inspection", "cmdb",
        }


# ── 2. enabled capabilities = config_translation + knowledge ──
class TestEnabledCapabilities:
    def test_enabled_capabilities_are_config_translation_and_knowledge(self):
        # v0.9 added 'artifact' and 'review' (both enabled).
        reg = get_default_capability_registry()
        enabled = sorted([m.capability_id for m in reg.list_enabled()])
        assert enabled == ["artifact", "config_translation", "knowledge", "review"]


# ── 3. planned capabilities = topology / inspection / cmdb ──
class TestPlannedCapabilities:
    def test_planned_capabilities_are_topology_inspection_cmdb(self):
        reg = get_default_capability_registry()
        planned = sorted([m.capability_id for m in reg.list_planned()])
        assert planned == ["cmdb", "inspection", "topology"]


# ── 4. config_translation manifest contract is complete ──
class TestConfigTranslationManifest:
    def test_config_translation_manifest_contract(self):
        reg = get_default_capability_registry()
        m = reg.get("config_translation")
        assert m is not None
        assert m.status == "enabled"
        assert m.module.module_id == "config_translation"
        assert m.module.status == "enabled"
        assert m.module.service_path == "agent.modules.config_translation.service"
        assert "translate_config" in m.module.operations
        assert m.skills and m.skills[0].skill_id == "config_translation"
        assert "config_translation.translate_config" in m.skills[0].related_tools
        assert m.safety.produces_deployable_config is False
        assert m.safety.may_fabricate_sources is False
        assert m.safety.requires_human_review is True
        # outputs
        out_ids = {o.output_id for o in m.outputs}
        assert "translated_config" in out_ids
        assert "manual_review_items" in out_ids


# ── 5. knowledge manifest contract is complete ──
class TestKnowledgeManifest:
    def test_knowledge_manifest_contract(self):
        reg = get_default_capability_registry()
        m = reg.get("knowledge")
        assert m is not None
        assert m.status == "enabled"
        assert m.module.service_path == "agent.modules.knowledge.service"
        assert "query_knowledge" in m.module.operations
        assert m.skills and m.skills[0].skill_id == "knowledge_query"
        assert m.safety.may_fabricate_sources is False
        out_ids = {o.output_id for o in m.outputs}
        assert "source_summary" in out_ids


# ── 6-8. planned capabilities are NOT callable ──
class TestPlannedNotCallable:
    @pytest.mark.parametrize("capability_id", ["topology", "inspection", "cmdb"])
    def test_planned_capability_not_callable(self, capability_id):
        reg = get_default_capability_registry()
        m = reg.get(capability_id)
        assert m is not None
        assert m.status == "planned"
        # No enabled tools allowed
        enabled_tools = [t for t in m.tools if t.status == "enabled"]
        assert enabled_tools == []
        # No tool may be callable_by_llm
        for t in m.tools:
            assert t.callable_by_llm is False
        # Module status mirrors capability status
        assert m.module.status == "planned"
        # Skill status mirrors capability status
        for s in m.skills:
            assert s.status == "planned"


# ── 9. visible_tool_ids excludes planned tools ──
class TestVisibilityRules:
    def test_visible_tool_ids_excludes_planned_tools(self):
        reg = get_default_capability_registry()
        visible = reg.visible_tool_ids()
        # All visible tools must come from enabled capabilities
        for tool_id in visible:
            owner_cap = None
            for cap in reg.list_enabled():
                if any(t.tool_id == tool_id for t in cap.tools):
                    owner_cap = cap
                    break
            assert owner_cap is not None, f"Visible tool {tool_id!r} has no enabled owner"
        # Specifically: no topology/inspection/cmdb tools visible
        for forbidden in (
            "topology.extract", "topology.render",
            "inspection.analyze_outputs", "inspection.generate_report",
            "cmdb.extract_assets", "cmdb.query_assets", "cmdb.upsert_assets",
        ):
            assert forbidden not in visible


# ── 10. visible_tool_ids includes enabled business tools ──
class TestEnabledBusinessToolsVisible:
    def test_visible_tool_ids_includes_config_translation_and_knowledge(self):
        reg = get_default_capability_registry()
        visible = reg.visible_tool_ids()
        assert "config_translation.translate_config" in visible
        assert "knowledge.query" in visible


# ── 11. to_snapshot_dict returns enabled/planned/tools/safety ──
class TestToSnapshotDict:
    def test_to_snapshot_dict_shape(self):
        reg = get_default_capability_registry()
        d = reg.to_snapshot_dict()
        assert "enabled_capabilities" in d
        assert "planned_capabilities" in d
        assert "all_tools" in d
        assert "visible_tools" in d
        assert "safety" in d
        # enabled_capabilities must include config_translation & knowledge
        enabled_ids = {c["capability_id"] for c in d["enabled_capabilities"]}
        assert "config_translation" in enabled_ids
        assert "knowledge" in enabled_ids
        # planned_capabilities must include the 3 planned ones
        planned_ids = {c["capability_id"] for c in d["planned_capabilities"]}
        assert planned_ids == {"topology", "inspection", "cmdb"}
        # Safety summary must reflect the conservative defaults
        assert d["safety"]["real_device_access"] is False
        assert d["safety"]["allows_config_push"] is False
        assert d["safety"]["produces_deployable_config"] is False
        assert d["safety"]["may_fabricate_sources"] is False


# ── 12. ModuleRegistry can be built from capabilities ──
class TestModuleRegistryFromCapabilities:
    def test_module_registry_from_capabilities(self):
        from agent.modules.registry import ModuleRegistry
        reg = get_default_capability_registry()
        mr = ModuleRegistry.from_capabilities(reg)
        # v0.9: 4 enabled + 3 planned modules
        enabled = sorted(m.module_id for m in mr.list_enabled_modules())
        planned = sorted(m.module_id for m in mr.list_planned_modules())
        assert enabled == ["artifact", "config_translation", "knowledge", "review"]
        assert planned == ["cmdb", "inspection", "topology"]


# ── 13. SkillRegistry can be built from capabilities ──
class TestSkillRegistryFromCapabilities:
    def test_skill_registry_from_capabilities(self):
        from agent.skills.registry import SkillRegistry
        reg = get_default_capability_registry()
        sr = SkillRegistry.from_capabilities(reg, base_skill_registry=SkillRegistry())
        enabled = sorted(s.skill_id for s in sr.list_enabled_skills())
        # Must include assistant_chat (base) + 2 capability skills
        assert "assistant_chat" in enabled
        assert "config_translation" in enabled
        assert "knowledge_query" in enabled
        planned = sorted(s.skill_id for s in sr.list_planned_skills())
        assert planned == ["cmdb", "inspection", "topology"]


# ── 14. ToolRegistry registers enabled capability tools ──
class TestToolRegistryCapabilityTools:
    def test_tool_registry_registers_enabled_capability_tools(self):
        # v1.0: 13 capability tools (2 + 4 artifact + 2 review + 5 knowledge).
        from agent.tools.registry import ToolRegistry
        reg = get_default_capability_registry()
        tr = ToolRegistry()
        n = tr.register_capability_tools(reg)
        assert n == 13
        for tid in (
            "config_translation.translate_config",
            "knowledge.query",
            "knowledge.import_document", "knowledge.list_sources",
            "knowledge.read_source", "knowledge.disable_source",
            "knowledge.delete_source",
            "artifact.list", "artifact.read", "artifact.diff", "artifact.export",
            "review.list_items", "review.update_item",
        ):
            assert tr.get(tid) is not None

    # ── 15. ToolRegistry does NOT register planned tools as LLM-visible ──
    def test_tool_registry_does_not_register_planned_as_llm_visible(self):
        from agent.tools.registry import ToolRegistry
        reg = get_default_capability_registry()
        tr = ToolRegistry()
        tr.register_capability_tools(reg)
        for forbidden in (
            "topology.extract", "topology.render",
            "inspection.analyze_outputs", "inspection.generate_report",
            "cmdb.extract_assets", "cmdb.query_assets", "cmdb.upsert_assets",
        ):
            assert tr.get(forbidden) is None, f"Planned tool {forbidden!r} leaked"


# ── 16. default_runtime_services exposes capability_registry ──
class TestRuntimeServicesExposesRegistry:
    def test_default_runtime_services_has_capability_registry(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        assert hasattr(svc, "capability_registry")
        assert svc.capability_registry is not None
        # The exposed registry is the same kind as get_default_capability_registry
        assert isinstance(svc.capability_registry, CapabilityRegistry)
        # And has 7 capabilities (5 v0.8 + artifact + review from v0.9)
        assert len(svc.capability_registry.list_all()) == 7


# ── 17. RuntimeSnapshot uses CapabilityRegistry ──
class TestRuntimeSnapshotUsesRegistry:
    def test_runtime_snapshot_uses_capability_registry(self):
        from agent.context.snapshot import build_runtime_snapshot
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        snap = build_runtime_snapshot(
            tool_count=57,
            visible_tool_count=57,
            workspace_id="demo",
            session_id="sess-1",
            model="test",
            capability_registry=svc.capability_registry,
            base_enabled_skills=["assistant_chat"],
        )
        # Capability baseline is populated
        assert snap.capability_baseline
        assert "config_translation" in [c["capability_id"]
                                         for c in snap.capability_baseline["enabled_capabilities"]]
        # Visible business tools are exactly the 13 enabled ones (v1.0)
        assert sorted(snap.visible_business_tools) == sorted([
            "config_translation.translate_config",
            "knowledge.query",
            "knowledge.import_document", "knowledge.list_sources",
            "knowledge.read_source", "knowledge.disable_source",
            "knowledge.delete_source",
            "artifact.list", "artifact.read", "artifact.diff", "artifact.export",
            "review.list_items", "review.update_item",
        ])
        # Safety baseline is populated
        assert snap.safety_baseline["real_device_access"] is False
        assert snap.safety_baseline["allows_config_push"] is False
        # prompt text reflects the new shape
        text = snap.to_prompt_text()
        assert "Current Capability Baseline:" in text
        assert "Visible business tools:" in text
        assert "planned capabilities are NOT callable." in text


# ── 18. Tool count is now 67 (v1.0: 54 general + 13 capability) ──
class TestToolCount:
    def test_total_tool_count_is_67(self):
        """v1.0 catalog total = 67.

        Was 62 at v0.9 (57 v0.8 + 5 v0.9 dedup). v1.0 adds 5 new
        knowledge tool_ids (import / list / read / disable / delete).
        The capability layer registry is 13 (2 + 4 + 2 + 5); only
        the catalog total is 67.
        """
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        total = len(tr.registry.list_all())
        assert total == 67

    def test_visible_tools_include_capability_tools(self):
        """All 13 capability tools must be in the LLM-visible whitelist."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        for n in (
            "config_translation__translate_config",
            "knowledge__query",
            "knowledge__import_document",
            "knowledge__list_sources",
            "knowledge__read_source",
            "knowledge__disable_source",
            "knowledge__delete_source",
            "artifact__list", "artifact__read",
            "artifact__diff", "artifact__export",
            "review__list_items", "review__update_item",
        ):
            assert n in names

    def test_visible_tools_exclude_disabled_general_tools(self):
        """High-risk tools (e.g. command.approved_exec) are kept in the
        catalog but hidden from LLM (enabled=False). This is unchanged
        from v0.7.1."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        names = {t["function"]["name"] for t in tr.model_visible_tools()}
        # The LLM-safe names for these are command__approved_exec and
        # powershell__approved_script — they must NOT appear.
        assert "command__approved_exec" not in names
        assert "powershell__approved_script" not in names
