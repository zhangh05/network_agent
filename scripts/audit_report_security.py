#!/usr/bin/env python3
"""Report Security Audit."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
os.makedirs(REPORTS, exist_ok=True)

critical, high, warnings = [], [], []

def run():
    # Check core.reports exists
    if os.path.exists(os.path.join(ROOT, "core", "reports")):
        warnings.append("OK: core/reports/ exists")
    else:
        critical.append("core/reports/ missing")

    # Check no full deployable in default report
    re_path = os.path.join(ROOT, "core", "reports", "renderer.py")
    if os.path.exists(re_path):
        with open(re_path) as f: c = f.read()
        if "include_deployable_config" in c:
            warnings.append("OK: include_deployable_config option present")
        else:
            high.append("include_deployable_config option missing in renderer")

    # Check docx/pdf unsupported
    exporter = os.path.join(ROOT, "core", "reports", "exporter.py")
    if os.path.exists(exporter):
        with open(exporter) as f: c_exp = f.read()
        if "unsupported" in c_exp.lower():
            warnings.append("OK: unsupported format handling present")

    # Summary
    result = {
        "audit": "report_security",
        "critical_count": len(critical), "high_count": len(high),
        "critical": critical, "high": high, "warnings": warnings,
        "conclusion": "PASS" if not critical and not high else "FAIL",
    }
    for fmt, name in [("json", "report_security_audit.json"), ("md", "REPORT_SECURITY_AUDIT.md")]:
        p = os.path.join(REPORTS, name)
        with open(p, "w") as f:
            if fmt == "json":
                json.dump(result, f, indent=2)
            else:
                f.write(f"# Report Security Audit\n\n**Conclusion: {result['conclusion']}**\n")
    print(f"Report Security Audit: {result['conclusion']} (C:{len(critical)} H:{len(high)})")

if __name__ == "__main__":
    run()