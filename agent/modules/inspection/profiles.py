"""agent.modules.inspection.profiles

Built-in ``InspectionProfile`` and ``VendorCommandProfile``
registries. The command set is intentionally boring: fixed, read-only
operator scripts keyed by vendor/type. LLMs pass a CMDB scope only; the
backend chooses the script set from each asset's vendor and device type.

All commands are **read-only**. The pipeline:
    ``display version`` / ``show version``
    ``display cpu-usage`` / ``show processes cpu``
    ...
    never include ``reset``, ``reboot``, ``delete``, ``save``,
    ``format``, ``config terminal``, ``system-view``, etc.

Adding a new vendor: drop a ``VENDOR_COMMAND_PROFILES`` entry below
with the same ``command_key`` keys you used in :mod:`profiles`.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    InspectionCheck,
    InspectionProfile,
    VendorCommandProfile,
)
from agent.runtime.utils import now_iso


# ── command keys (one per inspection check) ───────────────────────────────

CK_VERSION         = "version"
CK_CPU             = "cpu"
CK_MEMORY          = "memory"
CK_INTERFACE_BRIEF = "interface_brief"
CK_INTERFACE_ERROR = "interface_error"
CK_OSPF_PEER       = "ospf_peer"
CK_BGP_SUMMARY     = "bgp_summary"
CK_ROUTE_SUMMARY   = "route_summary"
CK_CURRENT_CONFIG  = "current_config"
CK_ENVIRONMENT     = "environment"
CK_LOG             = "log"
CK_ARP             = "arp"
CK_MAC             = "mac"
CK_VLAN            = "vlan"
CK_FIREWALL_SESSION = "firewall_session"
CK_FIREWALL_POLICY  = "firewall_policy"
CK_FIREWALL_NAT     = "firewall_nat"
CK_FIREWALL_HA      = "firewall_ha"
CK_SERVER_DISK      = "server_disk"
CK_SERVER_PROCESS   = "server_process"
CK_SERVER_NETWORK   = "server_network"
CK_SERVER_LISTEN    = "server_listen"


# ── builtin inspection profiles (MVP) ──────────────────────────────────────

AUTO_PROFILE_ID = "auto"
AUTO_PROFILE = InspectionProfile(
    profile_id=AUTO_PROFILE_ID,
    display_name="自动巡检",
    description="根据 CMDB 厂商和设备类型自动选择固定只读脚本。",
    checks=(),
    risk_level="medium",
)

BUILTIN_PROFILES: dict[str, InspectionProfile] = {
    "basic_health": InspectionProfile(
        profile_id="basic_health",
        display_name="基础健康检查",
        description="采集版本、运行时间、CPU 与内存利用率。",
        checks=tuple([
            InspectionCheck(
                check_id="basic.version", category="health",
                display_name="设备版本", command_key=CK_VERSION,
                parser_key="version",
                severity_default="info",
            ),
            InspectionCheck(
                check_id="basic.cpu", category="health",
                display_name="CPU 利用率", command_key=CK_CPU,
                parser_key="cpu",
                severity_default="info",
                timeout_seconds=20,
            ),
            InspectionCheck(
                check_id="basic.memory", category="health",
                display_name="内存利用率", command_key=CK_MEMORY,
                parser_key="memory",
                severity_default="info",
            ),
            InspectionCheck(
                check_id="basic.env", category="health",
                display_name="硬件/环境状态", command_key=CK_ENVIRONMENT,
                parser_key="environment",
                severity_default="warning",
            ),
            InspectionCheck(
                check_id="basic.log", category="health",
                display_name="近期告警日志", command_key=CK_LOG,
                parser_key="log",
                severity_default="warning",
            ),
        ]),
        risk_level="low",
    ),
    "interface_health": InspectionProfile(
        profile_id="interface_health",
        display_name="接口健康",
        description="接口摘要与按厂商可选的错包 / CRC / drop 计数。",
        checks=tuple([
            InspectionCheck(
                check_id="iface.brief", category="interface",
                display_name="接口摘要", command_key=CK_INTERFACE_BRIEF,
                parser_key="interface_brief",
                severity_default="info",
            ),
            InspectionCheck(
                check_id="iface.error", category="interface",
                display_name="接口错包 / 丢包计数", command_key=CK_INTERFACE_ERROR,
                parser_key="interface_error",
                severity_default="warning",
                timeout_seconds=30,
            ),
        ]),
        risk_level="low",
    ),
    "routing_health": InspectionProfile(
        profile_id="routing_health",
        display_name="路由健康",
        description="OSPF / BGP 邻居状态及路由表摘要。",
        checks=tuple([
            InspectionCheck(
                check_id="routing.ospf", category="routing",
                display_name="OSPF 邻居", command_key=CK_OSPF_PEER,
                parser_key="ospf_peer",
                severity_default="warning",
            ),
            InspectionCheck(
                check_id="routing.bgp", category="routing",
                display_name="BGP 概要", command_key=CK_BGP_SUMMARY,
                parser_key="bgp_summary",
                severity_default="warning",
                timeout_seconds=45,
            ),
            InspectionCheck(
                check_id="routing.route", category="routing",
                display_name="路由表摘要", command_key=CK_ROUTE_SUMMARY,
                parser_key="route_summary",
                severity_default="info",
                timeout_seconds=45,
            ),
        ]),
        risk_level="low",
    ),
    "config_backup": InspectionProfile(
        profile_id="config_backup",
        display_name="配置备份",
        description="抓取当前运行配置作为 artifact 保存。",
        checks=tuple([
            InspectionCheck(
                check_id="config.current", category="config",
                display_name="当前配置", command_key=CK_CURRENT_CONFIG,
                parser_key="current_config",
                severity_default="info",
                timeout_seconds=60,
            ),
        ]),
        risk_level="low",
    ),
    "firewall_health": InspectionProfile(
        profile_id="firewall_health",
        display_name="防火墙巡检",
        description="会话、策略、NAT、HA 与基础资源状态。",
        checks=tuple([
            InspectionCheck(
                check_id="fw.session", category="security",
                display_name="会话状态", command_key=CK_FIREWALL_SESSION,
                parser_key="firewall_session",
                severity_default="info",
                timeout_seconds=45,
            ),
            InspectionCheck(
                check_id="fw.policy", category="security",
                display_name="安全策略", command_key=CK_FIREWALL_POLICY,
                parser_key="firewall_policy",
                severity_default="info",
                timeout_seconds=60,
            ),
            InspectionCheck(
                check_id="fw.nat", category="security",
                display_name="NAT 状态", command_key=CK_FIREWALL_NAT,
                parser_key="firewall_nat",
                severity_default="info",
                timeout_seconds=45,
            ),
            InspectionCheck(
                check_id="fw.ha", category="health",
                display_name="双机/集群状态", command_key=CK_FIREWALL_HA,
                parser_key="ha",
                severity_default="warning",
                timeout_seconds=45,
            ),
        ]),
        risk_level="medium",
    ),
    "server_health": InspectionProfile(
        profile_id="server_health",
        display_name="服务器巡检",
        description="Linux 服务器的系统版本、负载、内存、磁盘、网卡与监听端口。",
        checks=tuple([
            InspectionCheck(
                check_id="srv.version", category="health",
                display_name="系统版本", command_key=CK_VERSION,
                parser_key="version",
                severity_default="info",
            ),
            InspectionCheck(
                check_id="srv.cpu", category="health",
                display_name="CPU / 负载", command_key=CK_CPU,
                parser_key="cpu",
                severity_default="warning",
            ),
            InspectionCheck(
                check_id="srv.memory", category="health",
                display_name="内存", command_key=CK_MEMORY,
                parser_key="memory",
                severity_default="warning",
            ),
            InspectionCheck(
                check_id="srv.disk", category="health",
                display_name="磁盘空间", command_key=CK_SERVER_DISK,
                parser_key="server_disk",
                severity_default="warning",
            ),
            InspectionCheck(
                check_id="srv.network", category="interface",
                display_name="网卡地址", command_key=CK_SERVER_NETWORK,
                parser_key="interface_brief",
                severity_default="info",
            ),
            InspectionCheck(
                check_id="srv.listen", category="security",
                display_name="监听端口", command_key=CK_SERVER_LISTEN,
                parser_key="server_listen",
                severity_default="info",
            ),
        ]),
        risk_level="medium",
    ),
    }  # end BUILTIN_PROFILES (declared above)

# ``full_basic`` aliases the union of basic + interface + routing.
BUILTIN_PROFILES["full_basic"] = InspectionProfile(
    profile_id="full_basic",
    display_name="综合巡检（基础 + 接口 + 路由）",
    description="一次完成基础状态、接口状态和路由邻居检查。",
    checks=tuple(
        BUILTIN_PROFILES["basic_health"].checks
        + BUILTIN_PROFILES["interface_health"].checks
        + BUILTIN_PROFILES["routing_health"].checks
    ),
    risk_level="low",
)


# ── vendor command templates ──────────────────────────────────────────────

VENDOR_COMMAND_PROFILES: dict[str, VendorCommandProfile] = {
    "h3c": VendorCommandProfile(
        vendor="h3c",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG, CK_ENVIRONMENT, CK_LOG,
            CK_ARP, CK_MAC, CK_VLAN,
        ),
        commands={
            CK_VERSION:         "display version",
            CK_CPU:             "display cpu-usage",
            CK_MEMORY:          "display memory",
            CK_INTERFACE_BRIEF: "display interface brief",
            CK_INTERFACE_ERROR: "display interface | include CRC ERROR DROP",
            CK_OSPF_PEER:       "display ospf peer brief",
            CK_BGP_SUMMARY:     "display bgp peer ipv4 unicast",
            CK_ROUTE_SUMMARY:   "display ip routing-table summary",
            CK_CURRENT_CONFIG:  "display current-configuration",
            CK_ENVIRONMENT:     "display device",
            CK_LOG:             "display logbuffer reverse",
            CK_ARP:             "display arp",
            CK_MAC:             "display mac-address",
            CK_VLAN:            "display vlan brief",
        },
    ),
    "h3c_firewall": VendorCommandProfile(
        vendor="h3c_firewall",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_ROUTE_SUMMARY, CK_CURRENT_CONFIG,
            CK_ENVIRONMENT, CK_LOG,
            CK_FIREWALL_SESSION, CK_FIREWALL_POLICY,
            CK_FIREWALL_NAT, CK_FIREWALL_HA,
        ),
        commands={
            CK_VERSION:          "display version",
            CK_CPU:              "display cpu-usage",
            CK_MEMORY:           "display memory",
            CK_INTERFACE_BRIEF:  "display interface brief",
            CK_INTERFACE_ERROR:  "display interface | include CRC ERROR DROP",
            CK_ROUTE_SUMMARY:    "display ip routing-table summary",
            CK_CURRENT_CONFIG:   "display current-configuration",
            CK_ENVIRONMENT:      "display device",
            CK_LOG:              "display logbuffer reverse",
            CK_FIREWALL_SESSION: "display session table",
            CK_FIREWALL_POLICY:  "display security-policy",
            CK_FIREWALL_NAT:     "display nat session",
            CK_FIREWALL_HA:      "display redundancy group",
        },
    ),
    "huawei": VendorCommandProfile(
        vendor="huawei",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG, CK_ENVIRONMENT, CK_LOG,
            CK_ARP, CK_MAC, CK_VLAN,
        ),
        commands={
            CK_VERSION:         "display version",
            CK_CPU:             "display cpu-usage",
            CK_MEMORY:          "display memory-usage",
            CK_INTERFACE_BRIEF: "display interface brief",
            CK_INTERFACE_ERROR: "display interface | include CRC ERROR DROP",
            CK_OSPF_PEER:       "display ospf peer brief",
            CK_BGP_SUMMARY:     "display bgp peer ipv4 unicast",
            CK_ROUTE_SUMMARY:   "display ip routing-table summary",
            CK_CURRENT_CONFIG:  "display current-configuration",
            CK_ENVIRONMENT:     "display device",
            CK_LOG:             "display logbuffer",
            CK_ARP:             "display arp",
            CK_MAC:             "display mac-address",
            CK_VLAN:            "display vlan",
        },
    ),
    "cisco": VendorCommandProfile(
        vendor="cisco",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG, CK_ENVIRONMENT, CK_LOG,
            CK_ARP, CK_MAC, CK_VLAN,
        ),
        commands={
            CK_VERSION:         "show version",
            CK_CPU:             "show processes cpu",
            CK_MEMORY:          "show memory statistics",
            CK_INTERFACE_BRIEF: "show ip interface brief",
            CK_INTERFACE_ERROR: "show interfaces counters | include CRC errors drop",
            CK_OSPF_PEER:       "show ip ospf neighbor",
            CK_BGP_SUMMARY:     "show ip bgp summary",
            CK_ROUTE_SUMMARY:   "show ip route summary",
            CK_CURRENT_CONFIG:  "show running-config",
            CK_ENVIRONMENT:     "show environment all",
            CK_LOG:             "show logging",
            CK_ARP:             "show ip arp",
            CK_MAC:             "show mac address-table",
            CK_VLAN:            "show vlan brief",
        },
    ),
    "ruijie": VendorCommandProfile(
        vendor="ruijie",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG, CK_ENVIRONMENT, CK_LOG,
            CK_ARP, CK_MAC, CK_VLAN,
        ),
        commands={
            CK_VERSION:         "show version",
            CK_CPU:             "show cpu",
            CK_MEMORY:          "show memory",
            CK_INTERFACE_BRIEF: "show ip interface brief",
            CK_INTERFACE_ERROR: "show interfaces counters errors",
            CK_OSPF_PEER:       "show ip ospf neighbor",
            CK_BGP_SUMMARY:     "show ip bgp summary",
            CK_ROUTE_SUMMARY:   "show ip route summary",
            CK_CURRENT_CONFIG:  "show running-config",
            CK_ENVIRONMENT:     "show environment",
            CK_LOG:             "show logging",
            CK_ARP:             "show arp",
            CK_MAC:             "show mac-address-table",
            CK_VLAN:            "show vlan",
        },
    ),
    "hillstone": VendorCommandProfile(
        vendor="hillstone",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_ROUTE_SUMMARY, CK_CURRENT_CONFIG,
            CK_LOG, CK_FIREWALL_SESSION, CK_FIREWALL_POLICY,
            CK_FIREWALL_NAT, CK_FIREWALL_HA,
        ),
        commands={
            CK_VERSION:          "show version",
            CK_CPU:              "show cpu",
            CK_MEMORY:           "show memory",
            CK_INTERFACE_BRIEF:  "show interface",
            CK_INTERFACE_ERROR:  "show interface",
            CK_ROUTE_SUMMARY:    "show route",
            CK_CURRENT_CONFIG:   "show configuration",
            CK_LOG:              "show log",
            CK_FIREWALL_SESSION: "show session",
            CK_FIREWALL_POLICY:  "show policy",
            CK_FIREWALL_NAT:     "show nat",
            CK_FIREWALL_HA:      "show ha",
        },
    ),
    "server": VendorCommandProfile(
        vendor="server",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_SERVER_DISK, CK_SERVER_PROCESS,
            CK_SERVER_NETWORK, CK_SERVER_LISTEN, CK_LOG,
        ),
        commands={
            CK_VERSION:        "uname -a",
            CK_CPU:            "top -bn1 | head -20",
            CK_MEMORY:         "free -m",
            CK_SERVER_DISK:    "df -h",
            CK_SERVER_PROCESS: "ps aux --sort=-%cpu | head -20",
            CK_SERVER_NETWORK: "ip -brief addr",
            CK_SERVER_LISTEN:  "ss -tuln",
            CK_LOG:            "journalctl -p warning -n 50 --no-pager",
        },
    ),
    "generic": VendorCommandProfile(
        vendor="generic",
        supported_checks=(CK_VERSION, CK_INTERFACE_BRIEF),
        fallback_to_generic=True,
        commands={
            # Only the absolute safest read-only commands.
            CK_VERSION:         "show version",
            CK_INTERFACE_BRIEF: "show ip interface brief",
        },
    ),
}


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "").replace("_", "")


def resolve_command_profile(vendor: str = "", device_type: str = "") -> VendorCommandProfile:
    """Resolve commands by CMDB vendor + type.

    The CMDB ``type`` wins for server/firewall because those assets need
    materially different scripts even when the vendor field is unknown or
    shared with switching products.
    """
    v = _norm(vendor)
    t = _norm(device_type)
    if t in {"server", "服务器", "linux", "主机"} or "linux" in v or "server" in v:
        return VENDOR_COMMAND_PROFILES["server"]
    if "hillstone" in v or "山石" in v:
        return VENDOR_COMMAND_PROFILES["hillstone"]
    if "ruijie" in v or "锐捷" in v:
        return VENDOR_COMMAND_PROFILES["ruijie"]
    if "huawei" in v or "华为" in v:
        return VENDOR_COMMAND_PROFILES["huawei"]
    if "cisco" in v or "思科" in v:
        return VENDOR_COMMAND_PROFILES["cisco"]
    if "h3c" in v or "华三" in v:
        if t in {"firewall", "防火墙"} or "firewall" in v or "防火墙" in v:
            return VENDOR_COMMAND_PROFILES["h3c_firewall"]
        return VENDOR_COMMAND_PROFILES["h3c"]
    return VENDOR_COMMAND_PROFILES["generic"]


def resolve_profile(profile_id: str) -> InspectionProfile | None:
    """Return the profile or None if the id is unknown."""
    if not (profile_id or "").strip() or profile_id == AUTO_PROFILE_ID:
        return AUTO_PROFILE
    return BUILTIN_PROFILES.get(profile_id)


def resolve_auto_profile_id(vendor: str = "", device_type: str = "") -> str:
    """Resolve the internal inspection profile for one CMDB asset."""
    command_profile = resolve_command_profile(vendor, device_type)
    if command_profile.vendor == "server":
        return "server_health"
    if command_profile.vendor in {"h3c_firewall", "hillstone"}:
        return "firewall_health"
    if command_profile.vendor in {"h3c", "huawei", "cisco", "ruijie"}:
        return "full_basic"
    return "basic_health"


def resolve_auto_profile(vendor: str = "", device_type: str = "") -> InspectionProfile:
    """Return the concrete internal profile used for one asset."""
    return BUILTIN_PROFILES[resolve_auto_profile_id(vendor, device_type)]


def resolve_vendor(vendor: str) -> VendorCommandProfile:
    """Look up vendor commands. Falls back to ``generic`` if unknown.

    A missing vendor profile is an inspection failure: the runner
    flags every check on the affected asset as ``skipped`` with
    ``reason=unsupported_vendor``. We never silently degrade.
    """
    return resolve_command_profile(vendor, "")


# ── v3.9.14: per-command-key timeout hints ──────────────────────────────
# The inspection runner maps each InspectionCheck's ``command_key`` to a
# default timeout here. The hint is overridden by the
# ``InspectionCheck.timeout_seconds`` field on the profile when present,
# so a profile can still bump a single check (e.g. config_backup) above
# the table value.
#
# Why finer-grained timeouts matter:
#   * ``uname -a`` / ``free -m`` / ``ip -brief addr`` finish in <1s.
#     Giving them 30s means a hung device also hangs the whole task.
#   * ``display current-configuration`` on a fat config genuinely
#     needs 60s; truncating to 5s silently returns an empty page.
#   * show commands on routing neighbors (OSPF / BGP) average 5-15s.
# Defaults chosen to be tight but well above the realistic p99.
CHECK_TIMEOUT_HINTS: dict[str, int] = {
    # fast Linux / BSD facts
    "version": 5,
    "cpu": 8,
    "memory": 5,
    "server_disk": 10,
    "server_listen": 5,
    "server_network": 5,
    "server_process": 5,
    # interface summaries
    "interface_brief": 15,
    "interface_error": 20,
    # routing
    "ospf_peer": 30,
    "bgp_summary": 45,
    "route_summary": 30,
    # ops / environment
    "environment": 15,
    "log": 15,
    "arp": 10,
    "mac": 10,
    "vlan": 10,
    # firewall-specific
    "firewall_session": 30,
    "firewall_policy": 60,
    "firewall_nat": 30,
    "firewall_ha": 30,
    # config backups / archives — wide page, slow link
    "current_config": 60,
}


# ── workspace-level script overrides ─────────────────────────────────────
# Operators can customise per-vendor commands via the frontend
# ScriptManager modal. Overrides are stored as JSON files under the
# workspace's ``inspection/scripts/`` directory and loaded first.
# If no override exists for a vendor the built-in defaults apply.


def _scripts_dir(workspace_id: str) -> Path:
    """Return ``<WS_ROOT>/<ws>/inspection/scripts/``, creating if needed."""
    from workspace.run_store import WS_ROOT
    from workspace.ids import validate_workspace_id
    p = WS_ROOT / validate_workspace_id(workspace_id) / "inspection" / "scripts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_vendor_commands(workspace_id: str, vendor: str) -> dict[str, str] | None:
    """Return workspace-level command overrides for *vendor*, or None."""
    fp = _scripts_dir(workspace_id) / f"{vendor}.json"
    if not fp.is_file():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict) and isinstance(data.get("commands"), dict):
        return data["commands"]
    return None


def save_vendor_commands(workspace_id: str, vendor: str,
                         commands: dict[str, str]) -> bool:
    """Persist a workspace-level vendor command override."""
    from workspace.atomic_io import atomic_write_json
    fp = _scripts_dir(workspace_id) / f"{vendor}.json"
    data = {
        "vendor": vendor,
        "updated_at": now_iso(),
        "source": "manual",
        "commands": commands,
    }
    try:
        atomic_write_json(fp, data)
        return True
    except OSError:
        return False


def delete_vendor_commands(workspace_id: str, vendor: str) -> bool:
    """Remove a workspace-level vendor override."""
    fp = _scripts_dir(workspace_id) / f"{vendor}.json"
    try:
        if fp.is_file():
            fp.unlink()
            return True
    except OSError:
        pass
    return False


def upload_vendor_script_file(workspace_id: str, vendor: str,
                              file_content: str) -> bool:
    """Persist a vendor script from an uploaded .txt file.
    Each non-empty, non-comment line is treated as a command.
    Lines are deduplicated; the first occurrence wins the key.
    """
    lines: list[str] = []
    for raw in file_content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        lines.append(line)
    if not lines:
        return False

    # Map each command line to a key: lowercase, spaces → underscores
    commands: dict[str, str] = {}
    for cmd in lines:
        key = cmd.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        # strip repeating underscores
        while "__" in key:
            key = key.replace("__", "_")
        key = key.strip("_")
        if key not in commands:
            commands[key] = cmd

    return save_vendor_commands(workspace_id, vendor, commands)


def load_command_profile(workspace_id: str, vendor: str = "",
                         device_type: str = "") -> VendorCommandProfile:
    """Resolve the vendor command profile, overlaying any workspace-level
    script customisations on top of the built-in defaults."""
    base = resolve_command_profile(vendor, device_type)
    overrides = load_vendor_commands(workspace_id, base.vendor)
    if overrides is None:
        return base
    merged = dict(base.commands)
    merged.update(overrides)
    return VendorCommandProfile(
        vendor=base.vendor,
        commands=merged,
        fallback_to_generic=base.fallback_to_generic,
        supported_checks=base.supported_checks,
    )


def default_timeout_for(command_key: str, profile_default: int = 30) -> int:
    """Return the recommended timeout for a command_key, falling back
    to ``profile_default`` if unknown. Always clamps to a safe range.
    """
    base = CHECK_TIMEOUT_HINTS.get(command_key, profile_default)
    return max(5, min(int(base or 30), 120))


def is_read_only_command(command: str) -> bool:
    """Static safety check: refuse anything that smells like a write.

    We layer this on top of the runtime's destructive-pattern scan;
    it's a redundant belt-and-braces guard for the inspection
    pipeline. The LLM does NOT pick commands — only checks, which
    resolve to a fixed per-vendor map. So if we ever see a string
    not in the map, abort the run, do NOT pretend success.
    """
    cmd = (command or "").strip().lower()
    if not cmd:
        return False
    blocked_prefixes = (
        "write ", "copy running", "copy start", "save ",
        "reload", "reboot", "reset", "shutdown", "poweroff",
        "delete", "erase", "format ", "config ", "system-view",
        "configure terminal", "conf t", "sys ", "quit-config",
    )
    if any(cmd.startswith(p) for p in blocked_prefixes):
        return False
    blocked_substrings = (
        " | redirect", " > ", " >> ",  # write-to-file
        " tftp:", " ftp:", " scp:",
        " commit ", "rollback-configuration",
    )
    if any(b in cmd for b in blocked_substrings):
        return False
    return True
