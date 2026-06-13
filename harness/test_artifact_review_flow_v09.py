# harness/test_artifact_review_flow_v09.py
"""Tests for v0.9 Artifact Consumption & Review Flow.

Coverage:
  1.  artifact.list returns translated_config artifact
  2.  artifact.read can read translated_config (authoritative=false / deployable_config=false)
  3.  artifact.read not-found returns ok=false
  4.  artifact.diff returns text diff
  5.  artifact.diff missing artifact returns ok=false
  6.  artifact.export txt / md
  7.  review.list_items returns manual_review_items
  8.  review.update_item modifies status
  9.  review.update_item does NOT modify translated_config
  10. review.update_item does NOT produce deployable_config
  11. CapabilityRegistry includes artifact / review enabled
  12. Tool count is 62 (= v0.8 baseline 57 + 5 new; one tool_id dedup)
  13. planned topology / inspection / cmdb are still NOT visible
  14. Runtime tool_call artifact.read succeeds
  15. Runtime tool_call review.update_item succeeds
  16. artifact capability safety: no real_device_access, no config.push,
      no deployable_config
  17. review capability safety: requires_human_review, sidecar only
  18. SkillSelector routes "list artifacts" to artifact_management skill
  19. SkillSelector routes "accept review" to review_flow skill
"""

import json
import pytest
from pathlib import Path

from agent.capabilities import get_default_capability_registry
from agent.capabilities.builtin import reset_default_capability_registry_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_default_capability_registry_cache()
    yield
    reset_default_capability_registry_cache()


@pytest.fixture
def reg():
    return get_default_capability_registry()


# ── End-to-end: produce an artifact, then exercise artifact + review tools ──

@pytest.fixture
def ws_with_translation(temp_dirs):
    """Set up a workspace with a translated_config artifact.

    Returns (workspace_id, artifact_id, item_ids, ws_root).
    """
    from artifacts.store import save_artifact
    ws_id = "test_ws_v09"
    # Save an artifact with manual_review_items (save_artifact creates
    # the workspace directory on demand).
    rec = save_artifact(
        workspace_id=ws_id,
        content="interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0\n!",
        artifact_type="translated_config",
        title="Cisco→Huawei (test)",
        scope="workspace",
        sensitivity="sensitive",
        module="config_translation",
        skill="config_translation",
        source="module_output",
        metadata={
            "source_vendor": "cisco",
            "target_vendor": "huawei",
            "line_count": 3,
            "manual_review_count": 2,
            "manual_review_items": [
                {
                    "item_id": "mr_1",
                    "severity": "warning",
                    "category": "acl",
                    "line_no": 2,
                    "source_text": " ip address 10.0.0.1 255.255.255.0",
                    "translated_text": " ip address 10.0.0.1 255.255.255.255",
                    "reason": "subnet mask 255.255.255.0 normalized to /32",
                    "recommendation": "verify if /32 was intended",
                },
                {
                    "item_id": "mr_2",
                    "severity": "info",
                    "category": "header",
                    "line_no": 3,
                    "source_text": "!",
                    "translated_text": "#",
                    "reason": "vendor comment marker",
                    "recommendation": "ok",
                },
            ],
            "authoritative": False,
            "deployable_config": False,
            "quality_gate_passed": True,
        },
    )
    assert rec is not None
    yield ws_id, rec.artifact_id, ["mr_1", "mr_2"], temp_dirs["workspace_dir"]


