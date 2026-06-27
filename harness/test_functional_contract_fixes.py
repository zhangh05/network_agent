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
