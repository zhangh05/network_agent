import json
import pytest
import shutil


def test_cmdb_asset_password_is_resolved_only_for_internal_connectors():
    from agent.modules.cmdb.service import get_asset, list_assets, save_asset
    from agent.modules.cmdb.tools import tool_add_asset, tool_get_asset
    from storage.paths import workspace_root

    workspace_id = "pytest_asset_secret_flow"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    result = tool_add_asset(
        workspace_id=workspace_id,
        name="edge",
        type="router",
        host="192.0.2.44",
        username="admin",
        password="secret-pass",
    )
    assert result["ok"] is True

    raw = (root / "cmdb" / "assets.jsonl").read_text(encoding="utf-8")
    assert "secret-pass" not in raw
    assert "password_secret" in raw

    safe_list = list_assets(workspace_id)
    assert "password" not in safe_list[0]
    safe_tool = tool_get_asset(workspace_id=workspace_id, asset_id=result["asset_id"])
    rendered = json.dumps(safe_tool, ensure_ascii=False)
    assert "secret-pass" not in rendered
    assert "password" not in safe_tool["asset"]

    internal = get_asset(workspace_id, result["asset_id"], safe=False)
    assert internal and internal["password"] == "secret-pass"

    if root.exists():
        shutil.rmtree(root)


def test_workspace_credential_v3_detects_tampering():
    from storage.credential_store import (
        CREDENTIAL_DECRYPT_FAILED,
        open_credential_strict,
        seal_credential,
    )
    from storage.paths import workspace_root

    workspace_id = "pytest_cmdb_secret_auth"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    sealed = seal_credential(workspace_id, "secret-pass")
    assert sealed.startswith("cred:v3:")
    assert open_credential_strict(workspace_id, sealed) == "secret-pass"

    tampered = sealed[:-2] + ("AA" if not sealed.endswith("AA") else "BB")
    assert (
        open_credential_strict(workspace_id, tampered)
        == CREDENTIAL_DECRYPT_FAILED
    )

    wrong_workspace = "pytest_cmdb_secret_auth_other"
    assert (
        open_credential_strict(wrong_workspace, sealed)
        == CREDENTIAL_DECRYPT_FAILED
    )

    for ws in (workspace_id, wrong_workspace):
        r = workspace_root(ws)
        if r.exists():
            shutil.rmtree(r)


def test_cmdb_update_preserves_created_at():
    from agent.modules.cmdb.service import get_asset, save_asset
    from storage.paths import workspace_root

    workspace_id = "pytest_cmdb_created_at"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    created = save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.40",
            "created_at": "2026-01-01T00:00:00+08:00",
        },
    )
    assert created["ok"] is True
    updated = save_asset(
        workspace_id,
        {
            "asset_id": created["asset_id"],
            "name": "edge-renamed",
            "type": "router",
            "host": "192.0.2.40",
            "port": 22,
        },
    )
    assert updated["ok"] is True
    asset = get_asset(workspace_id, created["asset_id"])
    assert asset["name"] == "edge-renamed"
    assert asset["created_at"] == "2026-01-01T00:00:00+08:00"
    assert asset["updated_at"] != asset["created_at"]

    if root.exists():
        shutil.rmtree(root)


def test_remote_connect_uses_cmdb_asset_id_without_frontend_password(monkeypatch):
    from agent.modules.cmdb.service import save_asset
    from agent.modules.remote import service as remote_service
    from storage.paths import workspace_root

    workspace_id = "pytest_remote_asset_secret"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    asset = save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.45",
            "port": 22,
            "protocol": "ssh",
            "username": "admin",
            "password": "secret-pass",
            "vendor": "h3c",
        },
    )

    captured = {}

    class FakeSession:
        log = ["banner"]
        vendor = type("Vendor", (), {"vendor": "h3c"})()

    def fake_ssh_connect(session_id, host, port, username, password, vendor, **kwargs):
        captured.update({
            "session_id": session_id,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "vendor": vendor,
            **kwargs,
        })
        return FakeSession()

    monkeypatch.setattr(remote_service, "ssh_connect", fake_ssh_connect)
    result = remote_service.connect_device(
        workspace_id=workspace_id,
        host="",
        port=22,
        protocol="ssh",
        username="",
        password="",
        vendor="",
        asset_id=asset["asset_id"],
    )

    assert result["ok"] is True
    assert captured["host"] == "192.0.2.45"
    assert captured["username"] == "admin"
    assert captured["password"] == "secret-pass"
    assert captured["vendor"] == "h3c"
    assert captured["terminal_cols"] == 160
    assert captured["terminal_rows"] == 40
    assert captured["workspace_id"] == workspace_id

    if root.exists():
        shutil.rmtree(root)