# ── 1. artifact.list returns translated_config ──
class TestArtifactList:
    def test_list_returns_translated_config(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import list_artifacts_for_session
        result = list_artifacts_for_session(workspace_id=ws_id)
        assert result["ok"] is True
        assert result["count"] >= 1
        types = {a.get("artifact_type") for a in result["artifacts"]}
        assert "translated_config" in types
        # The list records must be sanitized — no local file paths.
        for a in result["artifacts"]:
            for forbidden_key in ("path", "file_path", "local_path", "absolute_path"):
                assert forbidden_key not in a, f"local path leaked: {forbidden_key}"


# ── 2. artifact.read returns content with authoritative=false / deployable_config=false ──
class TestArtifactRead:
    def test_read_translated_config_preserves_safety(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import read_artifact
        result = read_artifact(workspace_id=ws_id, artifact_id=art_id,
                               allow_sensitive=True)
        assert result["ok"] is True
        assert "translated_config" in result.get("content", "") or \
               "ip address" in result.get("content", "")
        assert result["authoritative"] is False
        assert result["deployable_config"] is False
        # translated_config artifact's metadata still says not deployable
        assert result["metadata"].get("authoritative") is False
        assert result["metadata"].get("deployable_config") is False


# ── 3. artifact.read not-found returns ok=false ──
class TestArtifactReadNotFound:
    def test_missing_artifact_returns_ok_false(self):
        from agent.modules.artifact.service import read_artifact
        result = read_artifact(workspace_id="test_ws_v09",
                               artifact_id="art_does_not_exist",
                               allow_sensitive=True)
        assert result["ok"] is False
        assert "artifact_not_found" in result["errors"]


# ── 4. artifact.diff returns text diff ──
class TestArtifactDiff:
    def test_diff_returns_text(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from artifacts.store import save_artifact
        # Save a second artifact with different content
        rec2 = save_artifact(
            workspace_id=ws_id,
            content="interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0\n!NEW LINE",
            artifact_type="translated_config",
            title="Cisco→Huawei v2",
            scope="workspace",
            sensitivity="sensitive",
            module="config_translation",
            metadata={"authoritative": False, "deployable_config": False},
        )
        from agent.modules.artifact.service import diff_artifacts
        result = diff_artifacts(workspace_id=ws_id,
                                left_artifact_id=art_id,
                                right_artifact_id=rec2.artifact_id)
        assert result["ok"] is True
        assert "diff" in result
        assert "NEW LINE" in result["diff"]
        assert result["left_artifact_id"] == art_id


# ── 5. artifact.diff missing artifact returns ok=false ──
class TestArtifactDiffMissing:
    def test_missing_left_returns_ok_false(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import diff_artifacts
        result = diff_artifacts(workspace_id=ws_id,
                                left_artifact_id="art_does_not_exist",
                                right_artifact_id=art_id)
        assert result["ok"] is False
        assert "artifact_not_found" in result["errors"]

    def test_missing_right_returns_ok_false(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import diff_artifacts
        result = diff_artifacts(workspace_id=ws_id,
                                left_artifact_id=art_id,
                                right_artifact_id="art_does_not_exist")
        assert result["ok"] is False
        assert "artifact_not_found" in result["errors"]


# ── 6. artifact.export txt / md ──
class TestArtifactExport:
    def test_export_txt(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import export_artifact
        result = export_artifact(workspace_id=ws_id, artifact_id=art_id,
                                  format="txt")
        assert result["ok"] is True
        assert result["format"] == "txt"
        assert "ip address" in result["rendered"]
        # Surface deployable_config flag (False)
        assert result["deployable_config"] is False

    def test_export_md_includes_metadata_header(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import export_artifact
        result = export_artifact(workspace_id=ws_id, artifact_id=art_id,
                                  format="md")
        assert result["ok"] is True
        assert "# " in result["rendered"]  # markdown header
        assert "artifact_id" in result["rendered"]
        assert "deployable_config" in result["rendered"]
        assert "False" in result["rendered"]

    def test_export_unsupported_format(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.service import export_artifact
        result = export_artifact(workspace_id=ws_id, artifact_id=art_id,
                                  format="exe")
        assert result["ok"] is False
        assert "unsupported_format" in result["errors"]


# ── 7. review.list_items returns manual_review_items ──
class TestReviewListItems:
    def test_list_items_returns_two(self, ws_with_translation):
        ws_id, art_id, item_ids, _ = ws_with_translation
        from agent.modules.review.service import list_review_items
        result = list_review_items(workspace_id=ws_id, artifact_id=art_id)
        assert result["ok"] is True
        assert result["count"] == 2
        ids = [it["item_id"] for it in result["items"]]
        assert set(ids) == set(item_ids)
        # All items start as pending
        for it in result["items"]:
            assert it["status"] == "pending"
            assert it["user_note"] == ""


# ── 8. review.update_item modifies status ──
class TestReviewUpdateItem:
    def test_update_item_status_accepted(self, ws_with_translation):
        ws_id, art_id, _, ws_root = ws_with_translation
        from agent.modules.review.service import update_review_item
        result = update_review_item(
            workspace_id=ws_id, artifact_id=art_id,
            item_id="mr_1", status="accepted", user_note="OK after manual check",
        )
        assert result["ok"] is True
        assert result["status"] == "accepted"
        assert result["user_note"] == "OK after manual check"
        # Sidecar file exists at {ws_root}/{ws_id}/reviews/{art_id}.json
        sidecar_path = ws_root / ws_id / "reviews" / f"{art_id}.json"
        assert sidecar_path.exists()

    def test_update_then_list_shows_status(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.service import update_review_item, list_review_items
        update_review_item(workspace_id=ws_id, artifact_id=art_id,
                           item_id="mr_2", status="ignored",
                           user_note="auto-marked")
        out = list_review_items(workspace_id=ws_id, artifact_id=art_id)
        for it in out["items"]:
            if it["item_id"] == "mr_2":
                assert it["status"] == "ignored"
                assert it["user_note"] == "auto-marked"
            else:
                assert it["status"] == "pending"

    def test_invalid_status_rejected(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.service import update_review_item
        result = update_review_item(workspace_id=ws_id, artifact_id=art_id,
                                    item_id="mr_1", status="bogus")
        assert result["ok"] is False
        assert "invalid_status" in result["errors"]

    def test_unknown_item_rejected(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.service import update_review_item
        result = update_review_item(workspace_id=ws_id, artifact_id=art_id,
                                    item_id="mr_999", status="accepted")
        assert result["ok"] is False
        assert "item_not_found" in result["errors"]


# ── 9. review.update_item does NOT modify translated_config ──
class TestReviewDoesNotModifyOriginal:
    def test_translated_config_unchanged_after_review(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.service import update_review_item
        from agent.modules.artifact.service import read_artifact
        before = read_artifact(workspace_id=ws_id, artifact_id=art_id,
                                allow_sensitive=True)
        before_content = before["content"]
        update_review_item(workspace_id=ws_id, artifact_id=art_id,
                           item_id="mr_1", status="modified",
                           user_note="suggested change")
        after = read_artifact(workspace_id=ws_id, artifact_id=art_id,
                              allow_sensitive=True)
        assert after["content"] == before_content
        # And the metadata is unchanged
        assert after["metadata"]["authoritative"] is False
        assert after["metadata"]["deployable_config"] is False


# ── 10. review.update_item does NOT produce deployable_config ──
class TestReviewDoesNotProduceDeployableConfig:
    def test_update_result_marks_no_deployable_config(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.service import update_review_item
        result = update_review_item(workspace_id=ws_id, artifact_id=art_id,
                                    item_id="mr_1", status="accepted")
        assert result["ok"] is True
        # The metadata explicitly says no deployable_config was produced
        assert result["metadata"]["deployable_config_produced"] is False
        assert result["metadata"]["original_artifact_modified"] is False


# ── 11. CapabilityRegistry includes artifact / review enabled ──
class TestCapabilityRegistryV09:
    def test_artifact_enabled(self, reg):
        m = reg.get("artifact")
        assert m is not None
        assert m.status == "enabled"
        assert len(m.tools) == 4

    def test_review_enabled(self, reg):
        m = reg.get("review")
        assert m is not None
        assert m.status == "enabled"
        assert len(m.tools) == 2

    def test_visible_tools_includes_all_19(self, reg):
        # v1.0.1.1: read_source is no longer LLM-visible.
        # The LLM-visible set is now 18 (was 19; v1.0.1 set it to 19).
        v = sorted(reg.visible_tool_ids())
        assert v == sorted([
            "config_translation.translate_config",
            "knowledge.query", "knowledge.import_document",
            "knowledge.list_sources",
            "knowledge.disable_source", "knowledge.delete_source",
            "knowledge.import_file", "knowledge.list_chunks",
            "knowledge.search_chunks", "knowledge.read_chunk",
            "knowledge.read_parent", "knowledge.reindex_source",
            "artifact.list", "artifact.read", "artifact.diff", "artifact.export",
            "review.list_items", "review.update_item",
        ])


# ── 12. Tool count is 62 ──
class TestToolCountV09:
    def test_total_tool_count_is_73(self):
        # v1.0.1 adds 6 knowledge tool_ids (import_file / list_chunks /
        # search_chunks / read_chunk / read_parent / reindex_source).
        # Capability layer contributes 19 (2 + 4 + 2 + 6 + 5).
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        tr = svc.tool_service
        total = len(tr.registry.list_all())
        assert total == 76
        reg = get_default_capability_registry()
        assert len(reg.enabled_tools()) == 19


# ── 13. planned topology / inspection / cmdb are still NOT visible ──
class TestPlannedStillNotVisible:
    def test_topology_tools_not_visible(self, reg):
        assert "topology.extract" not in reg.visible_tool_ids()
        assert "topology.render" not in reg.visible_tool_ids()
    def test_inspection_tools_not_visible(self, reg):
        assert "inspection.analyze_outputs" not in reg.visible_tool_ids()
        assert "inspection.generate_report" not in reg.visible_tool_ids()
    def test_cmdb_tools_not_visible(self, reg):
        assert "cmdb.extract_assets" not in reg.visible_tool_ids()
        assert "cmdb.query_assets" not in reg.visible_tool_ids()
        assert "cmdb.upsert_assets" not in reg.visible_tool_ids()


# ── 14. Runtime tool_call artifact.read succeeds ──
class TestRuntimeArtifactRead:
    def test_tool_handler_returns_standard_dict(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.artifact.tools import tool_handler_read
        out = tool_handler_read({"workspace_id": ws_id, "artifact_id": art_id,
                                  "allow_sensitive": True})
        # Standard 10 fields
        for f in ("call_id", "tool_id", "ok", "summary", "artifacts",
                  "source_count", "manual_review_count", "errors",
                  "warnings", "metadata"):
            assert f in out, f"missing {f}"
        assert out["tool_id"] == "artifact.read"
        assert out["ok"] is True
        # Safety surface
        assert out["authoritative"] is False
        assert out["deployable_config"] is False


# ── 15. Runtime tool_call review.update_item succeeds ──
class TestRuntimeReviewUpdate:
    def test_tool_handler_returns_standard_dict(self, ws_with_translation):
        ws_id, art_id, _, _ = ws_with_translation
        from agent.modules.review.tools import tool_handler_update
        out = tool_handler_update({
            "workspace_id": ws_id, "artifact_id": art_id,
            "item_id": "mr_1", "status": "accepted",
            "user_note": "checked by test",
        })
        for f in ("call_id", "tool_id", "ok", "summary", "artifacts",
                  "source_count", "manual_review_count", "errors",
                  "warnings", "metadata"):
            assert f in out, f"missing {f}"
        assert out["tool_id"] == "review.update_item"
        assert out["ok"] is True
        assert out["status"] == "accepted"
        assert out["item_id"] == "mr_1"


# ── 16. artifact capability safety ──
class TestArtifactCapabilitySafety:
    def test_safety_contract(self, reg):
        m = reg.get("artifact")
        assert m.safety.real_device_access is False
        assert m.safety.allows_config_push is False
        assert m.safety.produces_deployable_config is False
        assert m.safety.may_fabricate_sources is False


# ── 17. review capability safety ──
class TestReviewCapabilitySafety:
    def test_safety_contract(self, reg):
        m = reg.get("review")
        assert m.safety.real_device_access is False
        assert m.safety.allows_config_push is False
        assert m.safety.produces_deployable_config is False
        assert m.safety.may_fabricate_sources is False
        assert m.safety.requires_human_review is True


# ── 18. SkillSelector routes "list artifacts" ──
class TestSkillSelectorArtifact:
    def test_list_artifacts_message_selects_artifact_management(self, reg):
        from agent.skills.selector import SkillSelector
        sel = SkillSelector(reg)
        skills = sel.select("请列出当前 workspace 的所有 artifact",
                           capability_registry=reg)
        assert "artifact_management" in skills
        assert "assistant_chat" in skills


# ── 19. SkillSelector routes "accept review" ──
class TestSkillSelectorReview:
    def test_review_message_selects_review_flow(self, reg):
        from agent.skills.selector import SkillSelector
        sel = SkillSelector(reg)
        skills = sel.select("请帮我 accept 一下这个 review item",
                           capability_registry=reg)
        assert "review_flow" in skills
        assert "assistant_chat" in skills
