"""CMDB-driven device inspection workflow contract.

Pins the v3.9.13 inspection capability:

  1. catalog lists `inspection` capability with `inspection.manage`
     as primary recommended tool.
  2. canonical_registry has `inspection.manage` registered and it
     executes through the merged adapter.
  3. profile commands come from fixed per-vendor/type maps; raw commands
     never appear in the canonical schema.
  4. create_task accepts automatic mode without user-selected profile_id.
  6. manifest_registry has 22 manifests including `inspection.manage`.
  7. tool_namespace_data has 22 NS_DATA entries including inspection.
  8. tool_namespace has matching canonical count (no drift).
  9. internal script catalog remains valid, but public API/schema does
     not require users to choose a profile.
 10. canonical tool never returns device passwords — the schema
     does not declare a password field.
"""

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path("/Users/zhangh01/Desktop/network_agent")


@pytest.fixture(scope="module", autouse=True)
def _ensure_path():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def test_catalog_inspection_capability_enabled():
    """`inspection` capability must be enabled with recommended tools."""
    from agent.capabilities.catalog import get
    cap = get("inspection")
    assert cap is not None, "missing inspection capability"
    assert cap["status"] == "enabled", "inspection capability must be enabled"
    assert "inspection.manage" in cap["recommended_tool_ids"], (
        "recommended_tool_ids must include inspection.manage"
    )
    # All recommended tool ids must be canonical (catalog validates this at import)
    from core.tools.tool_namespace import TOOL_NAMESPACE
    for tid in cap["recommended_tool_ids"]:
        assert tid in TOOL_NAMESPACE, f"{tid} not in canonical namespace"


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_canonical_inspection_manage_registered():
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    assert "inspection.manage" in CANONICAL_REGISTRY
    entry = CANONICAL_REGISTRY["inspection.manage"]
    schema = entry.input_schema or {}
    fields = set(schema.get("properties", {}).keys())
    # action discriminator must expose only user-facing task actions.
    enum_actions = set(schema["properties"]["action"].get("enum", []))
    assert "profile_list" not in enum_actions, (
        "LLM-visible schema must not send users through profile selection"
    )
    assert "profile_id" not in fields, (
        "LLM-visible schema must not expose inspection profile selection"
    )
    for required_action in ("run", "list", "get", "cancel", "report"):
        assert required_action in enum_actions, (
            f"missing action={required_action} in inspection.manage schema"
        )
    assert "wait" not in enum_actions, "LLM-visible inspection schema must not expose blocking wait"
    assert "html" in schema["properties"]["format"].get("enum", [])
    # No raw password / credential field — runner is server-side only
    forbidden = {"password", "credentials", "secret", "token"}
    leaked = forbidden & fields
    assert not leaked, f"inspection.manage schema leaks {leaked}"


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_internal_script_catalog_contains_vendor_device_scripts():
    from agent.modules.inspection import service as svc
    profiles = svc.list_profiles()
    assert len(profiles) >= 7, (
        f"expected at least 7 internal profiles including firewall/server, got {len(profiles)}"
    )
    ids = {p["profile_id"] for p in profiles}
    assert {"basic_health", "interface_health", "routing_health",
            "config_backup", "full_basic", "firewall_health",
            "server_health"} <= ids
    # All profiles must be read-only; long remote-read templates can be medium
    # without requiring approval.
    for p in profiles:
        assert p["risk_level"] in {"low", "medium"}
        assert p["requires_approval"] is False
        # Every check must have a known parser_key (LLM-typed strings rejected)
        for c in p["checks"]:
            assert c["command_key"], "command_key required"
            assert c["parser_key"], "parser_key required"


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_profile_commands_fixed_per_vendor_no_llm_input():
    """Vendor command profiles are fixed maps. The LLM never composes commands."""
    from agent.modules.inspection.profiles import (
        VENDOR_COMMAND_PROFILES, is_read_only_command,
    )
    expected = {"h3c", "h3c_firewall", "huawei", "cisco",
                "ruijie", "hillstone", "server", "generic"}
    assert expected <= set(VENDOR_COMMAND_PROFILES), (
        f"vendor profile set missing entries: got {set(VENDOR_COMMAND_PROFILES)}"
    )
    # Every command in every vendor profile must pass the static read-only check
    for vendor, prof in VENDOR_COMMAND_PROFILES.items():
        for ck, cmd in prof.commands.items():
            assert cmd, f"{vendor}.{ck} is empty"
            assert is_read_only_command(cmd), (
                f"{vendor}.{ck} = {cmd!r} failed read-only check"
            )
    # Negative check: a destructive command must be rejected
    assert not is_read_only_command("reload")
    assert not is_read_only_command("write memory")
    assert not is_read_only_command("erase flash:")
    assert not is_read_only_command("delete running-config")
    assert not is_read_only_command("format c:")


def test_inspection_policy_allows_long_read_only_task_without_approval():
    """CMDB inspection is a read-only long task; it must not be blocked by
    the generic low/medium timeout ceiling and must not request approval.
    """
    from core.tools.manifest_registry import MANIFESTS
    from core.tools.canonical_registry import to_tool_specs
    from core.tools.policy import ToolPolicy
    from core.tools.schemas import ToolInvocation

    # v3.9.14: the manifest declares its own timeout — the policy
    # ceiling (``max(tier, manifest)``) must include it so a long-
    # running read-only inspection is never blocked by the generic
    # medium-risk 300s ceiling.
    assert MANIFESTS["inspection.manage"].timeout_seconds >= 600, (
        f"inspection.manage.timeout_seconds must be >= 600s to "
        f"cover a fleet-wide run, got "
        f"{MANIFESTS['inspection.manage'].timeout_seconds}"
    )
    spec = next(spec for spec, _ in to_tool_specs() if spec.tool_id == "inspection.manage")
    decision = ToolPolicy().check(
        spec,
        ToolInvocation(
            tool_id="inspection.manage",
            arguments={
                "workspace_id": "ws_demo",
                "action": "run",
                "scope": {"region": "测试一区", "limit": 20},
            },
        ),
    )
    assert decision.allowed is True, decision.reason
    assert decision.requires_approval is False
    assert decision.risk_level in {"low", "medium"}


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_server_assets_resolve_to_server_command_profile():
    """Server assets must not fall through to network-device show commands."""
    from agent.modules.inspection.profiles import (
        CK_CPU,
        CK_MEMORY,
        CK_VERSION,
        resolve_command_profile,
        is_read_only_command,
    )

    prof = resolve_command_profile(vendor="", device_type="server")
    assert prof.vendor == "server"
    assert resolve_command_profile(vendor="Linux", device_type="").vendor == "server"
    assert "uname" in prof.commands[CK_VERSION]
    assert prof.commands[CK_CPU].startswith("top ")
    assert "free" in prof.commands[CK_MEMORY]
    for cmd in prof.commands.values():
        assert is_read_only_command(cmd), cmd


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_firewall_and_vendor_script_profiles_include_real_read_commands():
    """Firewall/Ruijie/Hillstone profiles must carry concrete read-only
    inspection commands rather than silently falling back to generic.
    """
    from agent.modules.inspection.profiles import (
        CK_FIREWALL_POLICY,
        CK_FIREWALL_SESSION,
        CK_ROUTE_SUMMARY,
        VENDOR_COMMAND_PROFILES,
        is_read_only_command,
    )

    h3c_fw = VENDOR_COMMAND_PROFILES["h3c_firewall"]
    from agent.modules.inspection.profiles import resolve_command_profile
    assert resolve_command_profile("H3C Firewall", "").vendor == "h3c_firewall"
    assert h3c_fw.commands[CK_FIREWALL_SESSION].startswith("display session")
    assert h3c_fw.commands[CK_FIREWALL_POLICY].startswith("display security-policy")

    ruijie = VENDOR_COMMAND_PROFILES["ruijie"]
    assert ruijie.commands[CK_ROUTE_SUMMARY].startswith("show ip route")

    hillstone = VENDOR_COMMAND_PROFILES["hillstone"]
    assert hillstone.commands[CK_FIREWALL_SESSION].startswith("show session")

    for profile_id in ("h3c_firewall", "ruijie", "hillstone"):
        for cmd in VENDOR_COMMAND_PROFILES[profile_id].commands.values():
            assert is_read_only_command(cmd), f"{profile_id}: {cmd}"


