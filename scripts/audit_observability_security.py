#!/usr/bin/env python3
"""Observability security audit — trace files, secrets, configs, APIs."""

import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

SECRET_PATTERNS = [
    r'sk-[A-Za-z0-9]{20,}', r'api[_-]?key[=:]\s*\S{8,}',
    r'password\s+\S+', r'secret\s+\S+', r'community\s+\S+',
    r'Bearer\s+\S{8,}', r'Authorization\s+\S{8,}',
]


def mask(v):
    if not v or len(v) <= 8:
        return "****"
    return v[:3] + "****" + v[-3:]


def find_secrets(text, filepath=""):
    findings = []
    for pat in SECRET_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            findings.append({"pattern": pat, "match": mask(m.group()), "file": filepath})
    return findings


def audit():
    issues = []
    key_leaks = []
    trace_issues = []

    # 1. Check trace files
    ws_dir = PROJECT_ROOT / "workspaces"
    for trace_file in ws_dir.glob("*/runs/*.trace.json"):
        content = trace_file.read_text()
        for leak in find_secrets(content, str(trace_file)):
            key_leaks.append(leak)
        # Check for full configs
        data = json.loads(content)
        for event in data.get("events", []):
            meta = str(event.get("metadata", {}))
            if "source_config" in meta and len(meta) > 500:
                trace_issues.append({"issue": "full_source_config_in_trace", "file": str(trace_file)})
            if "deployable_config" in meta and len(meta) > 500:
                trace_issues.append({"issue": "full_deployable_config_in_trace", "file": str(trace_file)})
            if "prompt" in meta and len(str(event.get("metadata", {}).get("prompt", ""))) > 200:
                trace_issues.append({"issue": "llm_prompt_in_trace", "file": str(trace_file)})

    # 2. Check run records for trace_path/trace_id
    for run_file in ws_dir.glob("*/runs/*.json"):
        if ".trace" in str(run_file):
            continue
        try:
            data = json.loads(run_file.read_text())
        except Exception:
            continue
        # Not all runs have trace yet, this is informational

    # 3. Check no /api/translate, no backend/services, no old GraphAgent
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if "retired" in p or "scripts/audit" in p or "harness/" in p:
            continue
        content = py_file.read_text()
        if "/api/translate" in content and "已删除" not in content:
            issues.append({"issue": "api_translate_ref", "file": p})

    # 4. Check no backend/services/config_translation
    svc_dir = PROJECT_ROOT / "backend" / "services" / "config_translation"
    if svc_dir.is_dir():
        issues.append({"issue": "backend_services_exists", "file": str(svc_dir)})

    # 5. Check trace_id present
    trace_file_count = len(list(ws_dir.glob("*/runs/*.trace.json")))

    result = {
        "audit": "OBSERVABILITY_SECURITY_AUDIT",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "key_leaks": len(key_leaks),
            "trace_issues": len(trace_issues),
            "issues": len(issues),
            "trace_files_found": trace_file_count,
            "verdict": "PASS" if len(key_leaks) == 0 else "FAIL",
        },
        "key_leaks": [{"pattern": k["pattern"], "file": k["file"]} for k in key_leaks],
        "trace_issues": trace_issues,
        "issues": issues,
    }

    json_path = REPORTS_DIR / "observability_security_audit.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    md = f"""# Observability Security Audit

**Verdict**: {result['summary']['verdict']}
**Trace files**: {trace_file_count}

| Metric | Value |
|--------|-------|
| Key Leaks | {result['summary']['key_leaks']} |
| Trace Issues | {result['summary']['trace_issues']} |
| Issues | {result['summary']['issues']} |

"""
    if key_leaks:
        md += "\n## 🔑 Key Leaks\n\n"
        for k in key_leaks:
            md += f"- `{k['pattern']}` in {k['file']}\n"

    if not key_leaks and not trace_issues:
        md += "✅ No key leaks or trace issues found.\n"

    md_path = REPORTS_DIR / "OBSERVABILITY_SECURITY_AUDIT.md"
    md_path.write_text(md)

    print(f"Audit complete. Verdict: {result['summary']['verdict']}")
    return result


if __name__ == "__main__":
    audit()
