# agent/runtime/stability/checks.py
"""StabilityChecks — individual check functions for core stability gate."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str = ""
    passed: bool = True
    details: str = ""


_REQUIRED_METADATA_KEYS = [
    "runtime_state_snapshot",
    "task_signal",
    "action_trace",
    "artifact_records",
    "output_summary",
    "final_response",
    "turn_trace",
]

_OLD_STAGE_PATTERNS = [
    re.compile(r"self\._permission\.run"),
    re.compile(r"self\._risk\.run"),
    re.compile(r"self\._approval\.run"),
    re.compile(r"self\._dispatch\.run"),
]

_RESIDUE_PATTERNS = [
    re.compile(r"\balias\s+wrapper\b", re.IGNORECASE),
    re.compile(r"\binactive\s+wrapper\b", re.IGNORECASE),
]


def check_required_metadata(ctx) -> CheckResult:
    """Check that all required metadata keys are present."""
    missing = [k for k in _REQUIRED_METADATA_KEYS if k not in ctx.metadata]
    if missing:
        return CheckResult(
            name="required_metadata",
            passed=False,
            details=f"Missing metadata keys: {', '.join(missing)}",
        )
    return CheckResult(name="required_metadata", passed=True, details="All required metadata present")


def check_no_old_stage_chain(source_dir: str = "") -> CheckResult:
    """Check that old tool stage chain patterns are not in pipeline code."""
    if not source_dir:
        return CheckResult(name="no_old_stage_chain", passed=True, details="Skipped (no source_dir)")
    target = os.path.join(source_dir, "agent", "runtime", "tool_execution", "pipeline.py")
    if not os.path.exists(target):
        return CheckResult(name="no_old_stage_chain", passed=True, details="pipeline.py not found (ok)")
    try:
        content = open(target, "r", encoding="utf-8").read()
    except Exception as exc:
        return CheckResult(name="no_old_stage_chain", passed=False, details=f"Read error: {exc}")
    for pat in _OLD_STAGE_PATTERNS:
        m = pat.search(content)
        if m:
            return CheckResult(
                name="no_old_stage_chain",
                passed=False,
                details=f"Old stage pattern found: {m.group()}"
            )
    return CheckResult(name="no_old_stage_chain", passed=True, details="No old stage patterns in pipeline")


def check_no_runtime_residue(source_dir: str = "", dirs: list[str] | None = None) -> CheckResult:
    """Check that no inactive wrapper residue exists in runtime modules."""
    if not source_dir:
        return CheckResult(name="no_runtime_residue", passed=True, details="Skipped (no source_dir)")
    target_dirs = dirs or [
        "agent/runtime/output",
        "agent/runtime/response",
        "agent/runtime/memory_write",
        "agent/runtime/observability",
        "agent/runtime/truth",
        "agent/runtime/stability",
    ]
    hits: list[str] = []
    _self_file = os.path.basename(__file__)
    for d in target_dirs:
        full = os.path.join(source_dir, d)
        if not os.path.isdir(full):
            continue
        for fname in os.listdir(full):
            if not fname.endswith(".py"):
                continue
            if fname == _self_file and d.endswith("stability"):
                continue  # skip self — pattern definitions live here
            fpath = os.path.join(full, fname)
            try:
                content = open(fpath, "r", encoding="utf-8").read()
            except Exception:
                continue
            for pat in _RESIDUE_PATTERNS:
                m = pat.search(content)
                if m:
                    hits.append(f"{d}/{fname}: {m.group()}")
    if hits:
        return CheckResult(
            name="no_runtime_residue",
            passed=False,
            details=f"Runtime residue found: {'; '.join(hits[:5])}",
        )
    return CheckResult(name="no_runtime_residue", passed=True, details="No inactive wrapper residue")


def check_kernel_reports(ctx) -> CheckResult:
    """Check that all finalization kernel reports can be found in metadata."""
    expected = [
        "artifact_records",
        "output_summary",
        "final_response",
        "memory_write_plan",
        "turn_trace",
        "truth_report",
    ]
    missing = [k for k in expected if k not in ctx.metadata]
    if missing:
        return CheckResult(
            name="kernel_reports",
            passed=False,
            details=f"Missing kernel reports: {', '.join(missing)}",
        )
    return CheckResult(name="kernel_reports", passed=True, details="All kernel reports present")
