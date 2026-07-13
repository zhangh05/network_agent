# Memory governance and LLM-first gate contracts.
"""Phase 8: Memory Governance tests."""

import json, pytest, uuid
from typing import get_args
from workspace.memory_governance import (
    MemoryRecord, MemorySource, MemoryStore, MemoryType, MemoryWriteGate,
    confirm_memory, reject_memory, expire_memory,
)


class TestMemoryWriteGate:
    def test_schema_includes_runtime_memory_types_and_sources(self):
        assert {"profile", "knowledge_note"}.issubset(set(get_args(MemoryType)))
        assert {"subagent", "llm_tool", "task", "action", "user_signal"}.issubset(set(get_args(MemorySource)))

    def test_agent_suggestion_default_pending(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id=f"ws_agent_{uuid.uuid4().hex[:8]}", session_id="s1",
            source="agent_suggestion", confidence=0.5,
            content="User prefers short answers",
            summary="Preference: short answers",
        )
        result = gate.write(rec)
        assert result["ok"]
        assert result["status"] == "pending"

    def test_user_explicit_can_be_active(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id=f"ws_user_{uuid.uuid4().hex[:8]}", session_id="s1",
            source="user", confidence=0.9, status="active",
            content="User set preferred language to zh-CN",
            summary="Language preference: zh-CN",
        )
        result = gate.write(rec)
        assert result["ok"]

    def test_subagent_forced_pending(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id=f"ws_sub_{uuid.uuid4().hex[:8]}", session_id="s1",
            created_by="subagent", source="tool", status="active",
            content="Found pattern: OSPF config fix",
            summary="Pattern: OSPF fix",
        )
        result = gate.write(rec)
        assert result["ok"]
        assert result["status"] == "pending"

    def test_secret_rejected(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test",
            content="API key is sk-abcdefghijklmnopqrstuvwxyz12345",
            summary="API key storage",
        )
        result = gate.write(rec)
        assert result["ok"] is False
        assert result["rejected"] is True

    def test_segmented_secret_rejected(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test",
            content="api key sk-test-secret-1234567890abcdef should not store",
            summary="API key storage",
        )
        result = gate.write(rec)
        assert result["ok"] is False
        assert result["rejected"] is True

    def test_secret_in_metadata_is_rejected(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        record = MemoryRecord(
            workspace_id="ws_meta_secret",
            content="Reusable operational finding with sufficient detail.",
            summary="Operational finding",
            metadata={"nested": {"api_key": "sk-abcdefghijklmnopqrstuvwxyz12345"}},
        )
        result = MemoryWriteGate().write(record)
        assert result["ok"] is False
        assert result["rejected"] is True
        assert MemoryStore().get(record.workspace_id, record.memory_id) is None

    def test_store_redacts_structured_projection_fields(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        record = MemoryRecord(
            workspace_id="ws_structured_redaction",
            status="pending",
            content="Safe content",
            summary="Safe summary",
            metadata={"password": "short-value"},
            citations=[{"authorization": "short-value"}],
        )
        MemoryStore()._save(record)
        stored = MemoryStore().get(record.workspace_id, record.memory_id)
        assert stored.metadata["password"] == "[REDACTED]"
        assert stored.citations[0]["authorization"] == "[REDACTED]"

    def test_workspace_required(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(workspace_id="", content="test")
        result = gate.write(rec)
        assert result["ok"] is False
        assert result["rejected"] is True

    def test_llm_first_fallback_surfaces_warning(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg

        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)

        def boom(self, candidates):
            raise RuntimeError("provider leaked prompt should not appear")

        monkeypatch.setattr("agent.runtime.memory_write.llm_gate.MemoryLLMGate.gate", boom)
        result = MemoryWriteGate().write(
            MemoryRecord(
                workspace_id="ws_llm_fb",
                source="agent_suggestion",
                confidence=0.9,
                content="keep this operational lesson",
                summary="operational lesson",
            ),
            gate_mode="llm_first",
        )

        # LLM failure → pending review (never silently accepted or lost)
        assert result["ok"] is True
        assert result["status"] == "pending"
        assert result["rejected"] is False
        assert result["warnings"] == [{"reason": "llm_gate_unavailable"}]
        assert "provider leaked prompt" not in str(result)

    def test_rule_only_agent_suggestion_stays_pending(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        result = MemoryWriteGate().write(MemoryRecord(
            workspace_id="ws_rule_pending",
            source="agent_suggestion",
            status="active",
            confidence=0.99,
            content="PE1 uses loopback 2.2.2.9 as its BGP router ID.",
            summary="PE1 BGP router ID is 2.2.2.9",
        ), gate_mode="rule_only")
        assert result["ok"] is True
        assert result["status"] == "pending"

    @pytest.mark.parametrize("score,expected", [(4, "active"), (3, "pending")])
    def test_llm_first_cached_score_drives_lifecycle(self, tmp_path, monkeypatch, score, expected):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)

        def must_not_call(self, candidates):
            raise AssertionError("cached generation decision must avoid a second LLM call")

        monkeypatch.setattr("agent.runtime.memory_write.llm_gate.MemoryLLMGate.gate", must_not_call)
        result = MemoryWriteGate().write(MemoryRecord(
            workspace_id=f"ws_cached_{score}",
            source="agent_suggestion",
            status="pending",
            confidence=0.9,
            content="Device PE1 has BGP router ID 2.2.2.9 from the verified inspection output.",
            summary="PE1 BGP router ID 2.2.2.9",
            metadata={"llm_score": score, "llm_keep": True, "llm_summary": "PE1 BGP router ID"},
        ), gate_mode="llm_first")
        assert result["ok"] is True
        assert result["status"] == expected

    def test_llm_first_low_cached_score_is_rejected_and_audited(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        record = MemoryRecord(
            workspace_id="ws_cached_low",
            source="agent_suggestion",
            content="The generic operation completed without a reusable finding.",
            summary="Generic operation completed",
            metadata={"llm_score": 2, "llm_keep": False},
        )
        result = MemoryWriteGate().write(record, gate_mode="llm_first")
        assert result["ok"] is False
        assert result["status"] == "rejected"
        stored = MemoryStore().get(record.workspace_id, record.memory_id)
        assert stored is not None and stored.status == "rejected"

    def test_content_without_summary_is_not_automatically_low_value(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        result = MemoryWriteGate().write(MemoryRecord(
            workspace_id="ws_no_summary",
            source="user",
            status="active",
            content="Prefer concise Chinese explanations for routine inspection results.",
            summary="",
            confidence=1.0,
        ))
        assert result["ok"] is True
        assert result["status"] == "active"


class TestPromotion:
    def test_confirm_makes_active(self):
        ws = f"ws_mem_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        rec = MemoryRecord(workspace_id=ws, session_id="s1", content="test",
                           summary="Test memory", status="pending")
        gate.write(rec)
        result = confirm_memory(ws, rec.memory_id)
        assert result["ok"]
        assert result["status"] == "active"

    def test_reject_makes_rejected(self):
        ws = f"ws_mr_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        rec = MemoryRecord(workspace_id=ws, content="test", status="pending")
        gate.write(rec)
        result = reject_memory(ws, rec.memory_id)
        assert result["ok"]
        assert result["status"] == "rejected"

    def test_expire_makes_expired(self):
        ws = f"ws_me_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        rec = MemoryRecord(workspace_id=ws, content="test", status="active")
        gate.write(rec)
        result = expire_memory(ws, rec.memory_id)
        assert result["ok"]
        assert result["status"] == "expired"


class TestRetrieval:
    def test_pending_confirmation_updates_context_projection(self, tmp_path, monkeypatch):
        import core.context.context_store as context_store
        import workspace.memory_governance as mg

        monkeypatch.setattr(mg, "WS_ROOT", tmp_path / "workspaces")
        monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "context"))
        context_store._stores.clear()

        ws = "ws_projection"
        record = MemoryRecord(
            workspace_id=ws,
            status="pending",
            source="agent_suggestion",
            content="PE1 uses router ID 2.2.2.9 for BGP sessions.",
            summary="PE1 BGP router ID",
        )
        result = MemoryWriteGate().write(record, gate_mode="rule_only")
        assert result["status"] == "pending"
        projection = context_store.get_context_store(ws)
        assert projection.get(f"mh_{record.memory_id}") is None

        assert confirm_memory(ws, record.memory_id)["ok"] is True
        indexed = projection.get(f"mh_{record.memory_id}")
        assert indexed is not None
        assert indexed["memory_status"] == "active"

        assert reject_memory(ws, record.memory_id)["ok"] is True
        assert projection.get(f"mh_{record.memory_id}") is None

    def test_pending_not_retrievable(self):
        ws = f"ws_rp_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws, status="pending", content="test",
                           scope="workspace")
        store._save(rec)
        results = store.list_retrievable(ws)
        assert not any(r["memory_id"] == rec.memory_id for r in results)

    def test_active_retrievable(self):
        ws = f"ws_ra_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws, status="active", content="test",
                           scope="workspace")
        store._save(rec)
        results = store.list_retrievable(ws)
        assert any(r["memory_id"] == rec.memory_id for r in results)

    def test_store_rejects_invalid_workspace_id(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg

        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        store = MemoryStore()

        with pytest.raises(ValueError):
            store._save(MemoryRecord(workspace_id="../x", status="active", content="bad"))

        assert not (tmp_path.parent / "x").exists()

    def test_cross_workspace_not_visible(self):
        ws_a = f"ws_ma_{uuid.uuid4().hex[:8]}"
        ws_b = f"ws_mb_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws_a, status="active", scope="workspace")
        store._save(rec)
        results = store.list_retrievable(ws_b)
        assert not any(r["memory_id"] == rec.memory_id for r in results)

    def test_expired_not_retrievable(self):
        ws = f"ws_ret_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        import time
        rec = MemoryRecord(workspace_id=ws, status="active",
                           content="test", scope="workspace",
                           expires_at=time.strftime("%Y-%m-%dT%H:%M:%S",
                                                    time.localtime(time.time() - 3600)))
        store._save(rec)
        results = store.list_retrievable(ws)
        assert not any(r["memory_id"] == rec.memory_id for r in results)


class TestConflict:
    def test_similar_content_detected_as_conflict(self):
        ws = f"ws_cf_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        r1 = MemoryRecord(workspace_id=ws, scope="workspace",
                          memory_type="user_preference", status="active",
                          content="prefer short answers", summary="short answers")
        gate.write(r1)
        r2 = MemoryRecord(workspace_id=ws, scope="workspace",
                          memory_type="user_preference",
                          content="user likes short concise answers",
                          summary="short concise answers")
        result = gate.write(r2)
        assert result["ok"]
        # Should be conflict since similar to active
        assert result["status"] in ("conflict", "pending")

    def test_chinese_network_content_detected_as_conflict(self):
        ws = f"ws_cjk_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        r1 = MemoryRecord(
            workspace_id=ws,
            scope="workspace",
            memory_type="operational_fact",
            status="active",
            source="manual_confirm",
            confidence=0.95,
            content="BGP邻居建立失败通常需要检查AS号、peer地址和路由可达性。",
            summary="BGP邻居建立失败需检查AS号 peer地址 路由可达性",
        )
        gate.write(r1)
        r2 = MemoryRecord(
            workspace_id=ws,
            scope="workspace",
            memory_type="operational_fact",
            status="active",
            source="manual_confirm",
            confidence=0.95,
            content="BGP peer 建立异常时优先确认AS号码、邻居地址以及路由是否可达。",
            summary="BGP peer建立异常优先确认AS号码邻居地址路由可达",
        )
        result = gate.write(r2)
        assert result["ok"]
        assert result["status"] == "conflict"

    def test_active_not_overwritten_by_conflict(self):
        ws = f"ws_ao_{uuid.uuid4().hex[:8]}"
        gate = MemoryWriteGate()
        store = MemoryStore()
        r1 = MemoryRecord(workspace_id=ws, scope="workspace",
                          memory_type="operational_fact", status="active",
                          source="user", confidence=1.0,
                          content="OSPF area 0 configured", summary="OSPF area 0")
        gate.write(r1)
        # Verify r1 is active
        loaded1 = store.get(ws, r1.memory_id)
        assert loaded1 is not None
        assert loaded1.status == "active"

        r2 = MemoryRecord(workspace_id=ws, scope="workspace",
                          memory_type="operational_fact",
                          source="agent_suggestion", confidence=0.5,
                          content="OSPF area 0 setup done",
                          summary="OSPF area 0 setup")
        gate.write(r2)
        # r1 should still be active — conflicts don't overwrite
        loaded = store.get(ws, r1.memory_id)
        assert loaded is not None
        assert loaded.status == "active"

    def test_confirming_conflict_expires_previous_active_memory(self, tmp_path, monkeypatch):
        import workspace.memory_governance as mg
        monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
        ws = "ws_conflict_confirm"
        gate = MemoryWriteGate()
        old = MemoryRecord(
            workspace_id=ws, memory_type="user_preference", status="active",
            source="user", confidence=1.0,
            content="User prefers concise Chinese operational summaries.",
            summary="Preference for concise Chinese summaries",
        )
        assert gate.write(old)["ok"] is True
        replacement = MemoryRecord(
            workspace_id=ws, memory_type="user_preference", status="active",
            source="user", confidence=1.0,
            content="User now prefers detailed Chinese operational summaries.",
            summary="Preference for detailed Chinese summaries",
        )
        result = gate.write(replacement)
        assert result["status"] == "conflict"
        assert replacement.conflict_group
        assert MemoryStore().get(ws, old.memory_id).conflict_group == replacement.conflict_group

        assert confirm_memory(ws, replacement.memory_id)["ok"] is True
        assert MemoryStore().get(ws, old.memory_id).status == "expired"
        assert MemoryStore().get(ws, replacement.memory_id).status == "active"


