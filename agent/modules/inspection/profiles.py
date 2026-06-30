"""agent.modules.inspection.profiles

Built-in ``InspectionProfile`` and ``VendorCommandProfile``
registries. The MVP focus is H3C, Huawei, Cisco. ``generic`` is
a last-resort fallback (only very-safe read-only commands).

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

from .models import (
    InspectionCheck,
    InspectionProfile,
    VendorCommandProfile,
)


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


# ── builtin inspection profiles (MVP) ──────────────────────────────────────

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
    }  # end BUILTIN_PROFILES (declared above)

# ``full_basic`` aliases the union of basic + interface + routing.
BUILTIN_PROFILES["full_basic"] = InspectionProfile(
    profile_id="full_basic",
    display_name="综合巡检（基础 + 接口 + 路由）",
    description="等价于 basic_health + interface_health + routing_health。",
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
            CK_CURRENT_CONFIG,
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
        },
    ),
    "huawei": VendorCommandProfile(
        vendor="huawei",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG,
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
        },
    ),
    "cisco": VendorCommandProfile(
        vendor="cisco",
        supported_checks=(
            CK_VERSION, CK_CPU, CK_MEMORY,
            CK_INTERFACE_BRIEF, CK_INTERFACE_ERROR,
            CK_OSPF_PEER, CK_BGP_SUMMARY, CK_ROUTE_SUMMARY,
            CK_CURRENT_CONFIG,
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


def resolve_profile(profile_id: str) -> InspectionProfile | None:
    """Return the profile or None if the id is unknown."""
    return BUILTIN_PROFILES.get(profile_id)


def resolve_vendor(vendor: str) -> VendorCommandProfile:
    """Look up vendor commands. Falls back to ``generic`` if unknown.

    A missing vendor profile is an inspection failure: the runner
    flags every check on the affected asset as ``skipped`` with
    ``reason=unsupported_vendor``. We never silently degrade.
    """
    if not vendor:
        return VENDOR_COMMAND_PROFILES["generic"]
    v = vendor.strip().lower()
    if v in VENDOR_COMMAND_PROFILES:
        return VENDOR_COMMAND_PROFILES[v]
    return VENDOR_COMMAND_PROFILES["generic"]


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