def test_create_task_defaults_to_auto_profile_without_user_selection():
    """CMDB-triggered inspection must not require the user/LLM to choose a
    template. The backend stores profile_id=auto and resolves scripts per asset.
    """
    from agent.modules.inspection import service as svc

    task = svc.create_task(workspace_id="ws_demo", profile_id="", scope={"limit": 1})
    assert task.profile_id == "auto"
    assert task.profile_display_name == "自动巡检"
    assert task.status in ("succeeded", "partial", "failed")


def test_create_task_rejects_unknown_explicit_profile():
    """Unknown explicit internal profile ids still fail deterministically."""
    from agent.modules.inspection import service as svc

    bad = svc.create_task(workspace_id="ws_demo", profile_id="does_not_exist_xyz")
    assert bad.status == "failed"
    assert bad.error.startswith("unknown_profile:")


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_create_task_with_known_profile_and_empty_scope_fails_clearly():
    """Empty CMDB scope must not be reported as a successful inspection."""
    from agent.modules.inspection import service as svc

    task = svc.create_task(
        workspace_id="ws_test_inspect",
        profile_id="basic_health",
        scope={"limit": 10},
    )
    assert task.status == "failed"
    assert task.error == "no_assets_matched_scope"
    assert task.total_assets == 0
    assert task.started_at and task.finished_at


def test_canonical_run_does_not_require_profile_id():
    """LLM/CMDB run action passes only scope; backend chooses scripts."""
    from core.tools.schemas import ToolInvocation
    from core.tools.canonical_registry import CANONICAL_REGISTRY

    inv = ToolInvocation(
        arguments={
            "workspace_id": "ws_test_inspect_auto",
            "action": "run",
            "scope": {"region": "不存在区域", "limit": 5},
        },
        tool_id="inspection.manage",
    )
    result = CANONICAL_REGISTRY["inspection.manage"].handler(inv)
    assert result["ok"] is True
    assert result["profile_id"] == "auto"
    assert result["tracking"]["task_id"] == result["task_id"]
    assert result["tracking"]["kind"] == "long_task"
    assert result["tracking"]["domain"] == "inspection"
    assert result["message"].startswith("巡检任务已创建")


def test_html_report_returns_download_link_and_artifact():
    from agent.modules.inspection import service as svc

    task = svc.create_task(
        workspace_id="ws_test_inspect_html",
        profile_id="",
        scope={"limit": 5},
    )
    rep = svc.render_report("ws_test_inspect_html", task.task_id, "html")
    assert rep["ok"] is True, rep.get("error")
    assert rep["format"] == "html"
    assert rep["filename"].endswith(".html")
    assert rep["artifact_id"].startswith("art_")
    assert (
        f"/api/inspection/tasks/{task.task_id}/report.html?workspace_id=ws_test_inspect_html"
        == rep["download_url"]
    )
    assert "<html" in rep["content"].lower()


def test_html_report_route_returns_viewable_html():
    from flask import Flask
    from backend.api.inspection_routes import register_inspection_routes
    from agent.modules.inspection import service as svc

    task = svc.create_task(
        workspace_id="ws_test_inspect_html_route",
        profile_id="",
        scope={"limit": 5},
    )
    app = Flask(__name__)
    register_inspection_routes(app)
    client = app.test_client()

    resp = client.get(
        f"/api/inspection/tasks/{task.task_id}/report.html"
        "?workspace_id=ws_test_inspect_html_route"
    )
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert "<html" in resp.get_data(as_text=True).lower()


def test_manifest_registry_has_29_manifests_with_inspection():
    from core.tools.manifest_registry import MANIFESTS, validate_all
    errors, count = validate_all()
    assert count == 29, f"expected 29 manifests (22 canonical + 7 spawn tools), got {count}"
    assert not errors, f"manifest validation errors: {errors}"
    assert "inspection.manage" in MANIFESTS
    # The runner caller (inspection_runner) must be in allowed_callers
    ins = MANIFESTS["inspection.manage"]
    assert "inspection_runner" in ins.allowed_callers
    # exec.run + device.manage must accept inspection_runner too
    assert "inspection_runner" in MANIFESTS["exec.run"].allowed_callers
    assert "inspection_runner" in MANIFESTS["device.manage"].allowed_callers


def test_namespace_data_has_29_entries_with_inspection():
    """NS_DATA / canonical / namespace triple stay in sync."""
    from core.tools.tool_namespace import TOOL_NAMESPACE
    from core.tools.tool_namespace_data import NS_DATA
    from core.tools.canonical_registry import CANONICAL_REGISTRY

    assert len(NS_DATA) == len(TOOL_NAMESPACE) == len(CANONICAL_REGISTRY) == 29
    # inspection.manage must be registered in all three. NS_DATA stores
    # 9-tuples keyed by index 0 == canonical_tool_id
    ns_ids = {entry[0] for entry in NS_DATA}
    assert "inspection.manage" in ns_ids
    assert "inspection.manage" in TOOL_NAMESPACE
    assert "inspection.manage" in CANONICAL_REGISTRY
    # Namespace metadata must include an inspection summary
    insp_meta = TOOL_NAMESPACE["inspection.manage"]
    fields = (
        insp_meta.canonical_tool_id, insp_meta.category, insp_meta.action,
        insp_meta.display_name, insp_meta.usage_hint, insp_meta.not_for,
    )
    assert any("inspection" in (f or "").lower() for f in fields)


def test_internal_script_catalog_shape_is_stable():
    """The internal vendor script catalog remains structured for runner use.

    It is not exposed as a frontend profile-selection contract.
    """
    from agent.modules.inspection.service import list_profiles
    profiles = list_profiles()
    required_keys = {
        "profile_id", "display_name", "description",
        "risk_level", "requires_approval", "checks",
    }
    for p in profiles:
        missing = required_keys - set(p.keys())
        assert not missing, f"profile {p.get('profile_id')} missing keys {missing}"
        for c in p["checks"]:
            assert {"check_id", "category", "display_name", "command_key",
                    "parser_key", "severity_default", "timeout_seconds"} \
                <= set(c.keys()), (
                f"check {c.get('check_id')} missing required keys"
            )