class TestMemoryLLMGate:
    def test_batches_all_candidates_without_dropping_tail(self, monkeypatch):
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate
        from agent.runtime.memory_write.models import MemoryCandidate

        calls = []

        def fake_call(messages):
            payload = json.loads(messages[1]["content"].split("\n", 1)[1])
            calls.append(len(payload))
            return json.dumps({"candidates": [
                {"id": item["id"], "score": 4, "keep": True,
                 "summary": item["content"][:30], "semantic_duplicate_of": None}
                for item in payload
            ]})

        monkeypatch.setattr(MemoryLLMGate, "_call_llm", staticmethod(fake_call))
        candidates = [
            MemoryCandidate(
                candidate_id=f"mc_{index}", memory_type="operational_fact",
                content=f"Reusable device fact number {index}", confidence=0.8,
            )
            for index in range(7)
        ]
        accepted, skipped = MemoryLLMGate().gate(candidates)
        assert calls == [5, 2]
        assert len(accepted) == 7
        assert skipped == []

    def test_unavailable_batch_returns_pending_signal_not_accept_all(self, monkeypatch):
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate
        from agent.runtime.memory_write.models import MemoryCandidate

        monkeypatch.setattr(
            MemoryLLMGate, "_call_llm",
            staticmethod(lambda messages: (_ for _ in ()).throw(RuntimeError("offline"))),
        )
        candidate = MemoryCandidate(
            candidate_id="mc_offline", memory_type="operational_fact",
            content="Potentially reusable fact that still needs review.", confidence=0.8,
        )
        accepted, skipped = MemoryLLMGate().gate([candidate])
        assert accepted == []
        assert skipped == [{
            "candidate_id": "mc_offline",
            "reason": "llm_gate_unavailable",
            "memory_type": "operational_fact",
        }]
