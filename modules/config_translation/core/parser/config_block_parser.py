# -*- coding: utf-8 -*-
"""Config block parser v1 — structural decomposition of network config into blocks.

Produces ConfigBlock objects for downstream typed IR parsing.
Does not alter translation output — only structural partitioning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BLOCK_HEADERS = {
    "interface": re.compile(
        r"^interface\s+(GigabitEthernet|Ten-GigabitEthernet|FastEthernet|Ethernet|"
        r"Vlanif|Vlan-interface|Vlan|LoopBack|Loopback|Port-channel|Eth-Trunk|Bridge-Aggregation|"
        r"AggregatePort|Tunnel|Null0|Serial|Mgmt|MEth|GE|XGE|HundredGigE|"
        r"Gi\d/\d|G\d/\d|Te\d/\d|Eth\d/\d|Fa\d/\d|Po\d+)\S*",
        re.IGNORECASE,
    ),
    "vlan": re.compile(r"^vlan\s+(\d+|batch)", re.IGNORECASE),
    "routing_process": re.compile(
        r"^(router\s+(ospf|bgp|isis|rip)|ospf\s+\d+|bgp\s+\d+|isis\s+\S+|rip\s+\S+)",
        re.IGNORECASE,
    ),
    "acl": re.compile(r"^(ip\s+access-list|acl\s+(number\s+)?\d+|access-list\s+\d+)", re.IGNORECASE),
    "firewall_policy": re.compile(
        r"^(security-policy|policy\s+name|nat-policy|ipsec\s+policy|ike\s+)",
        re.IGNORECASE,
    ),
}

BLOCK_END_HEADERS = re.compile(
    r"^(interface\s+|router\s+(ospf|bgp|isis|rip)|ospf\s+\d+|bgp\s+\d+|"
    r"ip\s+access-list|acl\s+|access-list\s+\d+|security-policy|"
    r"vlan\s+|nat-policy|ipsec\s+policy|ike\s+|policy\s+name)",
    re.IGNORECASE,
)

BLOCK_CONTINUATION = re.compile(
    r"^\s+(.+)|^(rule\s+|source-zone|destination-zone|action\s+|"
    r"service\s+|port\s+|ip\s+address|mask\s+|undo\s+|no\s+)",
    re.IGNORECASE,
)


@dataclass
class ConfigBlock:
    """A contiguous block of config lines with a header and body."""
    block_type: str
    header: str
    lines: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    indent_style: str = ""
    vendor_hint: str = ""

    @property
    def body_lines(self) -> list[str]:
        return self.lines[1:] if len(self.lines) > 1 else []

    @property
    def all_lines(self) -> list[str]:
        return self.lines


def _identify_block_type(stripped: str) -> str:
    for btype, pattern in BLOCK_HEADERS.items():
        if pattern.match(stripped):
            return btype
    return "unknown"


def parse_config_blocks(config_text: str, vendor: str = "") -> list[ConfigBlock]:
    """Parse config text into structured ConfigBlock objects.

    Args:
        config_text: Raw multi-line config
        vendor: Optional vendor hint for block interpretation

    Returns:
        List of ConfigBlock in source order
    """
    raw_lines = config_text.splitlines()
    blocks: list[ConfigBlock] = []
    current_block: ConfigBlock | None = None

    for i, raw in enumerate(raw_lines):
        line_no = i + 1
        stripped = raw.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith(("#", "!")):
            continue

        btype = _identify_block_type(stripped)

        if btype != "unknown":
            # New block header found — close previous and start new
            if current_block is not None:
                current_block.end_line = i
                blocks.append(current_block)
            current_block = ConfigBlock(
                block_type=btype, header=stripped,
                lines=[raw], start_line=line_no,
                vendor_hint=vendor,
            )
        elif current_block is not None and BLOCK_CONTINUATION.match(raw):
            # Continuation line within current block
            current_block.lines.append(raw)
        elif current_block is not None and BLOCK_END_HEADERS.match(stripped):
            # This might be a new block — but _identify_block_type said unknown
            # Could be a sub-header within a block (e.g. "rule name" inside firewall_policy)
            current_block.lines.append(raw)
        else:
            # Standalone line that doesn't match any block header or known continuation.
            # If it starts at column 0 (not indented) and the current block is a vlan/routing
            # block whose sub-commands are typically indented, close the current block.
            starts_at_col0 = raw and raw[0] not in (' ', '\t')
            if current_block is not None and starts_at_col0 and current_block.block_type in ("vlan",):
                # Non-indented line in a vlan block context — likely a new global command
                current_block.end_line = i
                blocks.append(current_block)
                current_block = ConfigBlock(
                    block_type="global", header=stripped,
                    lines=[raw], start_line=line_no, vendor_hint=vendor,
                )
            elif current_block is not None:
                current_block.lines.append(raw)
            else:
                current_block = ConfigBlock(
                    block_type="global", header=stripped,
                    lines=[raw], start_line=line_no,
                    vendor_hint=vendor,
                )

    # Close final block
    if current_block is not None:
        current_block.end_line = len(raw_lines)
        blocks.append(current_block)

    return blocks
