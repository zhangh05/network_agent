"""Config Translation Capability v0.7 E2E Tests.

Tests:
1. Skill enabled in SkillRegistry
2. Module enabled in ModuleRegistry
3. Tool visible in ToolRouter
4. translate_config missing source config
5. translate_config does not forge deployable_config
6. translate_config returns structured result
7. Runtime tool_call config_translation
8. Capability question behavior
"""

import os
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


# ── Skill / Module / Tool visibility ──

class TestConfigTranslationVisibility:
    """Config translation must be enabled and visible."""

    def test_config_translation_skill_enabled(self):
        from agent.skills.registry import SkillRegistry
        from agent.capabilities import get_default_capability_registry
        reg = SkillRegistry(get_default_capability_registry())
        skill = reg.get_skill("config_translation")
        assert skill is not None, "config_translation skill not found"
        assert skill.status == "enabled", f"Expected enabled, got {skill.status}"

    def test_config_translation_module_enabled(self):
        from agent.modules.registry import ModuleRegistry
        from agent.capabilities import get_default_capability_registry
        reg = ModuleRegistry(get_default_capability_registry())
        mod = reg.get_module("config_translation")
        assert mod is not None, "config_translation module not found"
        assert mod.status == "enabled", f"Expected enabled, got {mod.status}"
        assert mod.service_path, "service_path must be set"

    def test_config_translation_tool_visible(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        router = svc.tool_service

        # Check in specs
        all_tools = router.registry.list_all()
        config_tools = [t for t in all_tools if "translate_config" in t.tool_id or "config_translation" in t.tool_id]
        assert len(config_tools) >= 1, f"config_translation tool not found in registry: {[t.tool_id for t in all_tools]}"

        # Check visible
        visible_ids = {s.real_tool_id for s in router.model_visible_specs}
        found = any("translate_config" in tid or "config_translation" in tid for tid in visible_ids)
        assert found, f"config_translation tool not visible: {visible_ids}"


# ── Service behavior ──

class TestConfigTranslationService:
    """translate_config service behavior."""

    def test_missing_source_config(self):
        from agent.modules.config_translation.service import translate_config
        result = translate_config(source_config="", target_vendor="huawei")
        assert result["ok"] is False
        assert "missing_source_config" in result["errors"]

    def test_returns_structured_result(self):
        from agent.modules.config_translation.service import translate_config
        cfg = "interface GigabitEthernet0/0\n ip address 10.1.1.1 255.255.255.0\n"
        result = translate_config(
            source_config=cfg,
            source_vendor="cisco",
            target_vendor="huawei",
        )
        required = ["ok", "summary", "source_vendor", "target_vendor",
                     "line_count", "translated_config", "manual_review_items",
                     "warnings", "errors", "artifacts", "metadata"]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_does_not_forge_deployable_config_on_empty(self):
        from agent.modules.config_translation.service import translate_config
        result = translate_config(source_config="", target_vendor="huawei")
        assert result["translated_config"] == "" or not result["ok"]


# ── Runtime tool call ──

class TestRuntimeConfigTranslation:
    """RuntimeLoop → ToolRouter → config_translation flow."""

    def test_tool_call_config_translation_via_registry(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        registry = svc.tool_service.registry

        cfg = "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n"
        result = registry.dispatch("config_translation.translate_config", {
            "source_config": cfg,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "ok" in result
        if result["ok"]:
            assert "summary" in result
            assert "content" in result

    def test_tool_call_missing_source_returns_error(self):
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        result = svc.tool_service.registry.dispatch("config_translation.translate_config", {
            "source_config": "",
            "target_vendor": "huawei",
        })
        assert result["ok"] is False
        assert result.get("errors")


# ── Capability question ──

class TestConfigTranslationCapabilityQuestion:
    """'你能做配置翻译吗？' must answer based on enabled skill."""

    def test_skill_spec_has_config_translation(self):
        from agent.skills.registry import SkillRegistry
        from agent.capabilities import get_default_capability_registry
        reg = SkillRegistry(get_default_capability_registry())
        enabled = [s.skill_id for s in reg.list_enabled_skills()]
        assert "config_translation" in enabled, f"config_translation not enabled: {enabled}"

    def test_module_snapshot_includes_config_translation(self):
        from agent.modules.registry import ModuleRegistry
        from agent.capabilities import get_default_capability_registry
        reg = ModuleRegistry(get_default_capability_registry())
        snap = reg.snapshot()
        enabled_ids = [m["module_id"] for m in snap["enabled"]]
        assert "config_translation" in enabled_ids