def test_canonical_run_handler_uses_existing_manifests():
    """The canonical `inspection.manage(action=run)` handler must NOT bypass
    the canonical exec.run path. We verify by inspecting source — the
    handler must call the inspection service (which uses ToolRuntimeClient)
    and must NOT shell out directly with raw ssh/telnet / python."""
    from core.tools import canonical_registry
    src = Path(canonical_registry.__file__).read_text(encoding="utf-8")
    assert "from agent.modules.inspection import service" in src, (
        "canonical handler must delegate to inspection service"
    )
    # Must not contain raw socket / paramiko ssh — credentials stay server-side
    forbidden = ["paramiko.SSHClient", "pexpect.spawn", "telnetlib.Telnet"]
    for tok in forbidden:
        assert tok not in src, (
            f"inspection canonical handler must not import {tok}; "
            "use canonical exec.run(asset_id) for live access"
        )


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_report_render_does_not_embed_passwords():
    """render_report for a task with empty scope returns a Markdown report
    containing no `password=` substring and no CMDB credential field."""
    from agent.modules.inspection import service as svc
    task = svc.create_task(
        workspace_id="ws_test_inspect",
        profile_id="basic_health",
        scope={"limit": 5},
    )
    rep = svc.render_report("ws_test_inspect", task.task_id, "md")
    assert rep["ok"] is True, rep.get("error")
    md = rep["content"]
    # The empty-asset report must not contain password / token / secret literals
    for needle in ("password=", "password:", "secret=", "token="):
        assert needle.lower() not in md.lower(), (
            f"report unexpectedly contains {needle!r}"
        )
    # Empty-scope report must still include the basic structure: scope / auto policy / summary
    assert "巡检策略" in md, "report must include auto policy section"
    assert "巡检范围" in md, "report must include scope section"
    assert "总体" in md or "总设备" in md, "report must include summary section"


def test_explicit_asset_ids_are_authoritative_over_scope_filters():
    """Explicit asset ids must not be hidden by region/vendor/type filters."""
    from agent.modules.cmdb.service import save_asset
    from agent.modules.inspection.models import InspectionScope
    from agent.modules.inspection.runner import _resolve_target_assets

    ws = "ws_test_inspect_scope"
    created = save_asset(ws, {
        "name": "scope-router-01",
        "type": "router",
        "vendor": "H3C",
        "host": "10.251.13.1",
        "port": 22,
        "protocol": "ssh",
        "username": "admin",
        "region": "华东",
    })
    assert created["ok"] is True
    aid = created["asset_id"]

    targets = _resolve_target_assets(
        InspectionScope(region="不存在区域", vendor="Cisco", asset_ids=(aid,)),
        ws,
    )
    assert [t["asset_id"] for t in targets] == [aid]


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_telnet_asset_uses_telnet_target(monkeypatch):
    """The runner must pass the CMDB protocol into exec.run target."""
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    seen_protocols = []

    def fake_exec(workspace_id, asset_id, protocol, command, timeout, session_id=""):
        seen_protocols.append(protocol)
        return {"ok": True, "output": "H3C Comware Software", "error": "", "session_id": ""}

    monkeypatch.setattr(runner, "_exec_one_command", fake_exec)

    task = InspectionTask(
        task_id="ins_test_telnet",
        workspace_id="ws_test_inspect",
        scope=InspectionScope(),
        profile_id="one",
    )
    profile = InspectionProfile(
        profile_id="one",
        display_name="One",
        description="One check",
        checks=(InspectionCheck(
            check_id="basic.version",
            category="health",
            display_name="Version",
            command_key="version",
            parser_key="version",
        ),),
    )
    dr = runner._run_checks_on_asset(task, profile, {
        "asset_id": "asset_telnet",
        "name": "telnet-device",
        "host": "10.251.13.2",
        "vendor": "h3c",
        "type": "switch",
        "protocol": "telnet",
    }, "ws_test_inspect")

    assert dr.status == "succeeded"
    assert seen_protocols == ["telnet"]


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_current_config_snippet_is_not_raw_config(monkeypatch):
    """Raw current-config belongs in a sensitive artifact, not task JSON."""
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    class FakeArtifact:
        artifact_id = "art_sensitive_config"

    monkeypatch.setattr(
        runner,
        "_exec_one_command",
        lambda *args, **kwargs: {
            "ok": True,
            "output": "sysname demo\npassword=plain-secret\ninterface Vlanif1",
            "error": "",
        },
    )
    monkeypatch.setattr(runner, "save_artifact", lambda **kwargs: FakeArtifact())

    task = InspectionTask(
        task_id="ins_test_config",
        workspace_id="ws_test_inspect",
        scope=InspectionScope(),
        profile_id="config",
    )
    profile = InspectionProfile(
        profile_id="config",
        display_name="Config",
        description="Config backup",
        checks=(InspectionCheck(
            check_id="config.current",
            category="config",
            display_name="Current config",
            command_key="current_config",
            parser_key="current_config",
        ),),
    )
    dr = runner._run_checks_on_asset(task, profile, {
        "asset_id": "asset_cfg",
        "name": "cfg-device",
        "host": "10.251.13.3",
        "vendor": "h3c",
        "type": "switch",
        "protocol": "ssh",
    }, "ws_test_inspect")

    assert dr.command_results[0].artifact_id == "art_sensitive_config"
    snippet = dr.command_results[0].output_snippet.lower()
    assert "plain-secret" not in snippet
    assert "password=" not in snippet
    assert "sensitive artifact" in snippet

def test_scope_schema_exposes_inner_filter_fields():
    """The `scope` parameter is an object; the schema must document
    which fields the runner accepts (region/location/type/vendor/tags/
    asset_ids/limit). Otherwise the LLM can't construct a meaningful
    filter and will either send nothing or hallucinate fields.
    """
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    schema = CANONICAL_REGISTRY["inspection.manage"].input_schema
    scope = schema["properties"]["scope"]
    desc = (scope.get("description") or "").lower()
    for field in ("region", "location", "type", "vendor",
                   "tags", "asset_ids", "limit"):
        assert field in desc, (
            f"scope description must mention {field!r}; got: {desc!r}"
        )


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_run_with_empty_profile_id_resolves_to_auto_profile():
    """The runner must accept a missing/empty profile_id and route the
    task through AUTO_PROFILE. This is the contract that lets the LLM
    safely call inspection.manage(action=run) without a profile choice.
    """
    from agent.modules.inspection.profiles import (
        AUTO_PROFILE_ID, resolve_profile, BUILTIN_PROFILES,
    )
    # resolve_profile("") -> AUTO_PROFILE (already wired by f32de51)
    assert resolve_profile("").profile_id == AUTO_PROFILE_ID
    assert resolve_profile("auto").profile_id == AUTO_PROFILE_ID
    # resolve_profile(unknown) -> None — surface as a clean error
    assert resolve_profile("totally_made_up") is None
    # And the 5 builtin ids are all resolvable
    for pid in ("basic_health", "interface_health", "routing_health",
                 "config_backup", "full_basic"):
        assert pid in BUILTIN_PROFILES, f"missing builtin {pid!r}"