def test_cmdb_region_filter_is_visible_to_llm_tools():
    from agent.modules.cmdb.service import save_asset
    from storage.paths import workspace_root
    from core.tools.canonical_registry import _handler_cmdb_list_assets
    from core.tools.schemas import ToolInvocation

    workspace_id = "pytest_cmdb_region_flow"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    assert save_asset(workspace_id, {
        "name": "east-core",
        "type": "switch",
        "host": "192.0.2.51",
        "region": "华东",
        "location": "杭州-A机房",
    })["ok"]
    assert save_asset(workspace_id, {
        "name": "south-core",
        "type": "switch",
        "host": "192.0.2.52",
        "region": "华南",
        "location": "广州-B机房",
    })["ok"]

    direct = _handler_cmdb_list_assets(ToolInvocation(
        tool_id="device.manage",
        workspace_id=workspace_id,
        arguments={"action": "list", "region": "华东", "sort_by": "region"},
    ))
    assert direct["ok"] is True
    assert direct["count"] == 1
    assert direct["assets"][0]["name"] == "east-core"
    assert direct["by_region"]["华东"] == 1
    assert direct["by_region"]["华南"] == 1

    fuzzy = _handler_cmdb_list_assets(ToolInvocation(
        tool_id="device.manage",
        workspace_id=workspace_id,
        arguments={"action": "list", "search": "广州"},
    ))
    assert fuzzy["ok"] is True
    assert [a["name"] for a in fuzzy["assets"]] == ["south-core"]

    shutil.rmtree(root)


def test_remote_connect_falls_back_to_unique_cmdb_asset_when_password_empty(monkeypatch):
    from agent.modules.cmdb.service import save_asset
    from agent.modules.remote import service as remote_service
    from storage.paths import workspace_root

    workspace_id = "pytest_remote_asset_host_fallback"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.47",
            "port": 22,
            "protocol": "ssh",
            "username": "admin",
            "password": "secret-pass",
            "vendor": "h3c",
        },
    )

    captured = {}

    class FakeSession:
        log = ["banner"]
        vendor = type("Vendor", (), {"vendor": "h3c"})()

    def fake_ssh_connect(session_id, host, port, username, password, vendor, **kwargs):
        captured.update({
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "vendor": vendor,
            **kwargs,
        })
        return FakeSession()

    monkeypatch.setattr(remote_service, "ssh_connect", fake_ssh_connect)
    result = remote_service.connect_device(
        workspace_id=workspace_id,
        host="192.0.2.47",
        port=22,
        protocol="ssh",
        username="admin",
        password="",
        vendor="",
    )

    assert result["ok"] is True
    assert captured["password"] == "secret-pass"
    assert captured["terminal_cols"] == 160
    assert captured["terminal_rows"] == 40
    assert captured["workspace_id"] == workspace_id

    shutil.rmtree(root)


def test_remote_session_followup_requires_matching_workspace(monkeypatch):
    from agent.modules.remote import service as remote_service

    class FakeSession:
        connected = True
        workspace_id = "ws_a"

    monkeypatch.setattr(remote_service, "get_session", lambda sid: FakeSession())

    assert remote_service.interactive_input("sid", "\r", workspace_id="ws_b") == {
        "ok": False,
        "error": "session_workspace_mismatch",
    }
    assert remote_service.resize_terminal("sid", 120, 40, workspace_id="ws_b") == {
        "ok": False,
        "error": "session_workspace_mismatch",
    }
    assert remote_service.close_session("sid", workspace_id="ws_b") == {
        "ok": False,
        "error": "session_workspace_mismatch",
    }


def test_telnet_connect_allows_no_username_or_password(monkeypatch):
    from agent.modules.remote import core as remote_core

    sent: list[bytes] = []

    class FakeSocket:
        def __init__(self):
            self.timeout = None
            self.closed = False
            self.recv_chunks = [b"\r\n<H3C>"]

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, addr):
            self.addr = addr

        def sendall(self, data):
            sent.append(data)

        def recv(self, n):
            return self.recv_chunks.pop(0) if self.recv_chunks else b""

        def close(self):
            self.closed = True

        def fileno(self):
            return 0

    fake = FakeSocket()
    monkeypatch.setattr(remote_core.socket, "socket", lambda *a, **k: fake)
    monkeypatch.setattr(remote_core.select, "select", lambda r, w, x, timeout=0: (r if fake.recv_chunks else [], [], []))

    session = remote_core.telnet_connect(
        "sid_telnet_noauth",
        "192.0.2.61",
        23,
        username="",
        password="",
        vendor="h3c",
    )

    assert session.connected is True
    assert sent == [b"\r\n"]
    remote_core.disconnect("sid_telnet_noauth")


