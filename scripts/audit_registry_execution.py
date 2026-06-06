#!/usr/bin/env python3
"""Registry Execution Audit — validates Agent execution is registry-driven (no hardcoded adapter imports)."""

import json, os, sys, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def check_file(path: Path, pattern: str) -> bool:
    try:
        return pattern in path.read_text()
    except Exception:
        return False


def audit():
    critical = []
    issues = []

    # 1. Router must not have hardcoded module/skill maps
    router = PROJECT_ROOT / "agent" / "nodes" / "intent_router.py"
    router_content = router.read_text()

    if "_module_for" in router_content and "def _module_for" in router_content:
        critical.append("Router has hardcoded _module_for()")
    if "_skill_for" in router_content and "def _skill_for" in router_content:
        critical.append("Router has hardcoded _skill_for()")
    if "_INTENT_CAPABILITY_MAP" in router_content:
        critical.append("Router has hardcoded _INTENT_CAPABILITY_MAP")

    # 2. Executor must not have hardcoded config_translation
    executor = PROJECT_ROOT / "agent" / "nodes" / "skill_executor.py"
    exec_content = executor.read_text()

    if "from skills.config_translation.adapter import translate" in exec_content:
        critical.append("Executor hardcodes config_translation adapter import")
    if "if skill == 'config_translation'" in exec_content or 'if skill == "config_translation"' in exec_content:
        critical.append("Executor hardcodes if skill == config_translation")
    if "from skills.config_translation.adapter import" in exec_content:
        critical.append("Executor hardcodes adapter import (non-dynamic)")
    if "elif state.intent == 'context_qa'" in exec_content or 'elif state.intent == "context_qa"' in exec_content:
        critical.append("Executor special-cases context_qa intent")
    if "from modules.config_translation" in exec_content:
        critical.append("Executor imports modules.config_translation directly")

    # 3. Executor must use registry for dynamic loading
    if "importlib" not in exec_content:
        issues.append("Executor may not use dynamic import (no importlib)")
    if "registry" not in exec_content.lower():
        critical.append("Executor does not reference registry at all")

    # 4. No /api/translate in active code
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if any(x in p for x in ["legacy", "scripts/audit", "harness/", "registry/validator"]):
            continue
        content = py_file.read_text()
        if '"/api/translate"' in content or "'/api/translate'" in content:
            if "已删除" not in content and "legacy" not in p:
                critical.append(f"Active /api/translate reference: {py_file}")

    # 5. No backend/services/config_translation
    svc_dir = PROJECT_ROOT / "backend" / "services" / "config_translation"
    if svc_dir.is_dir():
        critical.append("backend/services/config_translation still exists")

    # 6. No old GraphAgent in active code
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        p = str(py_file)
        if any(x in p for x in ["legacy", "scripts/audit", "harness/", "registry/validator"]):
            continue
        if "GraphAgent" in py_file.read_text():
            critical.append(f"GraphAgent reference: {py_file}")

    # 7. Verify adapter has review() function
    adapter = PROJECT_ROOT / "skills" / "config_translation" / "adapter.py"
    if adapter.is_file():
        content = adapter.read_text()
        if "def review(" not in content:
            issues.append("adapter.py missing review() function for context QA")
    else:
        critical.append("config_translation adapter.py not found")

    # 8. Check skill.yaml has config.review with function=review
    sy = (PROJECT_ROOT / "skills" / "config_translation" / "skill.yaml").read_text()
    if "config.review" not in sy:
        critical.append("skill.yaml missing config.review capability")
    if "function: review" not in sy:
        issues.append("config.review capability may not have function: review")

    result = {
        "audit": "REGISTRY_EXECUTION_AUDIT",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "critical": len(critical),
            "issues": len(issues),
            "verdict": "PASS" if len(critical) == 0 else "FAIL",
        },
        "critical": critical,
        "issues": issues,
    }

    json_path = REPORTS_DIR / "registry_execution_audit.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    md = f"""# Registry Execution Audit

**Verdict**: {result['summary']['verdict']}

| Metric | Value |
|--------|-------|
| Critical | {result['summary']['critical']} |
| Issues | {result['summary']['issues']} |
"""
    for c in critical:
        md += f"\n- **CRITICAL**: {c}"
    for i in issues:
        md += f"\n- Issue: {i}"

    if not critical:
        md += "\n✅ No hardcoded execution found. Agent is registry-driven.\n"

    (REPORTS_DIR / "REGISTRY_EXECUTION_AUDIT.md").write_text(md)

    print(f"Audit complete. Verdict: {result['summary']['verdict']}")
    print(f"  Critical: {len(critical)}, Issues: {len(issues)}")

    return result


if __name__ == "__main__":
    audit()
