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
    assert body["status"] == "active"

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


def test_usage_requires_valid_workspace_id():
    from backend.main import create_app

    client = create_app().test_client()
    missing = client.get("/api/agent/usage")
    invalid = client.get("/api/agent/usage?workspace_id=../x")

    assert missing.status_code == 400
    assert missing.get_json()["error"] == "workspace_id is required"
    assert invalid.status_code == 400
    assert invalid.get_json()["error"] == "invalid_workspace_id"


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
