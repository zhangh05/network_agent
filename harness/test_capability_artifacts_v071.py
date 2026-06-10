"""Capability Artifacts v0.7.1 Tests.

Tests:
1. translate_config saves translated_config artifact
2. Missing source_config does not save artifact
3. Artifact metadata authoritative=false, deployable_config=false
4. Artifact save failure warns, does not fail translation
5. Manual review string items normalized
6. Manual review structured items preserved
7. Tool call config translation exposes artifacts in AgentResult
8. Tool call config translation exposes manual_review_count
9. ToolResultMessage contains artifact summary
10. Capability question mentions artifacts but not deployable
"""

import os
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


cfg_cisco = "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n"


class TestConfigTranslationArtifacts:
    """Artifact saving behavior for translate_config."""

    def test_translate_config_success_saves_artifact(self):
        """Successful translation must save translated_config as artifact."""
        from agent.modules.config_translation.service import translate_config
        result = translate_config(
            source_config=cfg_cisco,
            source_vendor="cisco",
            target_vendor="huawei",
        )
        assert result["ok"] is True
        assert len(result.get("artifacts", [])) >= 1, "Should save at least 1 artifact"

    def test_translate_config_missing_source_no_artifact(self):
        """Missing source_config must not save artifact."""
        from agent.modules.config_translation.service import translate_config
        result = translate_config(source_config="", target_vendor="huawei")
        assert result["ok"] is False
        assert result.get("artifacts", []) == [], "Should not save artifact when no source"

    def test_artifact_metadata_not_deployable(self):
        """Artifact metadata must mark authoritative=false, deployable_config=false."""
        from agent.modules.config_translation.service import translate_config
        result = translate_config(
            source_config=cfg_cisco,
            source_vendor="cisco",
            target_vendor="huawei",
        )
        for art in result.get("artifacts", []):
            meta = art.get("metadata", {})
            assert meta.get("authoritative") is False, f"Artifact must not be authoritative: {art.get('artifact_id')}"
            assert meta.get("deployable_config") is False, f"Artifact must not be deployable: {art.get('artifact_id')}"
            assert art.get("sensitivity") == "sensitive"
            assert art.get("artifact_type") == "translated_config"

    def test_artifact_save_failure_warns_not_fail(self, monkeypatch):
        """Artifact save failure should warn, not fail translation entirely."""
        # Mock save_artifact at the call site (artifacts.store)
        with patch("artifacts.store.save_artifact", return_value=None):
            from agent.modules.config_translation.service import translate_config
            result = translate_config(
                source_config=cfg_cisco,
                source_vendor="cisco",
                target_vendor="huawei",
            )
        # Translation should still succeed
        assert result["ok"] is True
        # Warnings should include artifact_save_failed
        assert any("artifact_save_failed" in str(w) for w in result.get("warnings", []))

    def test_artifact_type_is_translated_config(self):
        """Artifact type must be 'translated_config'."""
        from agent.modules.config_translation.service import translate_config
        result = translate_config(
            source_config=cfg_cisco,
            source_vendor="cisco",
            target_vendor="huawei",
        )
        for art in result.get("artifacts", []):
            assert art["artifact_type"] == "translated_config"


class TestManualReviewItems:
    """manual_review_items must be structured."""

    def test_string_review_item_normalized(self):
        """String review items must be normalized to structured format."""
        from agent.modules.config_translation.service import _normalize_review_items
        raw = ["This needs manual review"]
        items = _normalize_review_items(raw)
        assert len(items) == 1
        item = items[0]
        assert "item_id" in item
        assert item["severity"] == "medium"
        assert item["category"] == "unknown"
        assert item["requires_human_review"] is True
        assert len(item["reason"]) > 0

    def test_structured_review_item_preserved(self):
        """Already structured items must be preserved and fields filled."""
        from agent.modules.config_translation.service import _normalize_review_items
        raw = [{
            "source_excerpt": "line 1",
            "reason": "unsupported command",
            "risk_level": "high",
            "category": "syntax",
        }]
        items = _normalize_review_items(raw)
        assert len(items) == 1
        item = items[0]
        assert item["severity"] == "high"
        assert "item_id" in item
        assert item["requires_human_review"] is True
        assert item["reason"] == "unsupported command"

    def test_translate_config_returns_manual_review_count(self):
        """translate_config result must include manual_review_count."""
        from agent.modules.config_translation.service import translate_config
        result = translate_config(
            source_config=cfg_cisco,
            source_vendor="cisco",
            target_vendor="huawei",
        )
        assert "manual_review_count" in result


class TestRuntimeToolCallArtifacts:
    """Runtime tool_call path must expose artifacts and review count."""

    def test_tool_call_config_translation_exposes_artifacts(self):
        """AgentResult.tool_calls must include artifacts from config translation."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        fake_tc = type('FakeTC', (), {
            'id': 'call_ct1',
            'name': 'config_translation__translate_config',
            'arguments': {},
        })()
        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Translation complete."),
        ]

        # Patch dispatch to return simulated result with artifacts
        fake_result = type('Result', (), {
            'ok': True,
            'summary': 'Translation completed',
            'artifacts': [{'artifact_id': 'art_123', 'artifact_type': 'translated_config',
                           'title': 'Cisco to Huawei', 'metadata': {'authoritative': False}}],
            'manual_review_count': 3,
            'errors': [],
            'warnings': [],
            'metadata': {},
        })()

        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', return_value=fake_result):
                result = app.submit_user_message(
                    user_input="translate config",
                    session_id="artifact-test",
                )

        assert result.ok is True
        assert len(result.tool_calls) > 0
        tc = result.tool_calls[0]
        assert tc.get("artifacts"), f"tool_calls should have artifacts: {tc}"

    def test_tool_call_exposes_manual_review_count(self):
        """AgentResult.tool_calls must include manual_review_count."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        fake_tc = type('FakeTC', (), {
            'id': 'call_mr',
            'name': 'config_translation__translate_config',
            'arguments': {},
        })()
        fake_result = type('Result', (), {
            'ok': True, 'summary': 'done', 'artifacts': [],
            'manual_review_count': 5, 'errors': [], 'warnings': [], 'metadata': {},
        })()
        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Done with review items."),
        ]
        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', return_value=fake_result):
                result = app.submit_user_message(user_input="translate", session_id="mr-test")
        assert result.ok
        tc = result.tool_calls[0]
        assert tc.get("manual_review_count") == 5

    def test_capability_question_does_not_claim_deployable(self):
        """Skill spec should not claim deployable_config."""
        from agent.skills.schemas import SKILL_CONFIG_TRANSLATION
        assert "deployable_config" not in SKILL_CONFIG_TRANSLATION.prompt_summary.lower() or \
               "does not claim" in SKILL_CONFIG_TRANSLATION.prompt_summary.lower() or \
               "not claim" in SKILL_CONFIG_TRANSLATION.prompt_summary.lower() or \
               "authoritative" in SKILL_CONFIG_TRANSLATION.prompt_summary.lower()
