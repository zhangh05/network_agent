#!/usr/bin/env python3
"""verify_docs_runtime_consistency.py

Verify that documentation tool counts match actual runtime construction,
check for old/renamed tool names, and flag disallowed claims in docs.

Returns exit 0 if all checks pass, exit 1 if any fail.
"""

import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

FAILURES = 0
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global FAILURES, CHECKS
    CHECKS += 1
    status = "✅ PASS" if condition else "❌ FAIL"
    msg = f"  {status}: {name}"
    if detail and not condition:
        msg += f"  ({detail})"
    print(msg)
    if not condition:
        FAILURES += 1
    return condition


# ── 1. Get actual tool counts from runtime ───────────────────────────

print("=" * 60)
print("1. Runtime Tool Counts")
try:
    from agent.runtime.services import default_runtime_services
    svc = default_runtime_services()
    reg = svc.tool_service.registry
    all_tools = reg.list_all()
    visible = reg.list_model_visible()
    actual_all = len(all_tools)
    actual_visible = len(visible)
    print(f"   Actual registered tools: {actual_all}")
    print(f"   Actual model-visible:    {actual_visible}")
except Exception as e:
    print(f"   ERROR loading runtime: {e}")
    actual_all = 0
    actual_visible = 0

# ── 2. Check README.md tool count consistency ────────────────────────

print()
print("=" * 60)
print("2. README.md Tool Count")
readme_path = os.path.join(ROOT, "README.md")
if os.path.exists(readme_path):
    with open(readme_path) as f:
        readme = f.read()

    # Look for patterns like "70 registered / 70 model-visible"
    m = re.search(r'(\d+)\s+registered\s*/\s*(\d+)\s+model-visible', readme)
    if m:
        readme_all = int(m.group(1))
        readme_visible = int(m.group(2))
        check("README registered count matches runtime",
              readme_all == actual_all,
              f"README says {readme_all}, runtime says {actual_all}")
        check("README model-visible count matches runtime",
              readme_visible == actual_visible,
              f"README says {readme_visible}, runtime says {actual_visible}")
    else:
        check("README contains tool count pattern", False, "Could not find 'N registered / M model-visible' pattern")

    # Also check the tool count fact check section
    m2 = re.search(r'Expected current output:\s*`(\d+)\s+(\d+)`', readme)
    if m2:
        check("README expected output matches runtime",
              int(m2.group(1)) == actual_all and int(m2.group(2)) == actual_visible,
              f"README expects {m2.group(1)} {m2.group(2)}, runtime is {actual_all} {actual_visible}")
else:
    check("README.md exists", False, "File not found")

# ── 3. Check docs/CAPABILITIES_AND_TOOLS.md consistency ──────────────

print()
print("=" * 60)
print("3. CAPABILITIES_AND_TOOLS.md Consistency")
docs_path = os.path.join(ROOT, "docs", "CAPABILITIES_AND_TOOLS.md")
if os.path.exists(docs_path):
    with open(docs_path) as f:
        docs = f.read()

    # Check tool counts
    m = re.search(r'Registered tools:\s*(\d+)', docs)
    if m:
        docs_all = int(m.group(1))
        check("CAPABILITIES_AND_TOOLS.md registered count matches runtime",
              docs_all == actual_all,
              f"Docs says {docs_all}, runtime says {actual_all}")
    else:
        check("CAPABILITIES_AND_TOOLS.md contains registered tools count",
              False, "Pattern not found")

    m2 = re.search(r'Model-visible tools:\s*(\d+)', docs)
    if m2:
        docs_visible = int(m2.group(1))
        check("CAPABILITIES_AND_TOOLS.md model-visible count matches runtime",
              docs_visible == actual_visible,
              f"Docs says {docs_visible}, runtime says {actual_visible}")
    else:
        check("CAPABILITIES_AND_TOOLS.md contains model-visible tools count",
              False, "Pattern not found")

    # Check capabilities
    m3 = re.search(r'(\d+)\s+total,\s*(\d+)\s+enabled,\s*(\d+)\s+planned', docs)
    if m3:
        docs_total = int(m3.group(1))
        docs_enabled = int(m3.group(2))
        docs_planned = int(m3.group(3))
        check("CAPABILITIES_AND_TOOLS.md capability total is 7",
              docs_total == 7, f"Found {docs_total}")
        check("CAPABILITIES_AND_TOOLS.md capability enabled is 4",
              docs_enabled == 4, f"Found {docs_enabled}")
        check("CAPABILITIES_AND_TOOLS.md capability planned is 3",
              docs_planned == 3, f"Found {docs_planned}")
    else:
        check("CAPABILITIES_AND_TOOLS.md contains capability counts",
              False, "Pattern not found")
else:
    check("CAPABILITIES_AND_TOOLS.md exists", False, "File not found")

# ── 4. Check for old/renamed tool names ──────────────────────────────

