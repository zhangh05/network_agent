def test_runtime_task_list_rejects_invalid_workspace():
    from backend.main import create_app

    client = create_app().test_client()
    resp = client.get("/api/runtime/tasks?workspace_id=../x")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_workspace_id"


def test_memory_rest_contracts_are_governed_and_validated(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from backend.main import create_app

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    client = create_app().test_client()

    invalid = client.post(
        "/api/memory/write",
        json={"workspace_id": "../x", "title": "bad", "content": "bad"},
    )
    assert invalid.status_code == 400
    assert invalid.get_json()["error"] == "invalid_workspace_id"
    listed = client.get("/api/memory/list?workspace_id=../x")
    assert listed.status_code == 400
    assert listed.get_json()["error"] == "invalid_workspace_id"
    assert not (tmp_path.parent / "x").exists()

    created = client.post(
        "/api/memory/write",
        json={
            "workspace_id": "contract_ws",
            "title": "Remember this",
            "content": "User explicitly confirmed this memory.",
            "user_confirmed": True,
        },
    )
    assert created.status_code == 200
    body = created.get_json()
    assert body["ok"] is True
    assert body["status"] == "active"  # REST API path still honors user_confirmed
    visible = client.get("/api/memory/list?workspace_id=contract_ws")
    assert visible.status_code == 200
    visible_body = visible.get_json()
    assert visible_body["count"] == 1
    assert visible_body["records"][0]["content"] == "User explicitly confirmed this memory."

    old_confirm_mode = client.post(
        "/api/memory/confirm",
        json={"workspace_id": "contract_ws", "title": "old", "content": "old"},
    )
    assert old_confirm_mode.status_code == 400
    assert old_confirm_mode.get_json()["error"] == "memory_id required"

    reject_missing = client.post(
        "/api/memory/reject",
        json={"workspace_id": "contract_ws"},
    )
    assert reject_missing.status_code == 400
    assert reject_missing.get_json()["error"] == "memory_id required"


def test_memory_delete_uses_reject_transition_not_write_gate(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryStore
    from backend.main import create_app

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    store = MemoryStore()
    rec = MemoryRecord(
        workspace_id="delete_ws",
        status="active",
        source="user",
        confidence=1.0,
        content="delete me",
        summary="delete me",
    )
    store._save(rec)

    def fail_write(self, candidate, gate_mode="rule_only"):
        raise AssertionError("delete must not re-enter MemoryWriteGate.write")

    monkeypatch.setattr(mg.MemoryWriteGate, "write", fail_write)
    client = create_app().test_client()

    resp = client.delete(f"/api/memory/{rec.memory_id}?workspace_id=delete_ws")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert MemoryStore().get("delete_ws", rec.memory_id).status == "rejected"


def test_memory_list_redacts_legacy_secret_records(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryStore
    from backend.main import create_app

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    MemoryStore()._save(MemoryRecord(
        workspace_id="list_redact_ws",
        status="pending",
        source="agent_suggestion",
        content="legacy bad secret sk-test-secret-1234567890abcdef",
    ))
    client = create_app().test_client()

    resp = client.get("/api/memory/list?workspace_id=list_redact_ws")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 1
    assert "sk-test-secret-1234567890abcdef" not in str(body)
    assert "[REDACTED]" in str(body)


def test_memory_retriever_filters_non_active_hits(monkeypatch):
    from agent.runtime.memory.models import MemoryQueryPlan
    from agent.runtime.memory.retriever import MemoryRetriever
    import core.context.unified_retriever as unified

    class FakeRetriever:
        def search_memory(self, query, top_k):
            return [
                {"memory_id": "m_pending", "status": "pending", "content": "pending memory"},
                {"memory_id": "m_rejected", "status": "rejected", "content": "rejected memory"},
                {"memory_id": "m_active", "status": "active", "content": "active memory"},
            ]

    monkeypatch.setattr(unified, "get_retriever", lambda workspace_id: FakeRetriever())

    items = MemoryRetriever().retrieve(
        "ws_mem_retrieve",
        MemoryQueryPlan(should_search=True, query_text="memory", top_k=5),
    )

    assert [item.memory_id for item in items] == ["m_active"]


def test_slash_memory_uses_governed_store(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryStore
    from agent.runtime.command_system import execute_command

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    MemoryStore()._save(MemoryRecord(
        workspace_id="slash_ws",
        status="active",
        source="user",
        confidence=1.0,
        content="Slash memory content",
        summary="Slash memory summary",
    ))

    result = execute_command("memory", workspace_id="slash_ws")

    assert "Memory store not available" not in result
    assert "Slash memory summary" in result


def test_usage_requires_valid_workspace_id():
    from backend.main import create_app

    client = create_app().test_client()
    missing = client.get("/api/agent/usage")
    invalid = client.get("/api/agent/usage?workspace_id=../x")

    assert missing.status_code == 400
    assert missing.get_json()["error"] == "workspace_id is required"
    assert invalid.status_code == 400
    assert invalid.get_json()["error"] == "invalid_workspace_id"


def test_runtime_sse_requires_workspace_and_valid_session_id():
    from backend.main import create_app

    client = create_app().test_client()
    missing = client.get("/api/agent/sse/stream/sess-1")
    invalid_ws = client.get("/api/agent/sse/stream/sess-1?workspace_id=../x")
    invalid_sid = client.get("/api/agent/sse/stream/_bad?workspace_id=default")

    assert missing.status_code == 400
    assert missing.get_json()["error"] == "workspace_id is required"
    assert invalid_ws.status_code == 400
    assert invalid_ws.get_json()["error"] == "invalid_workspace_id"
    assert invalid_sid.status_code in (400, 404)


def test_approval_pending_is_workspace_scoped(tmp_path):
    from agent.approval import ApprovalStore

    store = ApprovalStore(tmp_path / "approvals.jsonl")
    store.create("sess-1", "exec.run", {"command": "pwd"}, workspace_id="ws_a")
    store.create("sess-1", "exec.run", {"command": "pwd"}, workspace_id="ws_b")

    assert len(store.get_pending("sess-1", workspace_id="ws_a")) == 1
    assert len(store.get_pending("sess-1", workspace_id="ws_b")) == 1
    assert len(store.get_pending("sess-1", workspace_id="ws_c")) == 0


def test_durable_subagent_profiles_expose_allowed_tools():
    from agent.runtime.durable.subagent import get_profile
    from agent.runtime.services import default_runtime_services
    from agent.tools.router import ToolRouter

    base_router = default_runtime_services().tool_service
    for profile_id in ("review_agent", "fix_agent", "test_agent"):
        profile = get_profile(profile_id)
        router = ToolRouter.for_turn(base_router.registry, allowed_tool_ids=profile.allowed_tools)
        visible = {spec.real_tool_id for spec in router.model_visible_specs}
        assert visible
        assert set(profile.allowed_tools).issubset(visible)


def test_memory_llm_first_gate_can_reject_agent_suggestion(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryWriteGate

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)

    def fake_gate(self, candidates):
        return [], [{"candidate_id": candidates[0].candidate_id, "reason": "llm_score_too_low: 1"}]

    monkeypatch.setattr("agent.runtime.memory_write.llm_gate.MemoryLLMGate.gate", fake_gate)

    result = MemoryWriteGate().write(
        MemoryRecord(
            workspace_id="ws_a",
            source="agent_suggestion",
            content="low value",
            summary="low value",
            confidence=0.9,
        ),
        gate_mode="llm_first",
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "llm_score_too_low: 1"


def test_memory_gate_rejects_invalid_workspace_id(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryWriteGate

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    result = MemoryWriteGate().write(
        MemoryRecord(workspace_id="../x", content="bad", summary="bad"),
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_workspace_id"
    assert not (tmp_path.parent / "x").exists()


def test_task_scope_memory_requires_session_filter(tmp_path, monkeypatch):
    import workspace.memory_governance as mg
    from workspace.memory_governance import MemoryRecord, MemoryStore

    monkeypatch.setattr(mg, "WS_ROOT", tmp_path)
    store = MemoryStore()
    store._save(MemoryRecord(
        workspace_id="ws_a",
        session_id="sess_a",
        scope="task",
        status="active",
        content="task scoped",
    ))

    assert store.list_retrievable("ws_a", session_id="") == []
    assert len(store.list_retrievable("ws_a", session_id="sess_a")) == 1


def test_network_ips_are_not_filtered_as_memory_secrets():
    from agent.runtime.memory_write.filter import MemoryRiskFilter
    from agent.runtime.memory_write.models import MemoryCandidate

    accepted, skipped = MemoryRiskFilter().filter([
        MemoryCandidate(candidate_id="c1", content="Router loopback is 10.0.0.1", memory_type="task_pattern")
    ])

    assert len(accepted) == 1
    assert skipped == []


def test_git_commit_requires_explicit_files(tmp_path):
    import subprocess
    from agent.modules.git.core import git_commit

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    result = git_commit(str(tmp_path), "test")

    assert result["ok"] is False
    assert "files are required" in result["error"]


def test_policy_does_not_scan_descriptive_text_as_path_argument():
    """v3.9.5: _check_argument_safety returns (risk_level, reason).
    Descriptive text mentioning sensitive paths must not be flagged —
    the policy only inspects command-bearing fields.
    """
    from core.tools.policy import _check_argument_safety

    risk, reason = _check_argument_safety(
        {"description": "The user asked whether /etc/passwd should be inspected."},
        tool_id="text.analyze",
    )
    assert risk == "low"
    assert reason == ""
