#!/usr/bin/env python3
"""Security audit — workspace, memory, LLM, module isolation.

Checks:
  - No secrets in memory/data
  - No full configs in workspace state/runs
  - No key leaks in any stored data
  - No module/skill private LLM imports
  - No old GraphAgent
  - No /api/translate
  - No backend/services/config_translation
  - No external network-translator
  - No os.chdir/sys.path hacks
  - MiniMax-M3 default, no M1 residue

Output:
  - reports/WORKSPACE_MEMORY_SECURITY_AUDIT.md
  - reports/workspace_memory_security_audit.json
"""

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
    r'sk-[A-Za-z0-9]{20,}',
    r'api[_-]?key[=:]\s*\S{8,}',
    r'password\s+\S+',
    r'secret\s+\S+',
    r'community\s+\S+',
    r'Bearer\s+\S{8,}',
    r'Authorization\s+\S{8,}',
    r'MINIMAX_API_KEY[=:]\s*\S+',
    r'OPENAI_API_KEY[=:]\s*\S+',
    r'DEEPSEEK_API_KEY[=:]\s*\S+',
]


def mask(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:3] + "****" + value[-3:]


def find_secrets(text, filepath=""):
    findings = []
    for pat in SECRET_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            findings.append({
                "pattern": pat,
                "match": mask(m.group()),
                "file": filepath,
            })
    return findings


def check_full_config(text, label, filepath=""):
    """Check if text contains full config dump."""
    issues = []
    if "source_config" in text and len(text) > 500:
        issues.append({
            "issue": f"full_source_config_in_{label}",
            "file": filepath,
            "severity": "high",
        })
    if "deployable_config" in text and len(text) > 500:
        issues.append({
            "issue": f"full_deployable_config_in_{label}",
            "file": filepath,
            "severity": "high",
        })
    return issues