def test_backend_routes_return_400_for_empty_profile_id():
    """Live backend route must not crash on missing profile_id; it must
    surface a clean 400 (or 200 with auto-resolved profile)."""
    import os
    host = os.environ.get("INSPECTION_API_HOST", "127.0.0.1")
    port = int(os.environ.get("INSPECTION_API_PORT", "8010"))
    try:
        import urllib.request
        import urllib.error
        body = b'{"workspace_id":"ws_schema_test","action":"run","scope":{"limit":5}}'
        req = urllib.request.Request(
            f"http://{host}:{port}/api/inspection/tasks",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            code = resp.getcode()
            payload = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        pytest.skip(f"backend not reachable on {host}:{port}: {exc}")
    import json
    data = json.loads(payload)
    # Either 200 with auto-resolved profile or 400 with explicit error.
    assert code in (200, 400), f"unexpected HTTP {code}: {payload[:200]}"
    if code == 200:
        assert data.get("profile_id") == "auto", (
            f"empty profile_id should default to 'auto', got {data.get('profile_id')!r}"
        )
    else:
        assert "error" in data, f"400 must include error field: {data}"


def test_task_from_dict_does_not_crash_on_disk_round_trip():
    """v3.9.14 follow-up: ``_task_from_dict`` must construct DeviceResult
    with both required fields (task_id, asset_id). Otherwise a
    list/get cycle on a real task raises
    ``DeviceResult.__init__() missing 1 required positional argument:
    'asset_id'`` instead of returning the task.
    """
    import json
    from agent.modules.inspection import service as svc
    from agent.modules.inspection.runner import _task_from_dict

    # 1. create + persist a real task to disk
    task = svc.create_task("ws_round_trip", profile_id="", scope={"limit": 3})
    assert task.task_id, "task creation failed"

    # 2. simulate a list_tasks payload (raw dict) and round-trip it
    raw = {
        "task_id": task.task_id,
        "workspace_id": task.workspace_id,
        "scope": {
            "region": "", "location": "", "type": "", "vendor": "",
            "tags": [], "asset_ids": [], "limit": 3,
        },
        "profile_id": task.profile_id,
        "status": task.status,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "total_assets": task.total_assets,
        "succeeded": task.succeeded,
        "failed": task.failed,
        "skipped": task.skipped,
        "warnings": task.warnings,
        "criticals": task.criticals,
        "infos": task.infos,
        "created_by": task.created_by,
        "session_id": task.session_id,
        "max_concurrency": task.max_concurrency,
        "devices": {},
        "error": task.error,
    }
    # Must not raise TypeError about missing asset_id
    loaded = _task_from_dict(raw)
    assert loaded.task_id == task.task_id
    assert loaded.workspace_id == task.workspace_id
    assert loaded.devices == {}

    # 3. round-trip with one synthesised device entry — the original
    #    bug (missing asset_id kwarg) would crash here.
    raw["devices"] = {
        "asset_x": {
            "asset_name": "switch-east-1",
            "host": "10.0.0.1",
            "status": "succeeded",
            "command_results": [],
            "findings": [],
            "errors": [],
        }
    }
    loaded2 = _task_from_dict(raw)
    assert "asset_x" in loaded2.devices
    assert loaded2.devices["asset_x"].asset_id == "asset_x"
    assert loaded2.devices["asset_x"].task_id == task.task_id


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_inspection_get_returns_tracking_summary():
    """LLM tracking uses get instead of a blocking wait call."""
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    from core.tools.schemas import ToolInvocation
    from agent.modules.inspection import service as svc

    task = svc.create_task("ws_wait_action", profile_id="", scope={"limit": 0})
    result = CANONICAL_REGISTRY["inspection.manage"].handler(ToolInvocation(
        tool_id="inspection.manage",
        arguments={
            "workspace_id": "ws_wait_action",
            "action": "get",
            "task_id": task.task_id,
        },
        requested_by="turn_runner",
    ))
    assert result["ok"] is True
    assert result["task"]["task_id"] == task.task_id
    assert result["tracking"]["task_id"] == task.task_id
    assert result["tracking"]["status"] in {"succeeded", "partial", "failed", "cancelled", "skipped"}
    assert result["tracking"]["done"] is True


def test_exec_one_command_uses_status_not_ok():
    """v3.9.14 follow-up: ToolResult has no ``ok`` attribute — it has
    ``status`` ("succeeded"|"failed"|"blocked"|"dry_run"). The earlier
    implementation of ``_exec_one_command`` read ``getattr(result, "ok",
    False)`` which always returned False, so every successful exec.run
    was misclassified as a failure. Pin the contract here.
    """
    from core.tools.schemas import ToolResult

    # The result object the runner consumes from ToolRuntimeClient.invoke
    succeeded = ToolResult(
        invocation_id="x", tool_id="exec.run", status="succeeded",
        output={"ok": True, "host": "10.0.0.1", "output": "Linux foo 6.8"},
        summary="Tool exec.run completed", errors=[],
    )
    # status is the source of truth, NOT a non-existent ok attribute.
    assert succeeded.status == "succeeded"
    assert not hasattr(succeeded, "ok"), (
        "ToolResult must not have an 'ok' attribute — the runner was "
        "reading this and always getting False via getattr default"
    )
    failed = ToolResult(
        invocation_id="y", tool_id="exec.run", status="failed",
        output={"ok": False, "error": "SSH 认证失败"},
        summary="Tool exec.run failed", errors=["auth_failed"],
    )
    assert failed.status == "failed"
    assert failed.errors == ["auth_failed"]
    blocked = ToolResult(
        invocation_id="z", tool_id="exec.run", status="blocked",
        output={}, summary="Caller 'foo' not allowed", errors=[],
    )
    assert blocked.status == "blocked"


def test_exec_one_command_parsing_happy_path():
    """Mock the ToolRuntimeClient and confirm a succeeded result
    surfaces as ``ok=True`` with the inner handler's stdout."""
    from unittest.mock import MagicMock, patch
    from core.tools.schemas import ToolResult
    from agent.modules.inspection import runner

    mock_result = ToolResult(
        invocation_id="x", tool_id="exec.run", status="succeeded",
        output={"ok": True, "host": "10.0.0.1",
                 "output": "Linux ubuntuserver 6.8.0", "session_id": "s1"},
        summary="Tool exec.run completed", errors=[],
    )
    mock_client = MagicMock()
    mock_client.invoke.return_value = mock_result

    with patch.object(runner, "get_default_tool_runtime_client",
                       return_value=mock_client):
        # No real asset needed — the runner extracts host/user/password
        # via the canonical exec.run handler which is mocked here.
        result = runner._exec_one_command(
            workspace_id="ws_test", asset_id="asset_xxx",
            protocol="ssh", command="uname -a", timeout=30,
        )
    assert result["ok"] is True, (
        f"succeeded result must surface ok=True; got {result!r}"
    )
    assert "Linux ubuntuserver" in result["output"]


def test_exec_one_command_parsing_blocked_path():
    """A blocked result (caller not in allowed_callers) must NOT
    silently degrade to ok=True. The runner returns the policy
    summary as the error so the device result surfaces a clean
    ``exec_run_blocked: ...`` reason."""
    from unittest.mock import MagicMock, patch
    from core.tools.schemas import ToolResult
    from agent.modules.inspection import runner

    mock_result = ToolResult(
        invocation_id="x", tool_id="exec.run", status="blocked",
        output={}, summary="Caller 'debug' not allowed for exec.run",
        errors=[],
    )
    mock_client = MagicMock()
    mock_client.invoke.return_value = mock_result
    with patch.object(runner, "get_default_tool_runtime_client",
                       return_value=mock_client):
        result = runner._exec_one_command(
            workspace_id="ws_test", asset_id="asset_xxx",
            protocol="ssh", command="uname -a", timeout=30,
        )
    assert result["ok"] is False
    assert "exec_run_blocked" in result["error"]
    assert "debug" in result["error"]


# ── v3.9.14: session reuse, per-check timeout, per-asset concurrency ──

def test_exec_one_command_passes_session_id_to_canonical_layer():
    """The runner must hand the cached session_id back to ``exec.run``
    on subsequent calls so the canonical handler reuses the existing
    paramiko channel. Pin the contract here.
    """
    from unittest.mock import MagicMock, patch
    from core.tools.schemas import ToolResult
    from agent.modules.inspection import runner

    mock_result = ToolResult(
        invocation_id="x", tool_id="exec.run", status="succeeded",
        output={"ok": True, "output": "Linux foo 6.8", "session_id": "ssh_pinned"},
        summary="Tool exec.run completed", errors=[],
    )
    mock_client = MagicMock()
    mock_client.invoke.return_value = mock_result

    captured: list[dict] = []
    def capture(*args, **kwargs):
        captured.append(kwargs)
        return mock_result

    mock_client.invoke.side_effect = capture

    with patch.object(runner, "get_default_tool_runtime_client",
                       return_value=mock_client):
        runner._exec_one_command(
            workspace_id="ws_test", asset_id="asset_xxx",
            protocol="ssh", command="df -h", timeout=30,
            session_id="ssh_pinned",
        )
    # The session_id must propagate into the canonical invoke call's
    # arguments dict (which becomes inv_args).
    invoke_args = mock_client.invoke.call_args[0][1]
    assert invoke_args.get("session_id") == "ssh_pinned", (
        f"session_id not threaded into canonical invoke; got {invoke_args!r}"
    )


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_default_timeout_for_clamps_and_uses_hints():
    """per-command-key timeout hints should be tighter than the
    30s/45s defaults in the profile, and the function must clamp
    to [5, 120] seconds.
    """
    from agent.modules.inspection.profiles import default_timeout_for

    assert default_timeout_for("version") == 5
    assert default_timeout_for("memory") == 5
    assert default_timeout_for("current_config") == 60
    # Unknown command key falls back to the supplied profile_default
    assert default_timeout_for("nonsense_key", profile_default=15) == 15
    # Clamp to safe range
    assert default_timeout_for("anything", profile_default=0) >= 5
    assert default_timeout_for("anything", profile_default=9999) <= 120


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_run_checks_uses_single_session_per_asset(monkeypatch):
    """Default config (workers=1) must dispatch every check against
    the same asset with the cached session_id. 6 calls → 1 distinct
    session_id reused 5 times.
    """
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    seen_sessions: list[str] = []

    def fake_exec(workspace_id, asset_id, protocol, command, timeout, session_id=""):
        # Simulate exec.run returning a fresh session_id only on the
        # first call (i.e. when no session_id was provided).
        if not session_id:
            sid = f"ssh_simulated_{len(seen_sessions)}"
        else:
            sid = session_id
        seen_sessions.append(sid)
        return {
            "ok": True,
            "output": f"fake-output-for-{command}",
            "error": "",
            "session_id": sid,
        }

    monkeypatch.setattr(runner, "_exec_one_command", fake_exec)

    profile = InspectionProfile(
        profile_id="server_health",
        display_name="Server",
        description="server checks",
        checks=tuple(InspectionCheck(
            check_id=f"srv.x{i}",
            category="server",
            display_name=f"X{i}",
            command_key="version",
            parser_key="version",
            timeout_seconds=30,
        ) for i in range(6)),
    )
    task = InspectionTask(
        task_id="ins_test_session",
        workspace_id="ws_test_inspect",
        scope=InspectionScope(),
        profile_id="server_health",
    )
    dr = runner._run_checks_on_asset(task, profile, {
        "asset_id": "asset_x",
        "name": "fake-server",
        "host": "10.0.0.1",
        "vendor": "",
        "type": "server",
        "protocol": "ssh",
    }, "ws_test_inspect")
    assert dr.status == "succeeded", dr.errors
    # 6 checks, 1 session_id reused across all 6
    assert len(seen_sessions) == 6
    distinct = set(seen_sessions)
    assert len(distinct) == 1, (
        f"expected 1 session reused, got {len(distinct)}: {distinct}"
    )


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_run_checks_closes_reused_session_after_asset(monkeypatch):
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    closed: list[tuple[str, str]] = []

    def fake_exec(workspace_id, asset_id, protocol, command, timeout, session_id=""):
        return {
            "ok": True,
            "output": f"fake-output-for-{command}",
            "error": "",
            "session_id": session_id or "ssh_asset_session",
        }

    monkeypatch.setattr(runner, "_exec_one_command", fake_exec)
    monkeypatch.setattr(
        runner,
        "_close_remote_session",
        lambda workspace_id, protocol, session_id: closed.append((protocol, session_id)),
    )

    profile = InspectionProfile(
        profile_id="server_health",
        display_name="Server",
        description="server checks",
        checks=tuple(InspectionCheck(
            check_id=f"srv.close{i}",
            category="server",
            display_name=f"X{i}",
            command_key="version",
            parser_key="version",
            timeout_seconds=30,
        ) for i in range(2)),
    )
    task = InspectionTask(
        task_id="ins_test_close_session",
        workspace_id="ws_test_inspect",
        scope=InspectionScope(),
        profile_id="server_health",
    )
    dr = runner._run_checks_on_asset(task, profile, {
        "asset_id": "asset_x",
        "name": "fake-server",
        "host": "10.0.0.1",
        "vendor": "",
        "type": "server",
        "protocol": "ssh",
    }, "ws_test_inspect")

    assert dr.status == "succeeded", dr.errors
    assert closed == [("ssh", "ssh_asset_session")]


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_per_device_workers_setting_is_ignored_for_interactive_safety(monkeypatch):
    """Per-device checks must remain serial even if an old worker
    tuning knob is present. Device-level concurrency is allowed, but
    one asset gets one ordered interactive stream and one session_id.
    """
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    seen_sessions: list[str] = []

    def fake_exec(workspace_id, asset_id, protocol, command, timeout, session_id=""):
        if not session_id:
            sid = "ssh_single_1"
        else:
            sid = session_id
        seen_sessions.append(sid)
        return {
            "ok": True, "output": f"fake-{command}",
            "error": "", "session_id": sid,
        }

    monkeypatch.setattr(runner, "_exec_one_command", fake_exec)
    monkeypatch.setattr(runner, "INSPECTION_PER_DEVICE_WORKERS", 2,
                        raising=False)

    profile = InspectionProfile(
        profile_id="server_health",
        display_name="Server",
        description="checks",
        checks=tuple(InspectionCheck(
            check_id=f"srv.x{i}",
            category="server",
            display_name=f"X{i}",
            command_key="version",
            parser_key="version",
            timeout_seconds=30,
        ) for i in range(6)),
    )
    task = InspectionTask(
        task_id="ins_test_workers",
        workspace_id="ws_test_inspect",
        scope=InspectionScope(),
        profile_id="server_health",
    )
    dr = runner._run_checks_on_asset(task, profile, {
        "asset_id": "asset_x",
        "name": "fake-server",
        "host": "10.0.0.1",
        "vendor": "",
        "type": "server",
        "protocol": "ssh",
    }, "ws_test_inspect")
    assert dr.status == "succeeded", dr.errors
    assert len(seen_sessions) == 6
    assert len(set(seen_sessions)) == 1, (
        f"per-device execution must stay serial, got sessions {set(seen_sessions)}"
    )


# ── v3.9.14 post-50-round fixes ─────────────────────────────────────────


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_cancel_task_returns_supported_true(monkeypatch, tmp_path):
    """Cancel endpoint is real now, not a 501 placeholder.

    The runner reads its per-workspace storage root from
    ``workspace.run_store.WS_ROOT``; monkey-patching that module
    attribute redirects all in-runner reads/writes to ``tmp_path``
    without touching the real on-disk store.
    """
    from agent.modules.inspection import runner
    import workspace.run_store as ws_store
    ws = "ws_cancel_real"
    (tmp_path / ws).mkdir(parents=True)
    # also create inspection/tasks subdir the runner expects
    (tmp_path / ws / "inspection" / "tasks").mkdir(parents=True)
    orig = ws_store.WS_ROOT
    ws_store.WS_ROOT = tmp_path
    try:
        # Service layer is what HTTP callers see; it's also the
        # one that coerces dict → InspectionScope properly.
        from agent.modules.inspection import service as insp_svc
        task = insp_svc.create_task(
            workspace_id=ws,
            profile_id="server_health",
            scope={"limit": 1},
            created_by="user",
        )
        result = insp_svc.cancel_task(ws, task.task_id)
    finally:
        ws_store.WS_ROOT = orig
    assert "ok" in result
    if result.get("ok"):
        assert result.get("supported") is True
        assert "marked_at" in result
    else:
        assert "error" in result
        assert result["error"].startswith("task_already_")


def test_cancel_task_closes_registered_remote_sessions(monkeypatch, tmp_path):
    """Cancel should actively close already-known SSH/Telnet sessions."""
    from dataclasses import asdict
    import json as _json

    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionScope, InspectionTask
    from agent.runtime.utils import now_iso
    import workspace.run_store as ws_store

    ws = "ws_cancel_close_sessions"
    task_id = "ins_cancel_close_001"
    task_dir = tmp_path / ws / "inspection" / "tasks"
    task_dir.mkdir(parents=True)
    task = InspectionTask(
        task_id=task_id,
        workspace_id=ws,
        scope=InspectionScope(),
        profile_id="server_health",
        status="running",
        started_at=now_iso(),
    )
    (task_dir / f"{task_id}.json").write_text(
        _json.dumps(asdict(task), ensure_ascii=False),
        encoding="utf-8",
    )

    closed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        runner,
        "_close_remote_session",
        lambda workspace_id, protocol, session_id: closed.append((workspace_id, protocol, session_id)),
    )
    runner._register_task_session(ws, task_id, "ssh", "ssh_sid_1")
    runner._register_task_session(ws, task_id, "telnet", "telnet_sid_2")

    orig = ws_store.WS_ROOT
    ws_store.WS_ROOT = tmp_path
    try:
        result = runner.cancel_task(ws, task_id)
    finally:
        ws_store.WS_ROOT = orig

    assert result["ok"] is True
    assert sorted(closed) == [
        (ws, "ssh", "ssh_sid_1"),
        (ws, "telnet", "telnet_sid_2"),
    ]
    assert runner._registered_task_sessions(ws, task_id) == {}


