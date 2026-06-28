# runtime/selfcheck.py
"""Runtime selfcheck — consistency validation across workspace, run, job, artifact, trace.

Only reads and validates structure. Never modifies data.
Never reads full sensitive content. Never exposes absolute paths.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


class SelfcheckStatus:
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class SelfcheckIssue:
    severity: str = "info"  # info | warning | error | critical
    code: str = ""
    message: str = ""
    ref_id: str = ""
    suggested_action: str = ""

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "ref_id": self.ref_id,
            "suggested_action": self.suggested_action,
        }


@dataclass
class SelfcheckResult:
    status: str = SelfcheckStatus.HEALTHY
    issues: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "issues": [i.as_dict() for i in self.issues],
            "checks": self.checks,
        }


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _safe_list_dir(path: Path) -> list:
    try:
        return [p for p in path.iterdir() if not p.name.startswith(".")]
    except Exception:
        return []


def run_selfcheck(workspace_id: str = "default") -> SelfcheckResult:
    """Run full selfcheck for a workspace. Returns structured result."""
    result = SelfcheckResult()
    run_checks(result, workspace_id)
    # Determine overall status
    severities = {i.severity for i in result.issues}
    if "critical" in severities:
        result.status = SelfcheckStatus.FAILED
    elif "error" in severities:
        result.status = SelfcheckStatus.DEGRADED
    elif "warning" in severities:
        result.status = SelfcheckStatus.WARNING
    return result


def run_checks(result: SelfcheckResult, ws_id: str):
    """Execute all selfcheck checks. Appends issues to result."""
    ws_dir = WS_ROOT / ws_id

    # 1. Workspace root exists
    if not ws_dir.exists():
        result.issues.append(SelfcheckIssue("error", "WS_ROOT_MISSING",
            f"Workspace '{ws_id}' not found", ws_id, "Create workspace first"))
        result.checks["workspace_root"] = "missing"
        return  # Cannot proceed without workspace
    result.checks["workspace_root"] = "ok"

    # 2. State file
    state_file = ws_dir / "sys" / "state.json"
    state = _safe_read_json(state_file)
    result.checks["state_json"] = "ok" if state else "missing"

    # 3. Runs directory
    runs_dir = ws_dir / "runs"
    run_files = _safe_list_dir(runs_dir) if runs_dir.is_dir() else []
    result.checks["runs_count"] = len(run_files)
    for rf in run_files[:20]:  # Check first 20
        record = _safe_read_json(rf)
        if record is None:
            result.issues.append(SelfcheckIssue("warning", "RUN_JSON_INVALID",
                f"Run record not parseable: {rf.name}", rf.name[:12],
                "Remove or repair the run record"))

    # 4. Artifacts directory
    art_dir = ws_dir / "files"
    art_files = _safe_list_dir(art_dir) if art_dir.is_dir() else []
    result.checks["artifacts_count"] = len(art_files)
    for af in art_files[:20]:
        record = _safe_read_json(af)
        if record is None and af.suffix == ".json":
            result.issues.append(SelfcheckIssue("warning", "ARTIFACT_JSON_INVALID",
                f"Artifact record not parseable: {af.name}", af.name[:12],
                "Remove or repair the artifact record"))

    # 5. Jobs directory
    jobs_dir = ws_dir / "jobs"
    job_files = _safe_list_dir(jobs_dir) if jobs_dir.is_dir() else []
    result.checks["jobs_count"] = len(job_files)

    # 6. Cross-reference: artifact refs in recent runs
    for rf in run_files[:10]:
        record = _safe_read_json(rf)
        if not record:
            continue
        art_refs = record.get("artifact_refs", []) or []
        for ref in art_refs:
            art_id = ref.get("artifact_id", "") if isinstance(ref, dict) else str(ref)
            art_path = art_dir / f"{art_id}.json" if not art_id.endswith(".json") else art_dir / art_id
            if not art_path.is_file():
                result.issues.append(SelfcheckIssue("warning", "ARTIFACT_REF_MISSING",
                    f"Run {rf.stem[:12]} references missing artifact {art_id}",
                    art_id[:12], "The artifact may have been removed"))

    # 7. Cross-reference: job refs in runs
    for rf in run_files[:10]:
        record = _safe_read_json(rf)
        if not record:
            continue
        job_refs = record.get("job_refs", []) or []
        for jr in job_refs:
            job_id = jr if isinstance(jr, str) else jr.get("job_id", "")
            job_path = jobs_dir / f"{job_id}.json"
            if not job_path.is_file():
                result.issues.append(SelfcheckIssue("info", "JOB_REF_MISSING",
                    f"Run {rf.stem[:12]} references job {job_id} but not found",
                    job_id[:12], "Job may be in different workspace"))

    # 8. Path safety: no absolute paths in run records
    for rf in run_files[:10]:
        record = _safe_read_json(rf)
        if not record:
            continue
        record_str = json.dumps(record)
        if "/Users/" in record_str or "/home/" in record_str:
            result.issues.append(SelfcheckIssue("warning", "ABSOLUTE_PATH",
                f"Run record {rf.stem} contains absolute path", rf.stem[:12],
                "Redact absolute paths"))

    # 9. quality_summary structure
    for rf in run_files[:10]:
        record = _safe_read_json(rf)
        if not record:
            continue
        qs = record.get("quality_summary", {})
        if isinstance(qs, dict) and qs:
            for field in ("source_residue_count", "silent_drop_count"):
                if field in qs and not isinstance(qs[field], int):
                    result.issues.append(SelfcheckIssue("warning", "QUALITY_SUMMARY_TYPE",
                        f"quality_summary.{field} is not int in {rf.stem[:12]}",
                        rf.stem[:12], "Fix quality_summary format"))

    # 10. Verify enabled modules — accept any valid module set, warn on empty
    try:
        from registry.loader import load_module_registry
        mods = load_module_registry()
        enabled = sorted([m.module_name for m in mods if m.is_enabled()])
        if not enabled:
            result.issues.append(SelfcheckIssue("warning", "MODULE_COUNT",
                "No enabled modules found", "",
                "Enable at least one module in registry"))
        result.checks["enabled_modules"] = enabled
    except Exception:
        result.issues.append(SelfcheckIssue("warning", "REGISTRY_UNAVAILABLE",
            "Registry loader failed", "", "Check registry files"))

    # 11. Forbidden API not restored
    try:
        main_py = (ROOT / "backend" / "main.py").read_text()
        if "/api/translate" in main_py and "route(" in main_py:
            result.issues.append(SelfcheckIssue("critical", "FORBIDDEN_API",
                "/api/translate found in backend", "",
                "Immediately remove /api/translate route"))
        result.checks["forbidden_api"] = "ok"
    except Exception:
        result.checks["forbidden_api"] = "unavailable"

    # 12. No absolute path leak in trace metadata
    trace_dir = ws_dir / "traces"
    if trace_dir.is_dir():
        for tf in _safe_list_dir(trace_dir)[:10]:
            record = _safe_read_json(tf)
            if record:
                record_str = json.dumps(record)
                if "/Users/" in record_str or "/home/" in record_str:
                    result.issues.append(SelfcheckIssue("warning", "TRACE_PATH_LEAK",
                        f"Trace record {tf.stem} contains absolute path", tf.stem[:12],
                        "Redact absolute paths from trace metadata"))

    # 13. Tool Runtime current policy/governance summary
    # v3.9.3: tool_governance module removed. All 21 canonical tools are
    # active by default. V02_FORBIDDEN_TOOLS is a separate historical
    # policy blacklist (tool names that should never be invoked) — it
    # is NOT a subset of the canonical registry.
    try:
        from tool_runtime.canonical_registry import CANONICAL_REGISTRY
        from tool_runtime.policy import V02_FORBIDDEN_TOOLS

        result.checks["tool_runtime"] = "ok"
        result.checks["tool_registered_count"] = len(CANONICAL_REGISTRY)
        result.checks["tool_forbidden_count"] = len(V02_FORBIDDEN_TOOLS)
        result.checks["tool_forbidden_list"] = sorted(V02_FORBIDDEN_TOOLS)
        result.checks["tool_governance"] = {
            "active": len(CANONICAL_REGISTRY),
            "disabled": 0,
            "internal": 0,
            "forbidden": 0,
        }
    except Exception:
        result.checks["tool_runtime"] = "unavailable"
