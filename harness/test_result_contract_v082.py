# harness/test_result_contract_v082.py
"""Tests for v0.8.2 Result Contract Standardization.

Covers:
  1-2. ModuleResult.success() / failure() factories
  3.   ModuleResult.to_dict / from_dict roundtrip
  4-5. ToolResult.from_module_result keeps data + artifacts
  6-7. config_translation / knowledge project to ModuleResult
  8-9. config_translation / knowledge tool handlers return standard ToolResult
  10.  AgentResult.tool_calls standardized fields
  11.  Missing fields default to safe values, no KeyError
  12.  v0.7.1 artifact / source_summary / manual_review_count fields preserved
  13.  ToolResult.from_legacy_dict adapts v0.7.x dict shape
  14.  _to_standard_tool_call helper handles all input shapes
  15.  Loop projection survives ToolResult / dict / object inputs
  16.  ModuleResult.from_dict tolerates missing fields
"""

import pytest

from agent.protocol import ModuleResult, ToolResult


# ── 1-2. ModuleResult.success() / failure() factories ──
class TestModuleResultFactories:
    def test_success_factory(self):
        mr = ModuleResult.success(
            summary="translated ok",
            data={"translated_config": "interface X", "manual_review_count": 0},
            artifacts=[{"artifact_id": "a1", "artifact_type": "translated_config"}],
            warnings=[],
            metadata={"elapsed_ms": 12},
        )
        assert mr.ok is True
        assert mr.errors == []
        assert mr.is_success is True
        assert mr.is_failure is False
        assert mr.summary == "translated ok"
        assert mr.data["translated_config"] == "interface X"
        assert mr.data["manual_review_count"] == 0
        assert len(mr.artifacts) == 1
        assert mr.artifacts[0]["artifact_type"] == "translated_config"

    def test_failure_factory(self):
        mr = ModuleResult.failure(
            summary="missing source",
            errors=["missing_source_config"],
            warnings=[],
            metadata={},
        )
        assert mr.ok is False
        assert "missing_source_config" in mr.errors
        assert mr.is_failure is True
        # When failure() is called with no errors, the contract
        # guarantees a placeholder.
        mr2 = ModuleResult.failure(summary="oops", errors=[])
        assert mr2.errors == ["unknown_error"]


# ── 3. ModuleResult.to_dict / from_dict roundtrip ──
class TestModuleResultSerialization:
    def test_roundtrip(self):
        original = ModuleResult.success(
            summary="ok",
            data={"k": 1},
            artifacts=[{"artifact_id": "x"}],
            warnings=["w1"],
            metadata={"m": 2},
        )
        d = original.to_dict()
        rebuilt = ModuleResult.from_dict(d)
        assert rebuilt.ok == original.ok
        assert rebuilt.summary == original.summary
        assert rebuilt.data == original.data
        assert rebuilt.artifacts == original.artifacts
        assert rebuilt.warnings == original.warnings
        assert rebuilt.metadata == original.metadata
        assert rebuilt.errors == original.errors

    def test_from_dict_tolerates_missing_fields(self):
        mr = ModuleResult.from_dict({})
        assert mr.ok is False
        assert mr.summary == ""
        assert mr.data == {}
        assert mr.artifacts == []
        assert mr.errors == []

    def test_from_dict_infers_failure_from_errors(self):
        # No "ok" key, but errors non-empty → ok=False
        mr = ModuleResult.from_dict({"errors": ["x"]})
        assert mr.ok is False


# ── 4-5. ToolResult.from_module_result keeps data + artifacts ──
class TestToolResultFromModuleResult:
    def test_preserves_data(self):
        mr = ModuleResult.success(
            summary="ok",
            data={"translated_config": "interface X"},
        )
        tr = ToolResult.from_module_result("t1", "c1", mr)
        assert tr.ok is True
        assert tr.data == {"translated_config": "interface X"}
        # data is also reflected in raw
        assert tr.raw["data"] == {"translated_config": "interface X"}

    def test_propagates_artifacts(self):
        artifacts = [
            {"artifact_id": "a1", "artifact_type": "translated_config",
             "title": "Cisco→Huawei", "scope": "workspace",
             "sensitivity": "sensitive", "source": "module_output",
             "metadata": {"authoritative": False, "deployable_config": False}}
        ]
        mr = ModuleResult.success(
            summary="ok", data={}, artifacts=artifacts,
        )
        tr = ToolResult.from_module_result("t1", "c1", mr)
        assert tr.artifacts == artifacts
        assert tr.raw["artifacts"] == artifacts

    def test_propagates_warnings_and_errors(self):
        mr = ModuleResult.failure(
            summary="failed",
            errors=["missing_query"],
            warnings=["knowledge_unavailable"],
        )
        tr = ToolResult.from_module_result("t1", "c1", mr)
        assert tr.errors == ["missing_query"]
        assert tr.warnings == ["knowledge_unavailable"]
        assert tr.ok is False


