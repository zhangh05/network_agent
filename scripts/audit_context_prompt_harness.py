#!/usr/bin/env python3
"""Context / Prompt / Harness Combined Audit."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
os.makedirs(REPORTS, exist_ok=True)

critical, high, warnings = [], [], []

def run():
    # Check context module
    for mod in ["context/schemas.py", "context/resolver.py", "context/loader.py", "context/selector.py", "context/compressor.py", "context/builder.py"]:
        if os.path.exists(os.path.join(ROOT, mod)):
            warnings.append(f"OK: {mod} exists")
        else:
            critical.append(f"{mod} missing")

    # Check builder uses pipeline
    builder_path = os.path.join(ROOT, "context", "builder.py")
    if os.path.exists(builder_path):
        with open(builder_path) as f: c = f.read()
        if "load_context_items" in c and "select_context_items" in c and "compress_context_items" in c:
            warnings.append("OK: builder uses full pipeline (load→select→compress)")
        else:
            high.append("builder may not use full pipeline")

    # Check prompts module
    for mod in ["prompts/schemas.py", "prompts/loader.py", "prompts/renderer.py", "prompts/policy.py", "prompts/registry.yaml"]:
        if os.path.exists(os.path.join(ROOT, mod)):
            warnings.append(f"OK: {mod} exists")
        else:
            critical.append(f"{mod} missing")

    # Check templates
    tmpl_dir = os.path.join(ROOT, "prompts", "templates")
    if os.path.exists(tmpl_dir):
        tmpls = os.listdir(tmpl_dir)
        warnings.append(f"OK: {len(tmpls)} templates in prompts/templates/")
    else:
        critical.append("prompts/templates/ missing")

    # Check safe_generate uses prompt runtime
    runtime_path = os.path.join(ROOT, "agent", "llm", "runtime.py")
    if os.path.exists(runtime_path):
        with open(runtime_path) as f: c = f.read()
        if "from prompts.loader import" in c or "from prompts.renderer import" in c:
            warnings.append("OK: safe_generate imports prompts runtime")
        else:
            high.append("safe_generate may not use prompts runtime")
        if "from agent.llm.tasks.prompts import PROMPTS" in c and "fallback" not in c:
            critical.append("safe_generate defaults to old PROMPTS path")
        if "rendered.text" in c:
            warnings.append("OK: rendered.text used in messages")
        else:
            high.append("rendered.text may not enter provider messages")

    # Check composer has task selection
    composer_path = os.path.join(ROOT, "agent", "nodes", "composer.py")
    if os.path.exists(composer_path):
        with open(composer_path) as f: c = f.read()
        if "_select_prompt_task" in c:
            warnings.append("OK: composer has _select_prompt_task")
        else:
            high.append("composer missing _select_prompt_task")

    # Check policy blocks
    policy_path = os.path.join(ROOT, "prompts", "policy.py")
    if os.path.exists(policy_path):
        with open(policy_path) as f: c = f.read()
        if "可直接下发" in c or "direct.deploy" in c.lower():
            warnings.append("OK: policy detects direct deploy claims")
        if "FAKE_REF_PATTERN" in c:
            warnings.append("OK: fake ref pattern present")

    # Check no old API
    for check_path in ["backend/services/config_translation.py"]:
        p = os.path.join(ROOT, check_path)
        if os.path.exists(p):
            critical.append(f"{check_path} should not exist")

    # Check docs exist
    for doc in ["FOUNDATION_BASELINE.md", "ARCHITECTURE.md", "AGENT_RUNTIME.md", "PROMPT_RUNTIME.md", "JOB_RUNTIME.md"]:
        dp = os.path.join(ROOT, "docs", doc)
        if os.path.exists(dp):
            warnings.append(f"OK: docs/{doc} exists")
        else:
            high.append(f"docs/{doc} missing")

    result = {
        "audit": "context_prompt_harness",
        "critical_count": len(critical), "high_count": len(high),
        "critical": critical, "high": high, "warnings": warnings,
        "conclusion": "PASS" if not critical and not high else "FAIL",
    }

    for fmt, name in [("json", "context_prompt_harness_audit.json"), ("md", "CONTEXT_PROMPT_HARNESS_AUDIT.md")]:
        p = os.path.join(REPORTS, name)
        with open(p, "w") as f:
            if fmt == "json":
                json.dump(result, f, indent=2)
            else:
                f.write(f"# Context / Prompt / Harness Audit\n\n**Conclusion: {result['conclusion']}**\n\n")
                for label, items in [("Critical", critical), ("High", high), ("Warnings", warnings)]:
                    if items:
                        f.write(f"## {label}\n")
                        for i in items: f.write(f"- {i}\n")
                        f.write("\n")

    print(f"Context/Prompt/Harness Audit: {result['conclusion']} (C:{len(critical)} H:{len(high)})")

if __name__ == "__main__":
    run()