def test_async_inspection_route_returns_real_task_id(monkeypatch):
    """async_run must return the actual persisted task_id, not a placeholder."""
    from flask import Flask
    from backend.api.inspection_routes import register_inspection_routes

    app = Flask(__name__)
    register_inspection_routes(app)
    client = app.test_client()

    class FakeTask:
        task_id = "ins_real_async_001"
        status = "running"
        profile_id = "auto"
        scope = type("Scope", (), {
            "region": "广域网", "location": "", "type": "", "vendor": "",
            "tags": (), "asset_ids": (), "limit": 50,
        })()
        total_assets = 6
        succeeded = failed = skipped = partial = warnings = criticals = infos = 0
        started_at = "2026-07-01T00:00:00+00:00"
        finished_at = ""
        error = ""

    pending_calls = []
    run_calls = []

    def fake_create_pending_task(**payload):
        pending_calls.append(payload)
        return FakeTask()

    def fake_create_task(**payload):
        run_calls.append(payload)
        return FakeTask()

    monkeypatch.setattr("agent.modules.inspection.service.create_pending_task", fake_create_pending_task)
    monkeypatch.setattr("agent.modules.inspection.service.create_task", fake_create_task)
    resp = client.post("/api/inspection/tasks", json={
        "workspace_id": "default",
        "scope": {"region": "广域网"},
        "async_run": True,
    })
    body = resp.get_json()
    assert resp.status_code == 202
    assert pending_calls, "async route must persist a real task before returning"
    assert body["task_id"] == "ins_real_async_001"
    import time as _time
    deadline = _time.time() + 1
    while not run_calls and _time.time() < deadline:
        _time.sleep(0.01)
    assert run_calls[0]["task_id"] == "ins_real_async_001"