# ── 6. config_translation → ModuleResult ──
class TestConfigTranslationToModuleResult:
    def test_success(self):
        from agent.modules.config_translation.service import to_module_result
        result = {
            "ok": True,
            "summary": "translated Cisco to Huawei",
            "translated_config": "interface X",
            "manual_review_items": [],
            "manual_review_count": 0,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
            "line_count": 10,
            "artifacts": [],
            "warnings": [],
            "errors": [],
            "metadata": {},
        }
        mr = to_module_result(result)
        assert mr.ok is True
        assert mr.data["translated_config"] == "interface X"
        assert mr.data["source_vendor"] == "cisco"
        assert mr.data["target_vendor"] == "huawei"
        assert mr.data["manual_review_count"] == 0
        assert mr.data["line_count"] == 10


# ── 7. knowledge → ModuleResult ──
class TestKnowledgeToModuleResult:
    def test_success(self):
        from agent.modules.knowledge.service import to_module_result
        result = {
            "ok": True,
            "summary": "found 2 hits",
            "query": "OSPF",
            "hits": [{"title": "RFC 2328"}, {"title": "OSPF Guide"}],
            "source_count": 2,
            "source_summary": [
                {"title": "RFC 2328", "source": "rfc", "score": 0.9, "snippet": "OSPF v2"},
            ],
            "warnings": [],
            "errors": [],
            "metadata": {},
        }
        mr = to_module_result(result)
        assert mr.ok is True
        assert mr.data["query"] == "OSPF"
        assert mr.data["source_count"] == 2
        assert len(mr.data["hits"]) == 2
        assert len(mr.data["source_summary"]) == 1