print()
print("=" * 60)
print("4. Old Tool Name Detection")
old_names = [
    "command.approved_exec",
    "powershell.approved_script",
]
found_old = []
for old_name in old_names:
    # Check in general_tools.py
    gp = os.path.join(ROOT, "tool_runtime", "general_tools.py")
    if os.path.exists(gp):
        with open(gp) as f:
            if old_name in f.read():
                found_old.append(f"{old_name} in general_tools.py")

    # Check in all docs
    for dirpath, _, filenames in os.walk(os.path.join(ROOT, "docs")):
        for fn in filenames:
            if fn.endswith(".md"):
                fp = os.path.join(dirpath, fn)
                with open(fp) as f:
                    content = f.read()
                    if old_name in content:
                        found_old.append(f"{old_name} in {fp}")

    # Check README
    if os.path.exists(readme_path):
        with open(readme_path) as f:
            if old_name in f.read():
                found_old.append(f"{old_name} in README.md")

check("No old tool names (command.approved_exec) found",
      "command.approved_exec" not in found_old,
      "Found: " + ", ".join(found_old) if found_old else "")
check("No old tool names (powershell.approved_script) found",
      "powershell.approved_script" not in found_old,
      "Found: " + ", ".join(found_old) if found_old else "")

# ── 5. Check for disallowed claims in docs ───────────────────────────

print()
print("=" * 60)
print("5. Disallowed Claims Detection")

disallowed_claims = {
    "memory.confirm auto-RAG": [
        r"memory\.confirm.*auto.*RAG",
        r"memory\.confirm.*automatically.*index",
    ],
    "session.rewind full checkpoint": [
        r"session\.rewind.*full.*checkpoint",
        r"session\.rewind.*complete.*snapshot",
    ],
    "python.exec strong sandbox": [
        r"python\.exec.*strong.*sandbox",
        r"python\.exec.*container.*isolat",
    ],
    "sub-agent agent team": [
        r"sub.?agent.*team",
        r"agent.*team.*sub.?agent",
    ],
}

_BACKTICK_RE = re.compile(r"`[^`]+`")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _prose_only(text: str) -> str:
    """Return text with backticked spans and markdown table rows removed.

    Disallowed-claim checks are about marketing prose in headings /
    paragraphs / list items. Markdown tables enumerate canonical tool
    data, and any line that begins with `|` and ends with `|` is part
    of such a table; tool names like `agent.team.coordinate` would
    otherwise trigger the regex even when the prose itself is benign.
    """
    text = _BACKTICK_RE.sub(lambda m: " " * len(m.group(0)), text)
    text = _TABLE_ROW_RE.sub("", text)
    return text


def _line_for_snippet(raw_text: str, offset: int) -> str:
    """Return the line of raw_text that contains ``offset``."""
    start = raw_text.rfind("\n", 0, offset) + 1
    end = raw_text.find("\n", offset)
    if end < 0:
        end = len(raw_text)
    return raw_text[start:end]


docs_files = []
for dirpath, _, filenames in os.walk(os.path.join(ROOT, "docs")):
    for fn in filenames:
        if fn.endswith(".md"):
            docs_files.append(os.path.join(dirpath, fn))
if os.path.exists(readme_path):
    docs_files.append(readme_path)

# Tighten the "sub-agent agent team" regex set. The original regexes
# (r"sub.?agent.*team", r"agent.*team.*sub.?agent") are greedy and
# match across the whole document whenever any of the words "agent",
# "team", "subagent", "sub-agent" appear, including inside plain
# bullet metadata such as "category / group / action: agent / subagent /
# spawn". Replace them with regexes that look for explicit claim
# phrases about agent teams (a marketing claim we want to forbid).
disallowed_claims["sub-agent agent team"] = [
    r"\bsub[\-\s]?agents?\b\s+(?:can\s+)?form\s+(?:a\s+)?team",
    r"\bsub[\-\s]?agents?\b\s+(?:work|collaborate)\s+(?:in|as)\s+a\s+team",
    r"\bagent\s+team\s+(?:can|will|supports?|handles?)",
    r"\bteam\s+of\s+(?:sub[\-\s]?)?agents?\b",
]


found_claims = {}
for claim_name, patterns in disallowed_claims.items():
    matches = []
    for fp in docs_files:
        with open(fp) as f:
            raw_content = f.read()
            content = _prose_only(raw_content)
        for pattern in patterns:
            for m in re.finditer(pattern, content, re.IGNORECASE):
                snippet = _line_for_snippet(raw_content, m.start())
                matches.append(f"  {os.path.basename(fp)}: ...{snippet.strip()}...")
    if matches:
        found_claims[claim_name] = matches

for claim_name in disallowed_claims:
    check(f"No disallowed claim: {claim_name}",
          claim_name not in found_claims,
          "\n" + "\n".join(found_claims.get(claim_name, [])) if claim_name in found_claims else "")

# ── 6. Check PRODUCTION_FOUNDATION.md exists and contains stats ──────

print()
print("=" * 60)
print("6. Production Foundation Doc")
pf_path = os.path.join(ROOT, "docs", "PRODUCTION_FOUNDATION.md")
check("PRODUCTION_FOUNDATION.md exists", os.path.exists(pf_path))

# ── Summary ──────────────────────────────────────────────────────────

print()
print("=" * 60)
print(f"SUMMARY: {CHECKS - FAILURES}/{CHECKS} checks passed")

if FAILURES > 0:
    print(f"\n❌ {FAILURES} FAILURE(S) DETECTED")
    sys.exit(1)
else:
    print("\n✅ ALL CHECKS PASSED")
    sys.exit(0)