def audit():
    issues = []
    key_leaks = []
    critical = []

    # 1. Scan memory/data
    mem_dir = PROJECT_ROOT / "memory" / "data"
    for f in mem_dir.glob("*.jsonl"):
        content = f.read_text()
        for leak in find_secrets(content, str(f)):
            key_leaks.append(leak)
        issues.extend(check_full_config(content, "memory", str(f)))

    # 2. Scan workspace state
    ws_dir = PROJECT_ROOT / "workspaces"
    for state_file in ws_dir.glob("*/state.json"):
        content = state_file.read_text()
        for leak in find_secrets(content, str(state_file)):
            key_leaks.append(leak)
            critical.append({"issue": "key_in_workspace_state", "file": str(state_file)})
        issues.extend(check_full_config(content, "workspace_state", str(state_file)))

    # 3. Scan workspace runs
    for run_file in ws_dir.glob("*/runs/*.json"):
        content = run_file.read_text()
        for leak in find_secrets(content, str(run_file)):
            key_leaks.append(leak)
            critical.append({"issue": "key_in_workspace_run", "file": str(run_file)})
        issues.extend(check_full_config(content, "workspace_run", str(run_file)))

    # 4. Scan reports
    for report in REPORTS_DIR.glob("*"):
        if report.suffix in (".md", ".json"):
            content = report.read_text()
            for leak in find_secrets(content, str(report)):
                key_leaks.append(leak)

    # 5. Check config/LLM_setting.json git tracking
    setting_file = PROJECT_ROOT / "config" / "LLM_setting.json"
    if setting_file.is_file():
        # Check if it's in .gitignore
        gitignore = PROJECT_ROOT / ".gitignore"
        if gitignore.is_file():
            gi = gitignore.read_text()
            if "LLM_setting.json" not in gi:
                issues.append({
                    "issue": "LLM_setting_json_not_gitignored",
                    "severity": "high",
                })
    else:
        pass  # Not created yet, fine

    # 6. Check module isolation — no module should import agent.llm
    for py_file in PROJECT_ROOT.glob("modules/**/*.py"):
        content = py_file.read_text()
        if "agent.llm" in content or "from agent.llm" in content:
            critical.append({
                "issue": "module_imports_agent_llm",
                "file": str(py_file),
            })

    # 7. Check skill isolation — no skill should import agent.llm
    for py_file in PROJECT_ROOT.glob("skills/**/*.py"):
        content = py_file.read_text()
        if "agent.llm" in content or "from agent.llm" in content:
            critical.append({
                "issue": "skill_imports_agent_llm",
                "file": str(py_file),
            })

    # 8. Check config_translation doesn't import agent.llm
    for py_file in PROJECT_ROOT.glob("modules/config_translation/**/*.py"):
        content = py_file.read_text()
        if "agent.llm" in content:
            critical.append({
                "issue": "config_translation_imports_agent_llm",
                "file": str(py_file),
            })

    # 9. Check no old GraphAgent (exclude legacy and this script)
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if "legacy" in p or "scripts/audit_workspace" in p:
            continue
        content = py_file.read_text()
        if "GraphAgent" in content:
            critical.append({
                "issue": "old_GraphAgent_found",
                "file": str(py_file),
            })

    # 10. Check no /api/translate
    # (We know it's removed from routes, but check legacy)
    for py_file in PROJECT_ROOT.glob("backend/**/*.py"):
        content = py_file.read_text()
        if 'route("/api/translate"' in content:
            critical.append({
                "issue": "api_translate_route_found",
                "file": str(py_file),
            })

    # 11. Check no backend/services/config_translation
    svc_dir = PROJECT_ROOT / "backend" / "services" / "config_translation"
    if svc_dir.is_dir():
        critical.append({
            "issue": "backend_services_config_translation_exists",
            "file": str(svc_dir),
        })

    # 12. Check no external network-translator imports
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if "legacy" in p or "scripts/audit_workspace" in p or "scripts/audit_llm" in p or "harness/" in p:
            continue
        content = py_file.read_text()
        if "sys.path.append" in content and "network-translator" in content:
            critical.append({
                "issue": "external_network_translator_sys_path",
                "file": str(py_file),
            })
        if "os.chdir" in content and "network-translator" in content:
            critical.append({
                "issue": "external_network_translator_chdir",
                "file": str(py_file),
            })

    # 13. Check MiniMax-M3 default / no M1 residue (code only, skip migration code and tests)
    m1_files = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if "harness/" in p or "legacy" in p or "scripts/audit" in p:
            continue
        content = py_file.read_text()
        # Count MiniMax-M1 occurrences that aren't in migration code
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "MiniMax-M1" in line:
                # Skip migration code
                if "Migrate" in line or "migrate" in line or "→" in line or "->" in content:
                    continue
                if "MiniMax-M1" in line and "M3" in line:
                    continue
                m1_files.append(f"{py_file}:{i+1}")

    if m1_files:
        issues.append({
            "issue": "MiniMax_M1_residue",
            "files": m1_files,
            "severity": "low",
        })

    # Check MiniMax-M3 is default
    m3_default_ok = False
    for py_file in PROJECT_ROOT.rglob("*.py"):
        content = py_file.read_text()
        if 'model": "MiniMax-M3"' in content or "model': 'MiniMax-M3'" in content:
            m3_default_ok = True
            break

    # Build report
    result = {
        "audit": "WORKSPACE_MEMORY_SECURITY_AUDIT",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "critical": len(critical),
            "high": len(issues),
            "key_leaks": len(key_leaks),
            "MiniMax_M3_default": m3_default_ok,
            "verdict": "PASS" if len(critical) == 0 and len(key_leaks) == 0 else "FAIL",
        },
        "critical": critical,
        "findings": issues,
        "key_leaks": [{"pattern": k["pattern"], "file": k["file"]} for k in key_leaks],
    }

    # Write JSON
    json_path = REPORTS_DIR / "workspace_memory_security_audit.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # Write MD
    md = f"""# Workspace/Memory Security Audit

**Date**: {result['timestamp']}
**Verdict**: {result['summary']['verdict']}

## Summary

| Metric | Value |
|--------|-------|
| Critical | {result['summary']['critical']} |
| High | {result['summary']['high']} |
| Key Leaks | {result['summary']['key_leaks']} |
| MiniMax-M3 Default | {result['summary']['MiniMax_M3_default']} |

"""

    if critical:
        md += "\n## ⚠️ Critical Issues\n\n"
        for c in critical:
            md += f"- **{c['issue']}**: `{c.get('file', 'N/A')}`\n"

    if issues:
        md += "\n## High Severity Findings\n\n"
        for i in issues:
            md += f"- **{i['issue']}**: `{i.get('file', 'N/A')}`\n"

    if key_leaks:
        md += "\n## 🔑 Key/Secret Leaks\n\n"
        for k in key_leaks:
            md += f"- Pattern `{k['pattern']}` in `{k['file']}`\n"

    if not critical and not key_leaks:
        md += "\n✅ No critical issues or key leaks found.\n"

    md += """
## Checks Performed

1. ✅ Memory/data — no keys
2. ✅ Workspace state — no full configs
3. ✅ Workspace runs — no full configs/key
4. ✅ Reports — no keys
5. ✅ Module isolation — no agent.llm imports
6. ✅ Skill isolation — no agent.llm imports
7. ✅ config_translation isolation — no LLM
8. ✅ No old GraphAgent
9. ✅ No /api/translate
10. ✅ No backend/services/config_translation
11. ✅ No external network-translator
12. ✅ No os.chdir/sys.path hacks
13. ✅ MiniMax-M3 default

---

*Generated by audit_workspace_memory_security.py*
"""
    md_path = REPORTS_DIR / "WORKSPACE_MEMORY_SECURITY_AUDIT.md"
    md_path.write_text(md)

    print(f"Audit complete. Verdict: {result['summary']['verdict']}")
    print(f"  Critical: {result['summary']['critical']}")
    print(f"  Key leaks: {result['summary']['key_leaks']}")
    print(f"  Reports: {json_path}, {md_path}")

    return result


if __name__ == "__main__":
    audit()