def test_telnet_connect_answers_login_prompts_only_when_credentials_exist(monkeypatch):
    from agent.modules.remote import core as remote_core

    sent: list[bytes] = []

    class FakeSocket:
        def __init__(self):
            self.recv_chunks = [b"Username:", b"Password:", b"\r\n<H3C>"]

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, addr):
            self.addr = addr

        def sendall(self, data):
            sent.append(data)

        def recv(self, n):
            return self.recv_chunks.pop(0) if self.recv_chunks else b""

        def close(self):
            pass

        def fileno(self):
            return 0

    fake = FakeSocket()
    monkeypatch.setattr(remote_core.socket, "socket", lambda *a, **k: fake)
    monkeypatch.setattr(remote_core.select, "select", lambda r, w, x, timeout=0: (r if fake.recv_chunks else [], [], []))

    session = remote_core.telnet_connect(
        "sid_telnet_auth",
        "192.0.2.62",
        23,
        username="admin",
        password="pw123",
        vendor="h3c",
    )

    assert session.connected is True
    assert sent == [b"\r\n", b"admin\r\n", b"pw123\r\n"]
    remote_core.disconnect("sid_telnet_auth")


def test_remote_exec_drains_stale_prompt_before_sending_command():
    from agent.modules.remote import core as remote_core

    class FakeVendor:
        vendor = "generic"

        def match_paging(self, text):
            return False

        def match_prompt(self, text):
            return text.rstrip().endswith("$")

    class FakeSession:
        def __init__(self):
            self.vendor = FakeVendor()
            self.log = []
            self.sent = False
            self.command_timeout = 5.0

        def recv(self, timeout=0):
            if not self.sent:
                self.sent = "drained"
                return b"stale prompt$ "
            if self.sent == "drained":
                return b""
            if self.sent == "sent":
                self.sent = "done"
                return b"show clock\n12:00:00\nrouter$ "
            return b""

        def send(self, data):
            assert data == b"show clock\n"
            self.sent = "sent"

    session = FakeSession()
    output = remote_core._exec_and_wait(session, "show clock")

    assert "12:00:00" in output
    assert "stale prompt" not in output


def test_remote_ws_keeps_xterm_enter_as_carriage_return():
    from backend.ws.remote_ws import _terminal_input_data

    assert _terminal_input_data("\r") == "\r"
    assert _terminal_input_data("display version\r") == "display version\r"


def test_remote_ws_validates_terminal_port():
    from backend.ws.remote_ws import _parse_port

    assert _parse_port(None) == 22
    assert _parse_port(23) == 23
    assert _parse_port("830") == 830
    for value in ("bad", 0, 65536):
        with pytest.raises(ValueError, match="invalid_port"):
            _parse_port(value)


def test_runner_trim_accepts_llm_message_objects():
    # v3.10: ``agent.runtime.runner`` (TurnRunner) was removed by
    # the SSOT Runtime hard cut (ff38bab). The SSOT Runtime conversation trimming
    # lives inside the budget controller, not in a public runner
    # module. We replace this test with a smoke check that
    # ``LLMMessage`` and the SSOT Runtime ``BudgetController`` agree on
    # the contract surface every consumer relies on.
    from agent.llm.schemas import LLMMessage
    from core.runtime_engine.budget_controller import BudgetController
    from core.runtime_engine.models import SSOTRuntimeConfig

    # Message shape round-trip.
    sys_msg = LLMMessage(role="system", content="system")
    assert sys_msg.role == "system"
    assert sys_msg.content == "system"

    # SSOT Runtime budget API exists and reports a clean state.
    cfg = SSOTRuntimeConfig()
    budget = BudgetController(cfg)
    res = budget.check_llm_call()
    assert hasattr(res, "ok")
    assert hasattr(res, "exceeded")
    # Default config must allow at least one planner call.
    assert res.ok, f"SSOTRuntimeConfig default budget rejected planner call: {res.exceeded}"


def test_memory_gate_rejects_generic_task_completion_noise():
    import shutil

    from storage.paths import workspace_root
    from storage.memory_governance import MemoryRecord, MemoryWriteGate

    workspace_id = "pytest_memory_noise"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    rec = MemoryRecord(
        workspace_id=workspace_id,
        memory_type="episodic_case",
        source="agent_suggestion",
        content="Task 't1' completed successfully",
        summary="Task 't1' completed successfully",
        confidence=0.9,
    )
    result = MemoryWriteGate().write(rec)

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "low_value_memory"

    if root.exists():
        shutil.rmtree(root)
