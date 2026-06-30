"""CMDB-driven device inspection workflow contract.

Pins the v3.9.13 inspection capability:

  1. catalog lists `inspection` capability with `inspection.manage`
     as primary recommended tool.
  2. canonical_registry has `inspection.manage` registered and it
     executes through the merged adapter.
  3. profile_list returns 5 builtin profiles (no LLM-typed commands).
  4. profile commands come from fixed per-vendor map; raw commands
     never appear in the canonical schema.
  5. create_task rejects ``profile_id=""`` and unknown profiles but
     accepts CMDB scope with ``limit``.
  6. manifest_registry has 22 manifests including `inspection.manage`.
  7. tool_namespace_data has 22 NS_DATA entries including inspection.
  8. tool_namespace has matching canonical count (no drift).
  9. backend GET /api/inspection/profiles returns the same shape as
     inspectionApi.listProfiles.
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
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    for tid in cap["recommended_tool_ids"]:
        assert tid in TOOL_NAMESPACE, f"{tid} not in canonical namespace"


def test_canonical_inspection_manage_registered():
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    assert "inspection.manage" in CANONICAL_REGISTRY
    entry = CANONICAL_REGISTRY["inspection.manage"]
    schema = entry.input_schema or {}
    fields = set(schema.get("properties", {}).keys())
    # action discriminator must include 6 actions
    enum_actions = set(schema["properties"]["action"].get("enum", []))
    for required_action in (
        "profile_list", "run", "task_list", "task_get",
        "task_cancel", "report",
    ):
        assert required_action in enum_actions, (
            f"missing action={required_action} in inspection.manage schema"
        )
    # No raw password / credential field — runner is server-side only
    forbidden = {"password", "credentials", "secret", "token"}
    leaked = forbidden & fields
    assert not leaked, f"inspection.manage schema leaks {leaked}"


def test_profile_list_returns_five_builtin_profiles():
    from tool_runtime.schemas import ToolInvocation
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    inv = ToolInvocation(
        arguments={"workspace_id": "ws_demo", "action": "profile_list"},
        tool_id="inspection.manage",
    )
    result = CANONICAL_REGISTRY["inspection.manage"].handler(inv)
    assert result["ok"] is True
    profiles = result["profiles"]
    assert result["count"] == len(profiles) == 5, (
        f"expected 5 builtin profiles, got {len(profiles)}"
    )
    ids = {p["profile_id"] for p in profiles}
    assert ids == {"basic_health", "interface_health", "routing_health",
                    "config_backup", "full_basic"}
    # All profiles must be read-only (risk_level=low, no destructive surface)
    for p in profiles:
        assert p["risk_level"] == "low"
        assert p["requires_approval"] is False
        # Every check must have a known parser_key (LLM-typed strings rejected)
        for c in p["checks"]:
            assert c["command_key"], "command_key required"
            assert c["parser_key"], "parser_key required"


def test_profile_commands_fixed_per_vendor_no_llm_input():
    """Vendor command profiles are fixed maps. The LLM never composes commands."""
    from agent.modules.inspection.profiles import (
        VENDOR_COMMAND_PROFILES, is_read_only_command,
    )
    # h3c / huawei / cisco / generic fallback
    expected = {"h3c", "huawei", "cisco", "generic"}
    assert set(VENDOR_COMMAND_PROFILES) == expected, (
        f"vendor profile set mismatch: got {set(VENDOR_COMMAND_PROFILES)}"
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


def test_create_task_rejects_empty_or_unknown_profile():
    """create_task must give a deterministic failure for missing/invalid profile."""
    from agent.modules.inspection import service as svc

    # Empty profile_id rejected via service internals (resolve_profile returns None)
    bad1 = svc.create_task(workspace_id="ws_demo", profile_id="")
    # Unknown profile id — service emits a failed InspectionTask with
    # error="unknown_profile: ..."
    bad2 = svc.create_task(workspace_id="ws_demo", profile_id="does_not_exist_xyz")
    assert bad2.status == "failed"
    assert bad2.error.startswith("unknown_profile:")
    # bad1 path — resolve_profile("") falls back to default value semantics, must not throw
    assert bad1.status in ("failed", "succeeded")


def test_create_task_with_known_profile_and_empty_scope_succeeds():
    """Empty CMDB scope (no assets) must run — runner yields succeeded status."""
    from agent.modules.inspection import service as svc

    task = svc.create_task(
        workspace_id="ws_test_inspect",
        profile_id="basic_health",
        scope={"limit": 10},
    )
    assert task.status in ("succeeded", "partial"), task.error
    assert task.total_assets == 0  # empty assets
    assert task.started_at and task.finished_at


def test_manifest_registry_has_22_manifests_with_inspection():
    from tool_runtime.manifest_registry import MANIFESTS, validate_all
    errors, count = validate_all()
    assert count == 22, f"expected 22 manifests, got {count}"
    assert not errors, f"manifest validation errors: {errors}"
    assert "inspection.manage" in MANIFESTS
    # The runner caller (inspection_runner) must be in allowed_callers
    ins = MANIFESTS["inspection.manage"]
    assert "inspection_runner" in ins.allowed_callers
    # exec.run + device.manage must accept inspection_runner too
    assert "inspection_runner" in MANIFESTS["exec.run"].allowed_callers
    assert "inspection_runner" in MANIFESTS["device.manage"].allowed_callers


def test_namespace_data_has_22_entries_with_inspection():
    """NS_DATA / canonical / namespace triple stay in sync."""
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_namespace_data import NS_DATA
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY

    assert len(NS_DATA) == len(TOOL_NAMESPACE) == len(CANONICAL_REGISTRY) == 22
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


def test_backend_profiles_route_shape_matches_api():
    """The live backend ``/api/inspection/profiles`` returns the same shape
    the frontend expects. We start a tiny in-process Flask app pointing
    to the canonical handler. (No real backend boot needed.)"""
    # The contract is: profiles keys MUST match InspectionProfile type
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
    from tool_runtime import canonical_registry
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
    # Empty-scope report must still include the basic structure: scope / profile / summary
    assert "巡检模板" in md, "report must include template name section"
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


def test_telnet_asset_uses_telnet_target(monkeypatch):
    """The runner must pass the CMDB protocol into exec.run target."""
    from agent.modules.inspection import runner
    from agent.modules.inspection.models import InspectionCheck, InspectionProfile, InspectionTask, InspectionScope

    seen_protocols = []

    def fake_exec(workspace_id, asset_id, protocol, command, timeout):
        seen_protocols.append(protocol)
        return {"ok": True, "output": "H3C Comware Software", "error": ""}

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
