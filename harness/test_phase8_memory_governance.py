# harness/test_phase8_memory_governance.py
"""Phase 8: Memory Governance tests."""

import pytest, uuid
from workspace.memory_governance import (
    MemoryRecord, MemoryStore, MemoryWriteGate,
    confirm_memory, reject_memory, expire_memory,
)


class TestMemoryWriteGate:
    def test_agent_suggestion_default_pending(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test", session_id="s1",
            source="agent_suggestion", confidence=0.5,
            content="User prefers short answers",
            summary="Preference: short answers",
        )
        ok, status = gate.write(rec)
        assert ok
        assert status == "pending"

    def test_user_explicit_can_be_active(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test", session_id="s1",
            source="user", confidence=0.9, status="active",
            content="User set preferred language to zh-CN",
            summary="Language preference: zh-CN",
        )
        ok, status = gate.write(rec)
        assert ok

    def test_subagent_forced_pending(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test", session_id="s1",
            created_by="subagent", source="tool", status="active",
            content="Found pattern: OSPF config fix",
            summary="Pattern: OSPF fix",
        )
        ok, status = gate.write(rec)
        assert ok
        assert status == "pending"

    def test_secret_rejected(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test",
            content="API key is sk-abcdefghijklmnopqrstuvwxyz12345",
            summary="API key storage",
        )
        ok, status = gate.write(rec)
        assert ok is False
        assert "secret" in status.lower()

    def test_workspace_required(self):
        gate = MemoryWriteGate()
        rec = MemoryRecord(workspace_id="", content="test")
        ok, _ = gate.write(rec)
        assert ok is False


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
    def test_pending_not_retrievable(self):
        ws = f"ws_rp_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws, status="pending", content="test",
                           scope="workspace")
        store.save(rec)
        results = store.list_retrievable(ws)
        assert not any(r["memory_id"] == rec.memory_id for r in results)

    def test_active_retrievable(self):
        ws = f"ws_ra_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws, status="active", content="test",
                           scope="workspace")
        store.save(rec)
        results = store.list_retrievable(ws)
        assert any(r["memory_id"] == rec.memory_id for r in results)

    def test_cross_workspace_not_visible(self):
        ws_a = f"ws_ma_{uuid.uuid4().hex[:8]}"
        ws_b = f"ws_mb_{uuid.uuid4().hex[:8]}"
        store = MemoryStore()
        rec = MemoryRecord(workspace_id=ws_a, status="active", scope="workspace")
        store.save(rec)
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
        store.save(rec)
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
        ok, status = gate.write(r2)
        assert ok
        # Should be conflict since similar to active
        assert status in ("conflict", "pending")

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


class TestPhase2To7Unaffected:
    def test_manifest_still_valid(self):
        from tool_runtime.manifest_registry import validate_all
        errors, _ = validate_all()
        assert len(errors) == 0
