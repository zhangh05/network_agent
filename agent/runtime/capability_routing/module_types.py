# agent/runtime/capability_routing/module_types.py
"""Module type classification — business vs platform."""

from __future__ import annotations

BUSINESS_MODULES = {
    "config_translation",
    "config_analysis",
    "pcap_analysis",
}

PLATFORM_SERVICES = {
    "workspace",
    "knowledge",
    "memory",
    "artifact",
    "runtime",
    "report",
    "web",
}


def is_business_module(module_id: str) -> bool:
    return module_id in BUSINESS_MODULES


def is_platform_service(module_id: str) -> bool:
    return module_id in PLATFORM_SERVICES