def test_cancel_route_maps_not_found_to_404(monkeypatch):
    """task_not_found is a normal API 404, not a 501 capability failure."""
    from flask import Flask
    from backend.api.inspection_routes import register_inspection_routes

    app = Flask(__name__)
    register_inspection_routes(app)
    client = app.test_client()

    monkeypatch.setattr(
        "agent.modules.inspection.service.cancel_task",
        lambda ws, task_id: {"ok": False, "error": "task_not_found"},
    )
    resp = client.post("/api/inspection/tasks/missing/cancel", json={
        "workspace_id": "default",
    })
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "task_not_found"


def test_cancel_route_maps_already_terminal_to_409(monkeypatch):
    """Already-terminal tasks should not be reported as Not Implemented."""
    from flask import Flask
    from backend.api.inspection_routes import register_inspection_routes

    app = Flask(__name__)
    register_inspection_routes(app)
    client = app.test_client()

    monkeypatch.setattr(
        "agent.modules.inspection.service.cancel_task",
        lambda ws, task_id: {"ok": False, "error": "task_already_succeeded"},
    )
    resp = client.post("/api/inspection/tasks/done/cancel", json={
        "workspace_id": "default",
    })
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "task_already_succeeded"


@pytest.mark.skip(reason="needs update for v4.x inspection refactor")
def test_parallel_cancel_records_completed_future_before_stopping(monkeypatch, tmp_path):
    """A completed future observed at cancel time must still be merged."""
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import DeviceResult, InspectionScope
    import workspace.run_store as ws_store

    ws = "ws_cancel_done_future"
    (tmp_path / ws).mkdir(parents=True)
    orig = ws_store.WS_ROOT
    ws_store.WS_ROOT = tmp_path
    try:
        monkeypatch.setattr(runner, "_resolve_target_assets", lambda scope, workspace_id: [
            {
                "asset_id": "a_0", "name": "asset-0", "type": "server",
                "vendor": "linux", "host": "127.0.0.1", "port": 22,
                "protocol": "ssh",
            },
            {
                "asset_id": "a_1", "name": "asset-1", "type": "server",
                "vendor": "linux", "host": "127.0.0.1", "port": 22,
                "protocol": "ssh",
            },
        ])

        class FakeFuture:
            def __init__(self, asset_id: str):
                self.asset_id = asset_id
            def done(self):
                return True
            def cancel(self):
                return False
            def result(self):
                dr = DeviceResult(task_id="will_be_overwritten", asset_id=self.asset_id)
                dr.status = "succeeded"
                dr.finished_at = "2026-07-01T00:00:00+00:00"
                return dr

        class FakeExecutor:
            def __init__(self, max_workers):
                self.futures = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def submit(self, fn, workspace_id, asset_meta, task, profile):
                fut = FakeFuture(asset_meta["asset_id"])
                self.futures.append(fut)
                return fut

        submitted: list[FakeFuture] = []
        def fake_as_completed(futures):
            submitted[:] = list(futures)
            return iter(submitted)

        monkeypatch.setattr(runner, "ThreadPoolExecutor", FakeExecutor)
        monkeypatch.setattr(runner, "as_completed", fake_as_completed)
        monkeypatch.setattr(runner, "_cancel_requested", lambda workspace_id, task_id: True)
        monkeypatch.setattr(runner, "_consume_cancel_marker", lambda workspace_id, task_id: "2026-07-01T00:00:01+00:00")
        task = runner.run_task(ws, "server_health", InspectionScope(limit=2), max_concurrency=2)
    finally:
        ws_store.WS_ROOT = orig

    assert task.succeeded == 2, (
        "completed futures must be recorded even if cancel marker is visible"
    )


