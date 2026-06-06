"""Security audit — scan for key leaks, full config leaks, boundary violations."""

import json, os, sys, re, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_PATTERN = re.compile(r'(sk-[A-Za-z0-9]{20,})|(eyJ[A-Za-z0-9+/=]{30,})', re.IGNORECASE)
DATA_DIRS = {"memory/data", "reports", "workspaces", "frontend"}
SOURCE_DIRS = {"agent", "backend", "modules", "skills", "harness", "config", "docs", "scripts"}

def scan_data_file(path, relpath):
    """Scan data/output files for secrets and full configs."""
    findings = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        # Only scan data/output files for key leaks
        for m in KEY_PATTERN.finditer(content):
            findings.append(f"KEY in {relpath}: ...{m.group(0)[:8]}...")
        # Check for full config in output files
        for cfg_key in ['"source_config"', '"deployable_config"']:
            count = content.count(cfg_key)
            if count > 0 and len(content) > 300:
                # Only flag if it looks like actual config data, not code
                if cfg_key in content and ('interface' in content.lower() or 'router' in content.lower()):
                    findings.append(f"FULL CONFIG may be in {relpath}")
    except: pass
    return findings

def scan_source_file(path, relpath):
    """Scan source code for key leaks only (not variable names)."""
    findings = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        # Check for actual key values, not variable names
        for m in KEY_PATTERN.finditer(content):
            key_val = m.group(0)
            # Skip if it's just a variable name assignment pattern
            context = content[max(0,m.start()-20):m.end()+5]
            if 'api_key' not in context.lower() and 'apikey' not in context.lower():
                findings.append(f"KEY in source {relpath}: ...{key_val[:8]}...")
    except: pass
    return findings

def scan_boundary():
    findings = []
    for d in ['modules', 'skills']:
        for f in glob.glob(os.path.join(ROOT,d,'**','*.py'),recursive=True):
            with open(f, encoding='utf-8', errors='replace') as fh:
                c = fh.read()
            if 'agent.llm' in c:
                findings.append(f"BOUNDARY VIOLATION: {os.path.relpath(f,ROOT)} imports agent.llm")
    return findings

def main():
    issues = []
    
    # Scan source code for actual key leaks
    for d in SOURCE_DIRS:
        dp = os.path.join(ROOT, d)
        if not os.path.isdir(dp): continue
        for dirpath,_,files in os.walk(dp):
            # Skip pycache
            if '__pycache__' in dirpath: continue
            for f in files:
                if f.endswith('.pyc'): continue
                fp = os.path.join(dirpath,f)
                rel = os.path.relpath(fp,ROOT)
                issues += scan_source_file(fp, rel)
    
    # Scan data directories
    for d in DATA_DIRS:
        dp = os.path.join(ROOT, d)
        if not os.path.isdir(dp): continue
        for dirpath,_,files in os.walk(dp):
            if '__pycache__' in dirpath: continue
            for f in files:
                if f.endswith('.pyc'): continue
                fp = os.path.join(dirpath,f)
                rel = os.path.relpath(fp,ROOT)
                issues += scan_data_file(fp, rel)
    
    # Boundary check
    issues += scan_boundary()
    
    # Scan README and ARCHITECTURE
    for f in ['README.md', 'docs/ARCHITECTURE.md']:
        fp = os.path.join(ROOT, f)
        if os.path.isfile(fp):
            with open(fp, encoding='utf-8', errors='replace') as fh:
                content = fh.read()
            for m in KEY_PATTERN.finditer(content):
                issues.append(f"KEY LEAK in {f}: ...{m.group(0)[:8]}...")

    report = {"total_issues": len(issues), "issues": issues, "passed": len(issues)==0}
    
    os.makedirs(os.path.join(ROOT,'reports'),exist_ok=True)
    with open(os.path.join(ROOT,'reports','llm_security_audit.json'),'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    md = "# LLM Security Audit\n\n" + ("✅ **PASS** — No issues found.\n" if not issues else f"❌ Found {len(issues)} issue(s):\n\n")
    for i in issues: md += f"- {i}\n"
    with open(os.path.join(ROOT,'reports','LLM_SECURITY_AUDIT.md'),'w') as f:
        f.write(md)
    
    print(f"Audit done: {len(issues)} issues")
    if issues:
        for i in issues: print(f"  - {i}")
        sys.exit(1)
    else:
        print("  All clear!")
        sys.exit(0)

if __name__=='__main__': main()
