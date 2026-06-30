"""agent.modules.inspection.models

Data models for the CMDB-driven inspection workflow.

The pipeline is:
    scope (region / type / vendor / tags / asset_ids)
    → automatic script selection by CMDB asset vendor + device type
    → vendor command profile (h3c / huawei / cisco / ruijie /
      hillstone / linux server / generic fallback)
    → per-asset remote execution through ``exec.run`` (asset_id,
      server-side credential resolution)
    → parsed metrics + findings + saved artifacts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ── scope ──────────────────────────────────────────────────────────────────

@dataclass
class InspectionScope:
    """Filter on top of the CMDB list_assets() result.

    All fields are optional — an empty scope plus ``asset_ids`` is
    a legal "just these N assets" call. ``limit`` caps how many
    assets are inspected in a single run so a CMDB-wide scope
    doesn't accidentally target hundreds of devices.
    """

    region: str = ""
    location: str = ""
    type: str = ""
    vendor: str = ""
    tags: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    limit: int = 50

    def is_empty(self) -> bool:
        return not any([
            self.region, self.location, self.type, self.vendor,
            self.tags, self.asset_ids,
        ])


# ── profile & checks ────────────────────────────────────────────────────────

# Severity buckets the parser / report can produce
SEVERITY_LEVELS = ("critical", "warning", "info")
Severity = str  # union of above; kept loose for JSON friendliness

CheckCategory = str  # health | interface | routing | config | security


@dataclass
class InspectionCheck:
    """A single read-only command to run against an asset.

    The ``command_key`` is what we look up in ``VendorCommandProfile``;
    the ``parser_key`` is matched by ``parser.py`` to extract metrics.
    """

    check_id: str
    category: CheckCategory
    display_name: str
    command_key: str
    parser_key: str = ""
    severity_default: Severity = "info"
    timeout_seconds: int = 30


@dataclass
class InspectionProfile:
    """A named bundle of checks (one of the MVP profiles)."""

    profile_id: str
    display_name: str
    description: str
    checks: tuple[InspectionCheck, ...]
    risk_level: str = "low"  # all read-only; we never escalate above medium
    requires_approval: bool = False


# ── vendor profile ────────────────────────────────────────────────────────

@dataclass
class VendorCommandProfile:
    """Vendor-specific command templates for an inspection check.

    ``commands`` is keyed by ``check.command_key``. Missing keys
    mean the vendor doesn't support that check — the runner
    will record the check as ``skipped`` with ``not_supported``.
    """

    vendor: str
    commands: dict[str, str]
    # When a vendor doesn't fully support a check, fall back to the
    # commands here and mark the run ``limited_support``.
    fallback_to_generic: bool = False
    supported_checks: tuple[str, ...] = ()


# ── run state ─────────────────────────────────────────────────────────────

@dataclass
class CommandResult:
    """Per-check execution record on a single asset."""

    check_id: str
    category: CheckCategory
    command_key: str
    command: str = ""         # actual command sent; useful for evidence
    ok: bool = False
    output_snippet: str = ""  # first ~800 chars; full output is the artifact
    artifact_id: str = ""
    elapsed_ms: int = 0
    error: str = ""           # only set when ``ok`` is False
    parsed_metric: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    """A classified observation produced by a parser."""

    finding_id: str
    severity: Severity  # critical | warning | info
    title: str
    detail: str = ""
    evidence: str = ""       # command + snippet
    asset_id: str = ""
    check_id: str = ""


@dataclass
class DeviceResult:
    """All data captured for one asset across one inspection run."""

    task_id: str
    asset_id: str
    asset_name: str = ""
    host: str = ""
    region: str = ""
    location: str = ""
    vendor: str = ""
    type: str = ""
    protocol: str = ""
    status: str = "pending"   # pending|running|succeeded|failed|skipped
    supported: bool = True   # False when no vendor profile matches
    limited_support: bool = False
    script_profile_id: str = ""
    script_profile_name: str = ""
    command_results: list[CommandResult] = field(default_factory=list)
    parsed_metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


@dataclass
class InspectionTask:
    """Top-level run state. One task inspects N assets serially."""

    task_id: str
    workspace_id: str
    scope: InspectionScope
    profile_id: str
    profile_display_name: str = ""
    status: str = "pending"   # pending|running|succeeded|partial|failed|cancelled
    started_at: str = ""
    finished_at: str = ""
    total_assets: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    warnings: int = 0
    criticals: int = 0
    infos: int = 0
    created_by: str = ""      # user / subagent / inspection_runner etc.
    session_id: str = ""
    max_concurrency: int = 3
    devices: dict[str, DeviceResult] = field(default_factory=dict)
    error: str = ""
