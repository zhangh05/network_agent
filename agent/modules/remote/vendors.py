# agent/modules/remote/vendors.py
"""Vendor profiles for device prompt detection and paging handling."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Pattern

@dataclass
class VendorProfile:
    vendor: str
    # Prompt regex patterns (ordered by specificity)
    prompts: list[str] = field(default_factory=list)
    # Paging indicators
    paging_patterns: list[str] = field(default_factory=list)
    # Paging response (space = next page, others for different behavior)
    paging_response: str = " "
    # Commands to run on connect to disable paging
    disable_paging_commands: list[str] = field(default_factory=list)
    # Commands to run on connect (e.g. terminal length 0)
    init_commands: list[str] = field(default_factory=list)

    def match_prompt(self, text: str) -> bool:
        for p in self.prompts:
            if re.search(p, text.rstrip()):
                return True
        return False

    def match_paging(self, text: str) -> bool:
        for p in self.paging_patterns:
            if re.search(p, text):
                return True
        return False


PROFILES: dict[str, VendorProfile] = {
    "h3c": VendorProfile(
        vendor="H3C",
        prompts=[
            r"<[\w\-\.]+>\s*$",
            r"\[[\w\-\.]+\]\s*$",
            r"<[\w\-\.]+>\s*\]\s*$",  # after more
        ],
        paging_patterns=[
            r"---- More ----",
            r"--- More ---",
        ],
        paging_response=" ",
        disable_paging_commands=["screen-length disable"],
        init_commands=["screen-length disable"],
    ),
    "huawei": VendorProfile(
        vendor="Huawei",
        prompts=[
            r"<[\w\-\.]+>\s*$",
            r"\[~?[\w\-\.]+\]\s*$",
            r"\[~?[\w\-\.]+-[a-zA-Z0-9\-]+\]\s*$",
        ],
        paging_patterns=[
            r"---- More ----",
            r"--- More ---",
        ],
        paging_response=" ",
        disable_paging_commands=["screen-length 0 temporary"],
        init_commands=["screen-length 0 temporary"],
    ),
    "cisco_ios": VendorProfile(
        vendor="Cisco IOS",
        prompts=[
            r"[\w\-\.]+>\s*$",          # user exec
            r"[\w\-\.]+#\s*$",          # privileged exec
            r"[\w\-\.]+\(config[^)]*\)#\s*$",  # config mode
        ],
        paging_patterns=[
            r"--More--",
            r"-- more --",
        ],
        paging_response=" ",
        disable_paging_commands=["terminal length 0"],
        init_commands=["terminal length 0"],
    ),
    "cisco_nxos": VendorProfile(
        vendor="Cisco NX-OS",
        prompts=[
            r"[\w\-\.]+>\s*$",
            r"[\w\-\.]+#\s*$",
            r"[\w\-\.]+\(config[^)]*\)#\s*$",
        ],
        paging_patterns=[
            r"--More--",
        ],
        paging_response=" ",
        disable_paging_commands=["terminal length 0"],
        init_commands=["terminal length 0"],
    ),
    "generic": VendorProfile(
        vendor="Generic",
        prompts=[
            r"[\w\-\.@]+[$#>%:]\s*$",
            r">\s*$",
            r"#\s*$",
        ],
        paging_patterns=[
            r"-- ?[Mm]ore ?--",
            r"---- ?[Mm]ore ?----",
        ],
        paging_response=" ",
        disable_paging_commands=[],
        init_commands=[],
    ),
}


def get_profile(vendor: str = "") -> VendorProfile:
    """Get vendor profile by name, fallback to generic."""
    key = (vendor or "").strip().lower()
    return PROFILES.get(key, PROFILES["generic"])


def list_vendors() -> list[dict]:
    return [
        {"key": k, "vendor": v.vendor}
        for k, v in PROFILES.items()
    ]
