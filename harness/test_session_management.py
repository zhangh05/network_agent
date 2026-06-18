"""Session Management — comprehensive tests for conversation session layer.

Covers:
- Session CRUD (create, get, list, update)
- Soft archive / soft delete / permanent delete semantics
- Run-to-session association
- Message recovery from session runs
- Auto-title from user input
- Workspace isolation
"""

import sys
import os
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.session_store import (
    create_session,
    get_session,
    list_sessions,
    update_session,
    archive_session,
    soft_delete_session,
    delete_session_permanently,
    add_run_to_session,
    get_session_messages,
    get_or_create_default_session,
    auto_title_from_input,
    get_session_count,
    list_sessions_by_status,
)
from workspace.run_store import write_run_record
from agent.state import NetworkAgentState


class TestSessionCRUD:
    def test_create_session(self):
        s = create_session("default", "Test CRUD")
        assert s["session_id"]
        assert s["title"] == "Test CRUD"
        assert s["status"] == "active"
        assert s["workspace_id"] == "default"
        assert s["run_ids"] == []

    def test_get_session(self):
        s = create_session("default", "Get Test")
        fetched = get_session(s["session_id"], "default")
        assert fetched is not None
        assert fetched["session_id"] == s["session_id"]

    def test_get_session_not_found(self):
        assert get_session("nonexistent123", "default") is None

    def test_list_sessions_active_only_by_default(self):
        # Clean up: get all active sessions and archive them
        existing = list_sessions("default", status="active")
        for sess in existing:
            archive_session(sess["session_id"], "default")

        s1 = create_session("default", "Active 1")
        s2 = create_session("default", "Active 2")
        archive_session(s2["session_id"], "default")

        active = list_sessions("default", status="active")
        ids = [s["session_id"] for s in active]
        assert s1["session_id"] in ids
        assert s2["session_id"] not in ids

    def test_list_sessions_archived(self):
        s = create_session("default", "Archived Test")
        archive_session(s["session_id"], "default")
        archived = list_sessions("default", status="archived")
        ids = [x["session_id"] for x in archived]
        assert s["session_id"] in ids

    def test_update_session_title(self):
        s = create_session("default", "Old Title")
        updated = update_session(s["session_id"], "default", title="New Title")
        assert updated["title"] == "New Title"

    def test_update_session_invalid_status_ignored(self):
        s = create_session("default", "Status Test")
        updated = update_session(s["session_id"], "default", status="invalid_status")
        # Invalid status should be ignored
        assert updated["status"] == "active"


class TestSessionLifecycle:
    def test_archive_session(self):
        s = create_session("default", "To Archive")
        archived = archive_session(s["session_id"], "default")
        assert archived["status"] == "archived"
        fetched = get_session(s["session_id"], "default")
        assert fetched["status"] == "archived"

    def test_soft_delete_session(self):
        s = create_session("default", "To Soft Delete")
        deleted = soft_delete_session(s["session_id"], "default")
        assert deleted["status"] == "deleted"
        fetched = get_session(s["session_id"], "default")
        assert fetched["status"] == "deleted"

    def test_permanent_delete_requires_confirm(self):
        s = create_session("default", "To Perm Delete")
        ok = delete_session_permanently(s["session_id"], "default", confirm=False)
        assert ok is False
        fetched = get_session(s["session_id"], "default")
        assert fetched is not None

    def test_permanent_delete_with_confirm(self):
        s = create_session("default", "To Perm Delete")
        ok = delete_session_permanently(s["session_id"], "default", confirm=True)
        assert ok is True
        fetched = get_session(s["session_id"], "default")
        assert fetched is None


class TestSessionRunAssociation:
    def test_add_run_to_session(self):
        s = create_session("default", "Run Assoc")
        updated = add_run_to_session(s["session_id"], "run_001", "default")
        assert "run_001" in updated["run_ids"]

    def test_add_run_duplicate_ignored(self):
        s = create_session("default", "Run Dup")
        add_run_to_session(s["session_id"], "run_001", "default")
        updated = add_run_to_session(s["session_id"], "run_001", "default")
        assert updated["run_ids"].count("run_001") == 1

    def test_run_record_auto_associates_with_session(self):
        s = create_session("default", "Auto Assoc")
        state = NetworkAgentState(
            request_id="run_auto_001",
            user_input="test input",
            intent="assistant_chat",
            workspace_id="default",
            session_id=s["session_id"],
        )
        run_id = write_run_record(state, "default")
        fetched = get_session(s["session_id"], "default")
        assert run_id in fetched["run_ids"]

    def test_run_record_without_session_no_association(self):
        state = NetworkAgentState(
            request_id="run_no_session_001",
            user_input="test input",
            intent="assistant_chat",
            workspace_id="default",
            session_id=None,
        )
        run_id = write_run_record(state, "default")
        # Should not crash; session should not be modified
        assert run_id