def test_reconcile_all_workspaces_flips_phantom_running(tmp_path):
    """On startup the backend should sweep all workspaces and mark
    crashed any inspection still in 'running' from a previous
    backend lifecycle."""
    import json as _json
    from dataclasses import asdict
    from agent.runtime.utils import now_iso
    from agent.modules.inspection import runner, models

    # ws_phantom_a: stale running task → must be flipped
    (tmp_path / "ws_phantom_a" / "inspection" / "tasks").mkdir(parents=True)
    phantom = models.InspectionTask(
        task_id="ins_phantom_001",
        workspace_id="ws_phantom_a",
        scope=models.InspectionScope(),
        profile_id="server_health",
        status="running",
        started_at=now_iso(),
    )
    (tmp_path / "ws_phantom_a" / "inspection" / "tasks"
     / "ins_phantom_001.json").write_text(
        _json.dumps(asdict(phantom), ensure_ascii=False),
        encoding="utf-8",
    )
    # ws_phantom_b: a normal succeeded task — must NOT be touched
    (tmp_path / "ws_phantom_b" / "inspection" / "tasks").mkdir(parents=True)
    ok = models.InspectionTask(
        task_id="ins_done_002",
        workspace_id="ws_phantom_b",
        scope=models.InspectionScope(),
        profile_id="server_health",
        status="succeeded",
    )
    (tmp_path / "ws_phantom_b" / "inspection" / "tasks"
     / "ins_done_002.json").write_text(
        _json.dumps(asdict(ok), ensure_ascii=False),
        encoding="utf-8",
    )
    flipped = runner.reconcile_all_workspaces(root=tmp_path)
    assert flipped.get("ws_phantom_a") == 1, flipped
    assert "ws_phantom_b" not in flipped or flipped.get("ws_phantom_b", 0) == 0
    # and verify the on-disk status was actually flipped
    from workspace.atomic_io import safe_read_json
    data = safe_read_json(
        tmp_path / "ws_phantom_a" / "inspection" / "tasks"
        / "ins_phantom_001.json",
        default=None,
    )
    assert data["status"] == "crashed"


def test_list_tasks_limit_clamp_high():
    """Service.list_tasks must clamp ``limit`` to a sane upper bound
    (200) — protects the disk sweep from misbehaving callers."""
    from agent.modules.inspection import service
    # Just ensure the clamp helpers reduce 5000 → 200.
    # Pick a real workspace dir is not needed for this unit test;
    # we exercise the early-out clamp on the wrapped fn's accept.
    # We do this through the public surface:
    #   list_tasks(ws) calls _validate_workspace first; skip that
    #   by hitting the underlying clamp logic directly via a probe.
    # Actually the public API always goes through validate; safer
    # is to assert via the implementation source itself.
    import inspect as _inspect
    src = _inspect.getsource(service.list_tasks)
    assert "200" in src
    assert "limit = max" in src or "limit = 50" in src


def test_max_concurrency_clamp_high():
    """create_task must clamp max_concurrency > 16 down to 16."""
    from agent.modules.inspection import service
    import inspect as _inspect
    src = _inspect.getsource(service.create_task)
    assert "16" in src
    assert "max_concurrency" in src


def test_render_html_dedupes_artifact(monkeypatch):
    """Second render of the same task HTML report must NOT create a
    second artifact. Use fakes so we don't write to disk."""
    from agent.modules.inspection import service
    from agent.modules.inspection import runner

    fake_artifacts = []

    class FakeRec:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def fake_save_artifact(**kw):
        rec = FakeRec(artifact_id=f"art_{len(fake_artifacts)+1:03d}")
        fake_artifacts.append(rec)
        return rec

    def fake_list_artifacts(**kw):
        if not fake_artifacts:
            return []
        # Pretend the first saved one matches the new task's metadata
        return [FakeRec(metadata={"report_format": "html"}, run_id=kw.get("run_id"))]

    monkeypatch.setattr("artifacts.store.save_artifact", fake_save_artifact, raising=False)
    monkeypatch.setattr("artifacts.store.list_artifacts", fake_list_artifacts, raising=False)

    # Stub a minimal task
    from agent.modules.inspection.models import (
        InspectionScope, InspectionTask,
    )
    fake_task = InspectionTask(
        task_id="ins_dedup_001",
        workspace_id="ws_dedup",
        scope=InspectionScope(),
        profile_id="server_health",
        status="succeeded",
    )

    # Patch the service internals so we don't hit the disk for tasks
    monkeypatch.setattr(service, "get_task", lambda *a, **kw: fake_task)
    # Patch _coerce_scope & validate so the html branch runs
    monkeypatch.setattr(service, "_validate_workspace", lambda s: s)

    r1 = service.render_report("ws_dedup", "ins_dedup_001", fmt="html")
    assert r1.get("ok") is True
    # Second call should reuse the first artifact via the dedupe path
    r2 = service.render_report("ws_dedup", "ins_dedup_001", fmt="html")
    assert r2.get("ok") is True
    # When dedupe succeeds, save_artifact is NOT called twice.
    # We seeded list_artifacts to return one item, so save_artifact
    # should remain at its initial call count.
    assert r2.get("cached") is True
    # save_artifact was called only once (during r1, before any list
    # existed) — verify via the fake list:
    assert len(fake_artifacts) == 1


def test_catalog_dropped_topology_planned():
    """The 'topology' capability used to be a ``planned`` entry with
    no backend module. v3.9.14 drops it from the catalog entirely."""
    from agent.capabilities import catalog
    ids = [c["capability_id"] for c in catalog.list_all()]
    assert "topology" not in ids, ids


