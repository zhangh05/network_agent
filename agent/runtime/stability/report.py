# agent/runtime/stability/report.py
"""StabilityReport — data model for stability gate output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StabilityReport:
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
