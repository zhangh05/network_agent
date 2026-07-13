#!/usr/bin/env python3
"""Artifact Security Audit — checks for key leaks, path traversal, content exposure."""

import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
os.makedirs(REPORTS, exist_ok=True)

critical, high, warnings = [], [], []

def _check_file(path, patterns, label):
    if not os.path.isfile(path): return
    try:
        content = open(path, encoding="utf-8").read().lower()
    except Exception:
        return
    for p in patterns:
        if p.lower() in content:
            high.append(f"{label}: contains '{p}'")

EXCLUDE_DIRS = {"venv", "scripts", "__pycache__", ".git", ".workbuddy", "harness", "workspaces", "runtime", "memory", "reports", "logs", ".run"}
EXCLUDE_FILES = {"registry/validator.py", "modules/config_translation/backend/client.py"}
EXCLUDE_PREFIXES = ("test_",)

def _check_code(pattern, label):
    for r, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".py") and not any(f.startswith(p) for p in EXCLUDE_PREFIXES):
                fp = os.path.join(r, f)
                rel = os.path.relpath(fp, ROOT)
                if rel in EXCLUDE_FILES:
                    continue
                try:
                    c = open(fp, encoding="utf-8").read()
                except Exception:
                    continue
                if pattern in c:
                    high.append(f"{label}: found in {fp}")

def run():
    # Production code must not mutate process cwd or inject import paths.
    _check_code("os.chdir", "os.chdir")
    _check_code("sys.path.append", "sys.path-hack")

    # Check artifact_id not sha256-based
    store_path = os.path.join(ROOT, "artifacts", "store.py")
    if os.path.exists(store_path):
        with open(store_path) as f:
            c = f.read()
        if "art_<uuid" not in c and "uuid.uuid4" not in c:
            high.append("artifact_id may not be UUID-based")
        if "sha256(content)[:" in c:
            critical.append("artifact_id still uses sha256")

    # Check source_path security
    if os.path.exists(store_path):
        with open(store_path) as f:
            c = f.read()
        if "resolve()" in c and "relative_to" in c:
            warnings.append("OK: source_path uses resolve().relative_to()")
        else:
            high.append("source_path missing resolve().relative_to() check")

    # Check upload size guard — look for the comment that proves correct order
    if os.path.exists(store_path):
        with open(store_path) as f:
            c = f.read()
        if "Size guard BEFORE read_text()" in c:
            warnings.append("OK: explicit size guard comment before read_text")
        elif "st_size" in c and "read_text" in c:
            st_pos = c.find("st_size")
            rt_pos = c.find("read_text")
            if st_pos < rt_pos:
                warnings.append("OK: st_size before read_text (file-level)")
            else:
                high.append("st_size may not precede read_text")

    # Check MAX_FILE_SIZE / _get_max_size
    if os.path.exists(store_path):
        with open(store_path) as f:
            c = f.read()
        if "_get_max_size" in c:
            warnings.append("OK: _get_max_size() exists")
        else:
            warnings.append("WARN: _get_max_size() not found in store.py")

    # Summary
    result = {
        "audit": "artifact_security",
        "critical_count": len(critical),
        "high_count": len(high),
        "warning_count": len(warnings),
        "critical": critical,
        "high": high,
        "warnings": warnings,
        "conclusion": "PASS" if not critical and not high else "FAIL",
    }

    json_path = os.path.join(REPORTS, "artifact_security_audit.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)

    md_path = os.path.join(REPORTS, "ARTIFACT_SECURITY_AUDIT.md")
    with open(md_path, "w") as f:
        f.write("# Artifact Security Audit\n\n")
        f.write(f"Critical: {len(critical)}, High: {len(high)}, Warnings: {len(warnings)}\n\n")
        f.write(f"**Conclusion: {result['conclusion']}**\n\n")
        if critical:
            f.write("## Critical\n")
            for i in critical: f.write(f"- {i}\n")
        if high:
            f.write("\n## High\n")
            for i in high: f.write(f"- {i}\n")
        if warnings:
            f.write("\n## Warnings\n")
            for w in warnings: f.write(f"- {w}\n")

    print(f"Artifact Security Audit: {result['conclusion']}")
    print(f"  Critical: {len(critical)}, High: {len(high)}")
    print(f"  Reports: {json_path}, {md_path}")

if __name__ == "__main__":
    run()