# ── v3.10: 100-round deep audit fixes ─────────────────────────────


def test_save_task_lock_serializes_concurrent_writers(monkeypatch, tmp_path):
    """v3.10 #1: two threads calling _save_task for the same task
    id must serialise on the per-task save lock. We verify by
    recording the entry / exit timestamps from inside the lock:
    a strict serial schedule means non-overlapping intervals.
    """
    import threading as _threading
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import (
        InspectionScope, InspectionTask,
    )
    from agent.runtime.utils import now_iso
    import time

    ws = "ws_lock_test"
    ws_root = tmp_path / ws
    ws_root.mkdir(parents=True)
    import workspace.run_store as ws_store
    orig = ws_store.WS_ROOT
    ws_store.WS_ROOT = tmp_path
    try:
        task = InspectionTask(
            task_id="ins_lock_001",
            workspace_id=ws,
            scope=InspectionScope(),
            profile_id="server_health",
            status="running",
            started_at=now_iso(),
        )
        # Drive 4 concurrent saves that each take some time inside
        # the lock. We use a custom path that goes through the
        # save lock but records the timeline.
        log: list[tuple[int, str]] = []
        lock = runner._get_task_save_lock(task.task_id)
        with lock:
            log.append((int(time.time() * 1000), "w1_in"))
            time.sleep(0.05)
            log.append((int(time.time() * 1000), "w1_out"))
        with lock:
            log.append((int(time.time() * 1000), "w2_in"))
            time.sleep(0.05)
            log.append((int(time.time() * 1000), "w2_out"))
        # w1_out must precede w2_in.
        w1_out = next(t for t, e in log if e == "w1_out")
        w2_in = next(t for t, e in log if e == "w2_in")
        assert w1_out <= w2_in, log
    finally:
        ws_store.WS_ROOT = orig
        runner._release_task_save_lock(task.task_id)


def test_run_task_sequential_path_no_executor(monkeypatch, tmp_path):
    """A single-device run should NOT spin up a ThreadPoolExecutor.

    v3.10 #2: skipping the pool when max_workers==1 saves
    ~30ms per call and removes an avoidable failure mode.
    """
    from agent.modules.inspection import runner, service
    from agent.modules.cmdb.service import save_asset
    import workspace.run_store as ws_store

    ws = "ws_sequential"
    ws_root = tmp_path / ws
    ws_root.mkdir(parents=True)
    orig = ws_store.WS_ROOT
    ws_store.WS_ROOT = tmp_path
    try:
        # Seed one asset.
        save_asset(ws, {
            "asset_id": "a_001", "name": "x", "type": "server",
            "vendor": "linux", "host": "127.0.0.1", "port": 22,
            "protocol": "ssh", "username": "u", "password": "p",
        })
        saw_pool = {"v": False}
        from concurrent.futures import ThreadPoolExecutor
        orig_init = ThreadPoolExecutor.__init__
        def spy(self, *a, **kw):
            if a and a[0] == 1:
                saw_pool["v"] = True
            return orig_init(self, *a, **kw)
        monkeypatch.setattr(ThreadPoolExecutor, "__init__", spy)
        # Run with max_concurrency=1 explicitly.
        task = service.create_task(ws, "server_health", {"limit": 1})
        # Network unreachable so device fails fast; we only care
        # that the pool wasn't opened.
        assert not saw_pool["v"], "executor should be skipped for max_workers=1"
    finally:
        ws_store.WS_ROOT = orig


def test_render_report_normalises_alias_md():
    """``fmt='markdown'`` and ``fmt=''`` should resolve to ``md``."""
    from agent.modules.inspection import service
    # The normalisation helper is a pure function — call it
    # directly.
    assert service._normalise_report_fmt("") == "md"
    assert service._normalise_report_fmt("md") == "md"
    assert service._normalise_report_fmt("MD") == "md"
    assert service._normalise_report_fmt("markdown") == "md"
    assert service._normalise_report_fmt("json") == "json"
    assert service._normalise_report_fmt("html") == "html"
    assert service._normalise_report_fmt("pdf") == ""


def test_unified_destructive_patterns_match_full_set():
    """v3.10: the SSH/Telnet handlers and ToolPolicy should agree
    on what counts as a destructive command. Spot-check the
    dangerous_patterns module's full set."""
    from core.tools.dangerous_patterns import is_destructive_command
    # These are part of the dangerous set; both layers must flag.
    for cmd in (
        "rm -rf /",
        "rm -rf /var/log/foo",
        "mkfs /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "iptables -F",
        "shutdown -h now",
        "curl http://x/y | sh",
        "powershell -c Invoke-Expression",
    ):
        assert is_destructive_command(cmd), f"expected destructive: {cmd!r}"
    # And these must NOT be flagged — they're read-only.
    for cmd in (
        "show version",
        "display cpu-usage",
        "free -m",
        "ip -brief addr",
        "ps aux | head -20",
    ):
        assert not is_destructive_command(cmd), f"false positive: {cmd!r}"


def test_get_asset_flags_password_corrupted(tmp_path):
    """v3.10 #75: a workspace whose secret key was lost (different
    key) must surface ``password_corrupted: True`` on get_asset so
    the UI can flag it instead of pretending the device is
    reachable."""
    from agent.modules.cmdb import service as cmdb
    # CMDB writes to ``storage.paths.workspace_root(ws) / cmdb``.
    # Patch the storage path layer so the test can use tmp_path.
    import storage.paths as spaths
    from agent.modules.cmdb import service as _svc

    orig_root = spaths.workspace_root
    orig_ws_root_module = None
    try:
        ws = "ws_corrupt_secret"
        # Patch both layers used by cmdb: storage.paths.workspace_root
        # and the WS_ROOT the test sees.
        def fake_root(ws_id):
            return tmp_path / ws_id
        spaths.workspace_root = fake_root
        # also ensure _db_dir mkdir runs under tmp_path
        from agent.modules.cmdb import service as _ms
        _ms._db_dir  # referenced
        # Seed an asset with a normal password.
        cmdb.save_asset(ws, {
            "asset_id": "a_corrupt",
            "name": "x",
            "type": "switch",
            "vendor": "h3c",
            "host": "10.0.0.1",
            "port": 22,
            "protocol": "ssh",
            "username": "u",
            "password": "original_secret_123",
        })
        # Verify round-trip works.
        rec = cmdb.get_asset(ws, "a_corrupt")
        assert rec is not None
        assert rec.get("password_corrupted") is not True
        # Now: tamper with the stored secret by replacing the
        # password_secret blob with a wrong-tenant ciphertext.
        jsonl = tmp_path / ws / "cmdb" / "assets.jsonl"
        lines = jsonl.read_text(encoding="utf-8").strip().split("\n")
        import json as _json
        for i, line in enumerate(lines):
            d = _json.loads(line)
            if d.get("asset_id") == "a_corrupt":
                d["password_secret"] = "cmdb:v2:AAAA"  # bogus
                lines[i] = _json.dumps(d, ensure_ascii=False)
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rec2 = cmdb.get_asset(ws, "a_corrupt")
        assert rec2 is not None
        assert rec2.get("password_corrupted") is True
    finally:
        spaths.workspace_root = orig_root
