#!/usr/bin/env python3
"""Registry Contract Audit — validates module/skill/capability schema compliance."""

import json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def audit():
    from registry.loader import load_module_registry, load_skill_registry, load_capabilities
    from registry.validator import generate_validation_report

    modules = load_module_registry()
    skills = load_skill_registry()
    caps = load_capabilities()

    report = generate_validation_report()
    issues = []
    critical = []

    # Check registries don't contain banned patterns
    for m in modules:
        m_dict = m.as_dict()
        raw = json.dumps(m_dict)
        if "/api/translate" in raw and m.module_name != "config_translation":
            critical.append(f"module {m.module_name} references /api/translate")
        if "backend/services" in raw:
            critical.append(f"module {m.module_name} references backend/services")
        if "8020" in raw:
            issues.append(f"module {m.module_name} references port 8020")
        if "MiniMax-M1" in raw:
            critical.append(f"module {m.module_name} has MiniMax-M1 residue")
        if "sk-" in raw:
            issues.append(f"module {m.module_name} may contain API key")

    for s in skills:
        s_dict = s.as_dict()
        raw = json.dumps(s_dict)
        if "GraphAgent" in raw:
            critical.append(f"skill {s.skill_name} references GraphAgent")

    # Deployable module requires verification
    for m in modules:
        if m.can_generate_deployable and not m.requires_manual_review:
            critical.append(f"module {m.module_name}: deployable without verification")

    result = {
        "audit": "REGISTRY_CONTRACT_AUDIT",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "critical": len(critical) + len(report["errors"]),
            "issues": len(issues),
            "validation_errors": len(report["errors"]),
            "validation_warnings": len(report["warnings"]),
            "modules_loaded": len(modules),
            "skills_loaded": len(skills),
            "capabilities_loaded": len(caps),
            "verdict": "PASS" if len(critical) == 0 and len(report["errors"]) == 0 else "FAIL",
        },
        "validation": report,
        "critical": critical,
        "issues": issues,
    }

    json_path = REPORTS_DIR / "registry_contract_audit.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    md = f"""# Registry Contract Audit

**Verdict**: {result['summary']['verdict']}

| Metric | Value |
|--------|-------|
| Modules | {len(modules)} |
| Skills | {len(skills)} |
| Capabilities | {len(caps)} |
| Validation Errors | {report['error_count']} |
| Validation Warnings | {report['warning_count']} |
| Critical | {len(critical)} |
"""
    for c in critical:
        md += f"\n- **CRITICAL**: {c}"

    if not critical and not report["errors"]:
        md += "\n✅ All registry contracts valid.\n"

    (REPORTS_DIR / "REGISTRY_CONTRACT_AUDIT.md").write_text(md)

    print(f"Audit complete. Verdict: {result['summary']['verdict']}")
    print(f"  Modules: {len(modules)}, Skills: {len(skills)}, Caps: {len(caps)}")
    print(f"  Critical: {len(critical)}, Errors: {len(report['errors'])}")

    return result


if __name__ == "__main__":
    audit()
