"""agent.modules.inspection.profiles

v4.0: flat command lists — no more command_key indirection. Each
vendor has a plain ordered list of read-only commands. pre_commands
runs after SSH login (welcome-banner flush + screen-length disable);
post_commands runs after all checks finish.

All commands are **read-only**. Never include write/dangerous
commands in a profile.

支持的厂商：H3C / HuaWei / Cisco / Hillstone / Ruijie / Dipu / generic
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from .models import (
    InspectionCheck,
    InspectionProfile,
    VendorCommandProfile,
)
from agent.runtime.utils import now_iso

ENTER_ACTION = "__ENTER__"

# ==========================================================================
# v4.0 — H3C command sets (flat lists, no parser keys)
# ==========================================================================

_H3C_PRE = ["screen-length disable"]

_H3C_POST = [
    "undo screen-length disable",
]

# v4.1: no built-in command lists — commands come exclusively from
# script management workspace overrides.  The constants below are
# retained as empty placeholders so downstream code doesn't break.
H3C_GENERAL_COMMANDS: list[str] = []
H3C_LOG_COMMANDS: list[str] = []

# ==========================================================================
# v4.0 — Vendor command profiles (H3C only for now)
# ==========================================================================

VENDOR_COMMAND_PROFILES: dict[str, VendorCommandProfile] = {
    "h3c": VendorCommandProfile(
        vendor="h3c",
        commands=H3C_GENERAL_COMMANDS,
        pre_commands=_H3C_PRE,
        post_commands=_H3C_POST,
    ),
    "huawei": VendorCommandProfile(
        vendor="huawei",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
    "cisco": VendorCommandProfile(
        vendor="cisco",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
    "hillstone": VendorCommandProfile(
        vendor="hillstone",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
    "ruijie": VendorCommandProfile(
        vendor="ruijie",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
    "dipu": VendorCommandProfile(
        vendor="dipu",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
    "generic": VendorCommandProfile(
        vendor="generic",
        commands=[],
        pre_commands=[],
        post_commands=[],
    ),
}

# ==========================================================================
# v4.0 — Inspection profiles
# ==========================================================================

AUTO_PROFILE_ID = "auto"

AUTO_PROFILE = InspectionProfile(
    profile_id=AUTO_PROFILE_ID,
    display_name="自动巡检",
    description="根据 CMDB 厂商和设备类型自动选择命令集。",
    checks=(),
    risk_level="medium",
)

BUILTIN_PROFILES: dict[str, InspectionProfile] = {
    "general": InspectionProfile(
        profile_id="general",
        display_name="通用巡检",
        description="全面硬件/协议/环境状态采集（不含日志）。",
        checks=tuple([
            InspectionCheck(
                check_id="general.collect",
                category="health",
                display_name="全量采集",
                command_key="__all__",  # runner detects this and runs all commands
                parser_key="raw",       # raw passthrough — LLM analyses
                severity_default="info",
            ),
        ]),
        risk_level="low",
    ),
    "log": InspectionProfile(
        profile_id="log",
        display_name="日志巡检",
        description="仅采集系统日志，由 LLM 分析异常。",
        checks=tuple([
            InspectionCheck(
                check_id="log.collect",
                category="health",
                display_name="日志采集",
                command_key="__log__",  # runner detects this and runs log commands
                parser_key="raw",
                severity_default="info",
                timeout_seconds=120,     # logs can be large
            ),
        ]),
        risk_level="low",
    ),
}


# ==========================================================================
# profile resolution
# ==========================================================================

def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "").replace("_", "")


def resolve_command_profile(vendor: str = "", device_type: str = "") -> VendorCommandProfile:
    """Resolve commands by CMDB vendor + type.

    支持的厂商：H3C / Huawei / Cisco / Hillstone / Ruijie / Dipu
    以及中文别名：华三、华为
    """
    v = _norm(vendor)
    t = _norm(device_type)
    if "h3c" in v or "华三" in v:
        return VENDOR_COMMAND_PROFILES["h3c"]
    if "huawei" in v or "华为" in v:
        return VENDOR_COMMAND_PROFILES["huawei"]
    if "cisco" in v:
        return VENDOR_COMMAND_PROFILES["cisco"]
    if "hillstone" in v or "山石" in v:
        return VENDOR_COMMAND_PROFILES["hillstone"]
    if "ruijie" in v or "锐捷" in v:
        return VENDOR_COMMAND_PROFILES["ruijie"]
    if "dipu" in v:
        return VENDOR_COMMAND_PROFILES["dipu"]
    return VENDOR_COMMAND_PROFILES["generic"]


def resolve_profile(profile_id: str) -> InspectionProfile | None:
    """Return the profile or None if the id is unknown."""
    if not (profile_id or "").strip() or profile_id == AUTO_PROFILE_ID:
        return AUTO_PROFILE
    return BUILTIN_PROFILES.get(profile_id)


def resolve_auto_profile_id(vendor: str = "", device_type: str = "") -> str:
    """Resolve the internal inspection profile for one CMDB asset."""
    cp = resolve_command_profile(vendor, device_type)
    if cp.vendor == "h3c":
        return "general"
    return "general"


def resolve_auto_profile(vendor: str = "", device_type: str = "") -> InspectionProfile:
    """Return the concrete internal profile used for one asset."""
    return BUILTIN_PROFILES[resolve_auto_profile_id(vendor, device_type)]


def resolve_vendor(vendor: str) -> VendorCommandProfile:
    """Look up vendor commands. Falls back to ``generic`` if unknown."""
    return resolve_command_profile(vendor, "")


# ==========================================================================
# workspace-level script overrides
# ==========================================================================
# Operators can customise per-vendor commands via the frontend
# ScriptManager modal. Overrides are stored as JSON files under the
# workspace's ``inspection/scripts/<general|log>/`` directory.
# If no override exists for a vendor the built-in defaults apply.


_SCRIPT_TYPES = {"general", "log"}


def _scripts_dir(workspace_id: str, script_type: str = "general") -> Path:
    """Return ``<WS_ROOT>/<ws>/inspection/scripts/<type>/``, creating if needed."""
    from workspace.run_store import WS_ROOT
    from workspace.ids import validate_workspace_id
    stype = script_type if script_type in _SCRIPT_TYPES else "general"
    p = WS_ROOT / validate_workspace_id(workspace_id) / "inspection" / "scripts" / stype
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_vendor_commands(workspace_id: str, vendor: str, *, script_type: str = "general") -> dict | None:
    """Return workspace-level command overrides for *vendor* and *script_type*, or None.

    v4.3: Returns a dict with {commands, pre_commands, post_commands}.
    pre_commands / post_commands is None when the field is missing in the
    JSON file (legacy format) — callers should fall back to built-in defaults.
    """
    fp = _scripts_dir(workspace_id, script_type) / f"{vendor}.json"
    if not fp.is_file():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    raw_pre = data.get("pre_commands")
    raw_post = data.get("post_commands")
    return {
        "commands": _clean_commands(data.get("commands")),
        "pre_commands": _clean_commands(raw_pre) if isinstance(raw_pre, list) else None,
        "post_commands": _clean_commands(raw_post) if isinstance(raw_post, list) else None,
    }


def _clean_commands(commands) -> list[str]:
    """Return command/action lines only; blank rows are not executable."""
    if not isinstance(commands, list):
        return []
    cleaned: list[str] = []
    for command in commands:
        token = str(command or "").strip()
        if not token:
            continue
        cleaned.append(ENTER_ACTION if _is_enter_action(token) else token)
    return cleaned


def _is_enter_action(command: str) -> bool:
    return str(command or "").strip().upper() in {
        ENTER_ACTION,
        "__CR__",
        "__RETURN__",
        "<ENTER>",
        "[ENTER]",
        "(ENTER)",
        "ENTER",
        "回车",
        "(回车)",
    }


def save_vendor_commands(workspace_id: str, vendor: str,
                         commands: list[str], *, script_type: str = "general",
                         pre_commands: list[str] | None = None,
                         post_commands: list[str] | None = None) -> bool:
    """Persist a workspace-level vendor command override (including pre/post)."""
    from workspace.atomic_io import atomic_write_json
    fp = _scripts_dir(workspace_id, script_type) / f"{vendor}.json"
    data = {
        "vendor": vendor,
        "script_type": script_type,
        "updated_at": now_iso(),
        "source": "manual",
        "commands": _clean_commands(commands),
    }
    if pre_commands is not None:
        data["pre_commands"] = _clean_commands(pre_commands)
    if post_commands is not None:
        data["post_commands"] = _clean_commands(post_commands)
    try:
        atomic_write_json(fp, data)
        return True
    except OSError:
        return False


def delete_vendor_commands(workspace_id: str, vendor: str, *, script_type: str = "general") -> bool:
    """Remove a workspace-level vendor override."""
    fp = _scripts_dir(workspace_id, script_type) / f"{vendor}.json"
    try:
        if fp.is_file():
            fp.unlink()
            return True
    except OSError:
        pass
    return False


def upload_vendor_script_file(workspace_id: str, vendor: str,
                              file_content: str, *, script_type: str = "general") -> bool:
    """Persist a vendor script from an uploaded .txt file.
    Each non-empty, non-comment line is treated as a command.
    """
    lines: list[str] = []
    for raw in file_content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Safety: disallow write commands even via file upload path
        if not is_read_only_command(line):
            logger.warning("upload_vendor_script_file: blocked write command %r for vendor=%s", line, vendor)
            continue
        lines.append(line)
    if not lines:
        return False
    defaults = resolve_command_profile(vendor, "")
    return save_vendor_commands(
        workspace_id,
        vendor,
        lines,
        script_type=script_type,
        pre_commands=list(defaults.pre_commands or []),
        post_commands=list(defaults.post_commands or []),
    )


def load_command_profile(workspace_id: str, vendor: str = "",
                         device_type: str = "", *, script_type: str = "general") -> VendorCommandProfile:
    """Resolve the vendor command profile from workspace-level script
    overrides.  No built-in commands — script management is the sole
    source.  If the matched vendor has no override, fall back to the
    generic vendor's override.  If neither exists, return an empty
    command list (runner will skip the device gracefully)."""
    resolved = resolve_command_profile(vendor, device_type)

    # 1) workspace override for the matched vendor
    overrides = load_vendor_commands(workspace_id, resolved.vendor, script_type=script_type)
    if overrides is not None:
        pre = overrides.get("pre_commands")
        post = overrides.get("post_commands")
        return VendorCommandProfile(
            vendor=resolved.vendor,
            commands=overrides.get("commands", []),
            pre_commands=pre if pre is not None else resolved.pre_commands,
            post_commands=post if post is not None else resolved.post_commands,
            fallback_to_generic=resolved.fallback_to_generic,
            supported_checks=resolved.supported_checks,
        )

    # 2) fall back to generic override
    if resolved.vendor != "generic":
        generic_overrides = load_vendor_commands(workspace_id, "generic", script_type=script_type)
        if generic_overrides is not None:
            pre = generic_overrides.get("pre_commands")
            post = generic_overrides.get("post_commands")
            return VendorCommandProfile(
                vendor="generic",
                commands=generic_overrides.get("commands", []),
                pre_commands=pre if pre is not None else resolved.pre_commands,
                post_commands=post if post is not None else resolved.post_commands,
                fallback_to_generic=True,
                supported_checks=resolved.supported_checks,
            )

    # 3) nothing configured → empty (runner handles)
    return resolved


# ==========================================================================
# read-only safety check
# ==========================================================================

def is_read_only_command(command: str) -> bool:
    """Static safety check: refuse anything that smells like a write.

    Empty strings are ignored by profile loading and are not executable.
    """
    cmd = (command or "").strip().lower()
    if not cmd:
        return True
    if _is_enter_action(command):
        return True
    blocked_prefixes = (
        "write ", "copy running", "copy start", "save ",
        "reload", "reboot", "reset", "shutdown", "poweroff",
        "delete", "erase", "format ", "config ", "system-view",
        "configure terminal", "conf t", "sys ", "quit-config",
    )
    if any(cmd.startswith(p) for p in blocked_prefixes):
        return False
    blocked_substrings = (
        " | redirect", " > ", " >> ",
        " tftp:", " ftp:", " scp:",
        " commit ", "rollback-configuration",
    )
    if any(b in cmd for b in blocked_substrings):
        return False
    return True
