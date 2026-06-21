# agent/runtime/stability/gate.py
"""StabilityGate — runs all stability checks and produces a stability report."""

from __future__ import annotations

from agent.runtime.stability.checks import (
    check_kernel_reports,
    check_no_runtime_residue,
    check_no_old_stage_chain,
    check_required_metadata,
)
from agent.runtime.stability.report import StabilityReport


class StabilityGate:
    """Run all stability checks and write a report to ctx.metadata."""

    def check(self, ctx, *, source_dir: str = "") -> StabilityReport:
        results = [
            check_required_metadata(ctx),
            check_no_old_stage_chain(source_dir=source_dir),
            check_no_runtime_residue(source_dir=source_dir),
            check_kernel_reports(ctx),
        ]

        passed = all(r.passed for r in results)
        warnings = [r.details for r in results if not r.passed]

        report = StabilityReport(
            passed=passed,
            checks=[
                {
                    "name": r.name,
                    "passed": r.passed,
                    "details": r.details,
                }
                for r in results
            ],
            warnings=warnings,
        )

        ctx.metadata["stability_report"] = {
            "passed": report.passed,
            "check_count": len(report.checks),
            "checks": report.checks,
            "warnings": report.warnings,
        }
        return report