class TestSessionMessages:
    def test_get_session_messages_empty(self):
        s = create_session("default", "Empty Messages")
        msgs = get_session_messages(s["session_id"], "default")
        assert msgs == []

    def test_get_session_messages_from_canonical_store(self):
        from workspace.message_store import SessionMessageStore

        s = create_session("default", "Messages Test")
        store = SessionMessageStore(s["session_id"], "default")
        for i in range(2):
            run_id = f"run_msg_{i}"
            metadata = {"created_at": f"2026-01-01T00:00:0{i}Z"}
            store.write_message(run_id, "user", f"question {i}", metadata)
            store.write_message(run_id, "assistant", f"answer {i}", metadata)

        msgs = get_session_messages(s["session_id"], "default")
        assert len(msgs) == 4
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"


class TestSessionAutoTitle:
    def test_auto_title_from_first_input(self):
        s = create_session("default", "新会话")
        new_title = auto_title_from_input(s["session_id"], "What is OSPF?", "default")
        assert new_title == "What is OSPF?"
        fetched = get_session(s["session_id"], "default")
        assert fetched["title"] == "What is OSPF?"

    def test_auto_title_truncates_long_input(self):
        s = create_session("default", "新会话")
        long_input = "A" * 50
        new_title = auto_title_from_input(s["session_id"], long_input, "default")
        assert new_title.endswith("...")
        assert len(new_title) <= 24  # 20 + "..."

    def test_auto_title_skips_non_generic_titles(self):
        s = create_session("default", "Custom Title")
        result = auto_title_from_input(s["session_id"], "Some input", "default")
        assert result is None  # Should not overwrite custom title


class TestSessionWorkspaceIsolation:
    def test_sessions_isolated_by_workspace(self):
        s1 = create_session("ws_a", "WS A Session")
        s2 = create_session("ws_b", "WS B Session")

        a_sessions = list_sessions("ws_a", status="active")
        b_sessions = list_sessions("ws_b", status="active")

        a_ids = [s["session_id"] for s in a_sessions]
        b_ids = [s["session_id"] for s in b_sessions]

        assert s1["session_id"] in a_ids
        assert s2["session_id"] not in a_ids
        assert s2["session_id"] in b_ids
        assert s1["session_id"] not in b_ids


class TestSessionCounts:
    def test_get_session_count(self):
        # Clean workspace first
        for s in list_sessions("default", status="active"):
            soft_delete_session(s["session_id"], "default")
        for s in list_sessions("default", status="archived"):
            soft_delete_session(s["session_id"], "default")
        for s in list_sessions("default", status="deleted"):
            delete_session_permanently(s["session_id"], "default", confirm=True)

        create_session("default", "Count Active")
        s2 = create_session("default", "Count Archived")
        archive_session(s2["session_id"], "default")
        s3 = create_session("default", "Count Deleted")
        soft_delete_session(s3["session_id"], "default")

        counts = get_session_count("default")
        assert counts["active"] >= 1
        assert counts["archived"] >= 1
        assert counts["deleted"] >= 1
        assert counts["total"] >= 3


class TestSessionDefault:
    def test_get_or_create_default_session(self):
        # First call should create a new session if none exist
        s = get_or_create_default_session("default_get_or_create")
        assert s["status"] == "active"
        # Second call should return the same session
        s2 = get_or_create_default_session("default_get_or_create")
        assert s2["session_id"] == s["session_id"]


if __name__ == "__main__":
    # Run all tests manually
    classes = [
        TestSessionCRUD,
        TestSessionLifecycle,
        TestSessionRunAssociation,
        TestSessionMessages,
        TestSessionAutoTitle,
        TestSessionWorkspaceIsolation,
        TestSessionCounts,
        TestSessionDefault,
    ]
    total = 0
    passed = 0
    failed = 0
    for cls in classes:
        inst = cls()
        for name in dir(inst):
            if name.startswith("test_"):
                total += 1
                try:
                    getattr(inst, name)()
                    passed += 1
                    print(f"  PASS: {cls.__name__}.{name}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL: {cls.__name__}.{name} — {e}")
    print(f"\n{total} tests, {passed} passed, {failed} failed")
