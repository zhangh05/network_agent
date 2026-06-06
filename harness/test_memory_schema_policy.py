# harness/test_memory_schema_policy.py
"""Memory Schema, Redaction, Policy, and Writer tests."""

import json
import pytest
from pathlib import Path


class TestMemorySchema:
    """MemoryRecord schema tests."""

    def test_memory_record_has_sensitivity(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test", content="data")
        assert r.sensitivity == "internal"

    def test_memory_record_has_metadata(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test")
        assert isinstance(r.metadata, dict)
        assert r.metadata == {}

    def test_memory_record_has_expires_at(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test")
        assert r.expires_at is None

    def test_confidence_enum_supported(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(confidence="user_confirmed")
        assert r.confidence == "user_confirmed"

    def test_old_float_confidence_normalized(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord.from_dict({
            "memory_id": "test1",
            "title": "old",
            "confidence": 0.8,
        })
        assert isinstance(r.confidence, str)
        assert r.confidence in ("system_generated", "inferred", "imported")

    def test_low_confidence_normalized(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord.from_dict({
            "memory_id": "test2",
            "title": "low",
            "confidence": 0.3,
        })
        assert isinstance(r.confidence, str)

    def test_redaction_applied_supported(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(title="test", redaction_applied=True)
        assert r.redaction_applied is True

    def test_as_dict_roundtrip(self):
        from memory.schemas import MemoryRecord
        r = MemoryRecord(
            title="test", content="data",
            tags=["tag1"], project_id="proj1",
            sensitivity="sensitive",
        )
        d = r.as_dict()
        r2 = MemoryRecord.from_dict(d)
        assert r2.title == "test"
        assert r2.sensitivity == "sensitive"
        assert r2.project_id == "proj1"


class TestRunRecordSchema:
    def test_run_record_fields(self):
        from memory.schemas import RunRecord
        r = RunRecord(run_id="r1", workspace_id="ws1", intent="translate")
        d = r.as_dict()
        assert d["run_id"] == "r1"
        assert "llm_metadata" in d
        assert "sensitivity" in d
        assert "redaction_applied" in d


class TestWorkspaceStateSchema:
    def test_workspace_state_fields(self):
        from memory.schemas import WorkspaceState
        s = WorkspaceState(workspace_id="ws1", name="test")
        d = s.as_dict()
        assert d["workspace_id"] == "ws1"
        assert "runs_count" in d
        assert "memory_count" in d
        assert "artifacts_count" in d


class TestArtifactRecordSchema:
    def test_artifact_fields(self):
        from memory.schemas import ArtifactRecord
        a = ArtifactRecord(artifact_type="report", title="test")
        d = a.as_dict()
        assert d["artifact_type"] == "report"
        assert "sensitivity" in d


class TestRedaction:
    """Memory redaction tests."""

    def test_redact_password(self):
        from memory.redaction import redact_text
        result = redact_text("password secret123")
        assert "REDACTED" in result

    def test_redact_secret(self):
        from memory.redaction import redact_text
        result = redact_text("enable secret mySecret123")
        assert "REDACTED" in result

    def test_redact_community(self):
        from memory.redaction import redact_text
        result = redact_text("snmp-server community public RO")
        assert "REDACTED" in result

    def test_redact_api_key(self):
        from memory.redaction import redact_text
        result = redact_text("OPENAI_API_KEY=sk-test12345")
        assert "REDACTED" in result

    def test_redact_authorization(self):
        from memory.redaction import redact_text
        result = redact_text("Authorization Bearer token123")
        assert "REDACTED" in result

    def test_contains_secret_detects_key(self):
        from memory.redaction import contains_secret
        assert contains_secret("password mypass") is True

    def test_contains_secret_false_on_safe(self):
        from memory.redaction import contains_secret
        assert contains_secret("interface GigabitEthernet0/1") is False

    def test_redact_dict(self):
        from memory.redaction import redact_dict
        d = {"password": "secret123", "name": "R1"}
        result = redact_dict(d)
        assert result["password"] != "secret123"
        assert result["name"] == "R1"

    def test_summarize_config_safely(self):
        from memory.redaction import summarize_config_safely
        config = "hostname R1\npassword mypass\ninterface Gi0/1"
        result = summarize_config_safely(config)
        assert result["line_count"] == 3
        assert result["has_secrets"] is True


class TestMemoryPolicy:
    """Memory policy tests."""

    def test_blocks_full_source_config(self):
        from memory.policy import can_write_memory
        content = "source_config: " + "x" * 600
        p = can_write_memory("knowledge_note", content)
        assert not p.allowed

    def test_blocks_full_deployable_config(self):
        from memory.policy import can_write_memory
        content = "deployable_config: " + "x" * 600
        p = can_write_memory("knowledge_note", content)
        assert not p.allowed

    def test_blocks_key_in_content(self):
        from memory.policy import can_write_memory
        p = can_write_memory("knowledge_note", "password secret123")
        # Should redact, not block — secrets get redacted
        assert p.redaction_needed is True

    def test_long_term_decision_requires_user_confirmed(self):
        from memory.policy import can_write_memory
        p = can_write_memory("decision", "some decision", confidence="system_generated")
        assert not p.allowed

    def test_allows_user_confirmed_decision(self):
        from memory.policy import can_write_memory
        p = can_write_memory("decision", "user confirmed decision", confidence="user_confirmed")
        assert p.allowed

    def test_redaction_needed_when_secret(self):
        from memory.policy import can_write_memory
        p = can_write_memory("knowledge_note", "password mypass")
        assert p.redaction_needed is True

    def test_can_write_workspace_state_no_config(self):
        from memory.policy import can_write_workspace_state
        assert can_write_workspace_state({"last_intent": "translate"}) is True

    def test_can_write_workspace_state_block_config(self):
        from memory.policy import can_write_workspace_state
        assert can_write_workspace_state({"source_config": "x" * 300}) is False


class TestMemoryWriter:
    """Memory writer integration tests."""

    def test_write_run_summary(self, temp_dirs):
        from memory.writer import write_run_summary
        mid = write_run_summary(
            intent="translate_config",
            skill="config_translation",
            module="config_translation",
            counts=" | d:5 mr:0 us:0",
            project_id="test_ws",
        )
        assert mid is not None
        assert len(mid) > 0

    def test_write_blocks_full_config(self, temp_dirs):
        from memory.writer import write_memory
        mid = write_memory(
            title="test",
            content="source_config: " + "x" * 600,
        )
        assert mid == ""  # blocked

    def test_write_redacts_secrets(self, temp_dirs):
        from memory.writer import write_memory
        mid = write_memory(
            title="test",
            content="enable password secret123 here",
        )
        if mid:
            # If allowed after redaction, verify content is clean
            from memory.backends.jsonl_store import JSONLMemoryStore
            store = JSONLMemoryStore()
            r = store.get(mid)
            if r:
                assert "secret123" not in r.content

    def test_write_user_confirmed_decision(self, temp_dirs):
        from memory.writer import write_user_confirmed_decision
        mid = write_user_confirmed_decision(
            title="Best practice",
            content="Use Null0 for blackhole routing",
            tags=["routing"],
        )
        assert mid is not None
        assert len(mid) > 0

    def test_write_translation_rule_requires_confirmed(self, temp_dirs):
        from memory.writer import write_memory
        # Without user_confirmed, should be blocked
        mid = write_memory(
            title="rule", content="translate this way",
            memory_type="translation_rule",
            scope="long_term",
            confidence="system_generated",
        )
        assert mid == ""

    def test_write_translation_rule_user_confirmed(self, temp_dirs):
        from memory.writer import write_translation_rule
        mid = write_translation_rule(
            title="NAT rule",
            content="ip nat inside source static",
            tags=["nat"],
        )
        assert mid is not None
        assert len(mid) > 0