# ── 8-9. config_translation / knowledge tool handlers return standard ToolResult ──
class TestToolHandlersReturnStandardToolResult:
    def test_config_translation_tool_handler(self):
        from agent.modules.config_translation.tools import tool_handler
        out = tool_handler({
            "source_config": "interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0",
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        # All 10 standard fields present
        required = {"call_id", "tool_id", "ok", "summary", "artifacts",
                    "source_count", "manual_review_count", "errors",
                    "warnings", "metadata"}
        assert required.issubset(out.keys()), f"missing: {required - out.keys()}"
        assert out["tool_id"] == "config_translation.translate_config"
        # Legacy compat: manual_review_count at top level
        assert "manual_review_count" in out
        # Data is structured
        assert isinstance(out.get("data"), dict)
        assert "translated_config" in out["data"]

    def test_knowledge_tool_handler(self):
        from agent.modules.knowledge.tools import tool_handler
        out = tool_handler({"query": "OSPF"})
        required = {"call_id", "tool_id", "ok", "summary", "artifacts",
                    "source_count", "manual_review_count", "errors",
                    "warnings", "metadata"}
        assert required.issubset(out.keys())
        assert out["tool_id"] == "knowledge.query"
        # Data is structured
        assert isinstance(out.get("data"), dict)
        assert "hits" in out["data"]


# ── 10. AgentResult.tool_calls standardized fields ──
class TestAgentResultToolCallsStandardized:
    def test_to_standard_tool_call_from_dict(self):
        from agent.runtime.loop import _to_standard_tool_call
        out = _to_standard_tool_call("c1", "t1", {
            "ok": True, "summary": "ok", "content": "x", "artifacts": [],
            "errors": [], "warnings": [], "metadata": {},
        })
        required = {"call_id", "tool_id", "ok", "summary", "artifacts",
                    "source_count", "manual_review_count", "errors",
                    "warnings", "metadata"}
        assert required.issubset(out.keys())
        assert out["call_id"] == "c1"
        assert out["tool_id"] == "t1"

    def test_to_standard_tool_call_from_toolresult(self):
        from agent.runtime.loop import _to_standard_tool_call
        tr = ToolResult(
            call_id="c2", tool_id="t2", ok=False,
            errors=["e1"], warnings=["w1"],
        )
        out = _to_standard_tool_call("xx", "yy", tr)
        assert out["call_id"] == "c2"  # ToolResult.call_id wins
        assert out["tool_id"] == "t2"
        assert out["ok"] is False
        assert out["errors"] == ["e1"]

    def test_to_standard_tool_call_from_object(self):
        from agent.runtime.loop import _to_standard_tool_call
        class _Obj:
            ok = True
            summary = "obj"
            artifacts = [{"artifact_id": "a1"}]
            errors = []
            warnings = []
            metadata = {"k": "v"}
        out = _to_standard_tool_call("c3", "t3", _Obj())
        assert out["ok"] is True
        assert out["summary"] == "obj"
        assert out["artifacts"] == [{"artifact_id": "a1"}]
        assert out["metadata"] == {"k": "v"}


# ── 11. Missing fields default to safe values, no KeyError ──
class TestMissingFieldsDefaults:
    def test_sparse_dict_projection_no_keyerror(self):
        from agent.runtime.loop import _to_standard_tool_call
        # Only ok + summary present
        out = _to_standard_tool_call("c", "t", {"ok": True, "summary": "x"})
        assert out["artifacts"] == []
        assert out["errors"] == []
        assert out["warnings"] == []
        assert out["metadata"] == {}
        assert out["source_count"] is None
        assert out["manual_review_count"] is None

    def test_toolresult_from_legacy_dict_no_keyerror(self):
        tr = ToolResult.from_legacy_dict("t", "c", {"ok": True})
        # data extraction falls through to {} when content is non-dict
        assert isinstance(tr.data, dict)
        assert tr.artifacts == []
        assert tr.errors == []
        assert tr.source_count is None


# ── 12. v0.7.1 artifact / source_summary / manual_review_count preserved ──
class TestV071FieldsPreserved:
    def test_config_translation_artifact_preserved(self):
        from agent.modules.config_translation.service import translate_config
        out = translate_config(
            source_config="interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0",
            source_vendor="cisco",
            target_vendor="huawei",
        )
        # manual_review_count is preserved
        assert "manual_review_count" in out
        assert isinstance(out["manual_review_count"], int)
        # artifacts may be present
        if out.get("artifacts"):
            for a in out["artifacts"]:
                assert a.get("artifact_type") == "translated_config"
                assert a.get("metadata", {}).get("authoritative") is False
                assert a.get("metadata", {}).get("deployable_config") is False

    def test_knowledge_source_summary_preserved(self):
        from agent.modules.knowledge.service import query_knowledge
        out = query_knowledge(query="OSPF 协议介绍")
        # source_count + source_summary are both present
        assert "source_count" in out
        assert "source_summary" in out
        # If source_summary is non-empty, snippets must be ≤ 200 chars
        for s in out.get("source_summary", []):
            assert len(s.get("snippet", "")) <= 200


# ── 13. ToolResult.from_legacy_dict adapts v0.7.x dict ──
class TestToolResultFromLegacyDict:
    def test_legacy_v07x_dict_adapts(self):
        legacy = {
            "ok": True,
            "summary": "ok",
            "content": "translated text",
            "artifacts": [{"artifact_id": "a1", "artifact_type": "translated_config"}],
            "manual_review_count": 2,
            "source_count": 5,
            "errors": [],
            "warnings": ["artifact_save_failed"],
            "metadata": {"build_commit": "abc123"},
        }
        tr = ToolResult.from_legacy_dict("t", "c", legacy)
        assert tr.ok is True
        assert tr.artifacts == legacy["artifacts"]
        assert tr.manual_review_count == 2
        assert tr.source_count == 5
        assert tr.warnings == ["artifact_save_failed"]
        assert tr.metadata == {"build_commit": "abc123"}

    def test_legacy_dict_with_dict_content(self):
        legacy = {
            "ok": True, "summary": "ok",
            "content": {"translated_config": "x"},  # dict content
        }
        tr = ToolResult.from_legacy_dict("t", "c", legacy)
        # When content is a dict, it goes into data
        assert tr.data == {"translated_config": "x"}


# ── 14. ModuleResult.from_dict with sparse input ──
class TestModuleResultFromDict:
    def test_only_ok_present(self):
        mr = ModuleResult.from_dict({"ok": True})
        assert mr.ok is True
        assert mr.data == {}
        assert mr.artifacts == []

    def test_only_summary_present(self):
        mr = ModuleResult.from_dict({"summary": "hi"})
        assert mr.summary == "hi"
        assert mr.ok is False  # default

    def test_artifacts_propagated(self):
        mr = ModuleResult.from_dict({"ok": True, "artifacts": [{"artifact_id": "a"}]})
        assert mr.artifacts == [{"artifact_id": "a"}]


# ── 15. ModuleResult.source_count / manual_review_count helpers ──
class TestModuleResultCounters:
    def test_source_count_from_data(self):
        mr = ModuleResult.success(summary="ok", data={"source_count": 7})
        assert mr.source_count() == 7

    def test_source_count_missing_returns_none(self):
        mr = ModuleResult.success(summary="ok", data={})
        assert mr.source_count() is None

    def test_manual_review_count_from_data(self):
        mr = ModuleResult.success(summary="ok", data={"manual_review_count": 3})
        assert mr.manual_review_count() == 3

    def test_manual_review_count_missing_returns_none(self):
        mr = ModuleResult.success(summary="ok", data={})
        assert mr.manual_review_count() is None
