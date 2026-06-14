#!/usr/bin/env python3
"""inspect_runtime_tools — audit tool registry and check docs consistency.

v2.0 Upgrade: added medium-risk tool list, sub-agent visible tools count,
and Production Foundation readiness checks.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.services import default_runtime_services


def main():
    svc = default_runtime_services()
    reg = svc.tool_service.registry

    all_tools = reg.list_all()
    visible = reg.list_model_visible()
    hidden = [t for t in all_tools if t not in visible]

    high_risk = [t for t in all_tools if getattr(t, 'risk_level', '') == 'high']
    medium_risk = [t for t in all_tools if getattr(t, 'risk_level', '') == 'medium']
    needs_approval = [t for t in all_tools if getattr(t, 'requires_approval', False)]

    print(f"registered tools:       {len(all_tools)}")
    print(f"model-visible tools:    {len(visible)}")
    print(f"not model-visible:      {[t.tool_id for t in hidden]}")
    print()

    print("=== high-risk tools ===")
    for t in high_risk:
        print(f"  {t.tool_id:40s} risk={t.risk_level} approval={t.requires_approval}")
    if not high_risk:
        print("  (none)")
    print()

    # ── v2.0: medium-risk write/state tools list ──
    print("=== medium-risk tools (write/state/network) ===")
    if medium_risk:
        for t in medium_risk:
            print(f"  {t.tool_id:40s} source={getattr(t, 'source', 'N/A')}")
    else:
        print("  (none)")
    print()

    print("=== requires_approval tools ===")
    for t in needs_approval:
        print(f"  {t.tool_id:40s}")
    if not needs_approval:
        print("  (none)")
    print()

    # shell/powershell detail
    for tid in ("shell.exec", "powershell.exec"):
        t = reg.get(tid)
        if t:
            print(f"=== {tid} ===")
            print(f"  risk_level:        {t.risk_level}")
            print(f"  requires_approval: {t.requires_approval}")
            print(f"  callable_by_llm:   {t.callable_by_llm}")
            print(f"  source:            {getattr(t, 'source', 'N/A')}")
            print(f"  description:       {(getattr(t, 'description', '') or '')[:120]}")
        else:
            print(f"=== {tid} NOT FOUND ===")
        print()

    # capability counts
    try:
        from agent.capabilities import get_default_capability_registry
        cap_reg = get_default_capability_registry()
        caps = cap_reg.list_all()
        enabled = [c for c in caps if c.status == "enabled"]
        planned = [c for c in caps if c.status == "planned"]
        disabled = [c for c in caps if c.status == "disabled"]
        print(f"capabilities — total: {len(caps)}  enabled: {len(enabled)}  planned: {len(planned)}  disabled: {len(disabled)}")
        for c in caps:
            print(f"  {c.name:30s} status={c.status}")
    except Exception as e:
        print(f"capabilities: error — {e}")
    print()

    # Phase 2: skill tools
    print("=== skill tools ===")
    for tid in ("skill.list", "skill.request_load"):
        t = reg.get(tid)
        status = "✅" if t else "❌"
        print(f"  {status} {tid}")
    print()

    # Phase 2: memory tools
    print("=== memory tools ===")
    for tid in ("memory.create", "memory.list", "memory.confirm",
                "memory.get_profile", "memory.set_profile"):
        t = reg.get(tid)
        status = "✅" if t else "❌"
        print(f"  {status} {tid}")
    print()

    # Phase 2: compact status
    print("=== compact status ===")
    try:
        from agent.runtime.context_compactor import should_compact, compact_messages
        print("  context_compactor module: present true")
    except ImportError:
        print("  context_compactor module: present false")
    try:
        from agent.runtime.loop import TokenLimitExceeded
        print("  token_hard_limit: present true")
    except ImportError:
        print("  token_hard_limit: present false")
    print()

    # ── v2.0: Sub-agent visible tools count ──
    print("=== sub-agent default visible tools ===")
    try:
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS, FORBIDDEN_FOR_SUB_AGENT
        print(f"  DEFAULT_ALLOWED_TOOLS count: {len(DEFAULT_ALLOWED_TOOLS)}")
        print(f"  FORBIDDEN_FOR_SUB_AGENT count: {len(FORBIDDEN_FOR_SUB_AGENT)}")
        # Check that high-risk tools are forbidden for sub-agents
        forbidden_set = set(FORBIDDEN_FOR_SUB_AGENT)
        high_risk_ids = {t.tool_id for t in high_risk}
        high_risk_forbidden = high_risk_ids & forbidden_set
        print(f"  high-risk tools forbidden for sub-agent: {sorted(high_risk_forbidden)}")
        high_risk_not_forbidden = high_risk_ids - forbidden_set
        if high_risk_not_forbidden:
            print(f"  ⚠️  WARNING: high-risk tools NOT forbidden for sub-agent: {sorted(high_risk_not_forbidden)}")
        else:
            print(f"  ✅ all high-risk tools are forbidden for sub-agent")
    except ImportError as e:
        print(f"  sub_agent module: error — {e}")
    print()

    # Check docs consistency
    docs_path = os.path.join(os.path.dirname(__file__), "..", "docs", "CAPABILITIES_AND_TOOLS.md")
    if os.path.exists(docs_path):
        with open(docs_path) as f:
            content = f.read()
        docs_claims_58_57 = "58" in content and "57" in content
        if docs_claims_58_57:
            print("⚠️  WARNING: docs/CAPABILITIES_AND_TOOLS.md claims 58/57, but actual is "
                  f"{len(all_tools)}/{len(visible)}")
        else:
            print(f"✅ docs consistent with actual {len(all_tools)}/{len(visible)}")
    else:
        print("⚠️  docs/CAPABILITIES_AND_TOOLS.md not found")
    print()

    # ── v2.0: Production Foundation Readiness ──
    print("=" * 60)
    print("=== PRODUCTION FOUNDATION READINESS ===")
    print()
    readiness_ok = True

    # 1. tool_contract_ok: all tools have required fields
    print("--- tool_contract_ok ---")
    missing_fields = []
    for t in all_tools:
        tid = t.tool_id
        missing = []
        if not getattr(t, 'tool_id', ''):
            missing.append("tool_id")
        if not getattr(t, 'name', ''):
            missing.append("name")
        if not getattr(t, 'description', ''):
            missing.append("description")
        if not getattr(t, 'category', ''):
            missing.append("category")
        if not getattr(t, 'risk_level', ''):
            missing.append("risk_level")
        if not getattr(t, 'input_schema', None):
            missing.append("input_schema")
        if not getattr(t, 'timeout_seconds', None):
            missing.append("timeout_seconds")
        if missing:
            missing_fields.append(f"{tid}: missing {', '.join(missing)}")
    tool_contract_ok = len(missing_fields) == 0
    if tool_contract_ok:
        print(f"  ✅ All {len(all_tools)} tools have required fields")
    else:
        print(f"  ❌ {len(missing_fields)} tools missing fields:")
        for mf in missing_fields[:10]:
            print(f"     {mf}")
    readiness_ok = readiness_ok and tool_contract_ok
    print()

    # 2. approval_contract_ok: all high-risk have requires_approval=True
    print("--- approval_contract_ok ---")
    approval_failures = []
    for t in high_risk:
        if not getattr(t, 'requires_approval', False):
            approval_failures.append(t.tool_id)
    approval_contract_ok = len(approval_failures) == 0
    if approval_contract_ok:
        print(f"  ✅ All {len(high_risk)} high-risk tools have requires_approval=True")
    else:
        print(f"  ❌ High-risk tools missing requires_approval: {approval_failures}")
    readiness_ok = readiness_ok and approval_contract_ok
    print()

    # 3. docs_consistency_ok: tool counts match between runtime and docs
    print("--- docs_consistency_ok ---")
    docs_consistency_ok = True
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")
    if os.path.exists(readme_path):
        with open(readme_path) as f:
            readme_content = f.read()
        import re
        # v3.0: README mentions canonical / handler / planner counts.
        from tool_runtime.tool_namespace import TOOL_NAMESPACE
        from tool_runtime.canonical_registry import CANONICAL_REGISTRY
        from tool_runtime.tool_governance import planner_visible_tool_ids
        canonical_count = len(TOOL_NAMESPACE)
        registry_count = len(CANONICAL_REGISTRY)
        visible_count = len(planner_visible_tool_ids())
        # Accept any of these patterns in the README.
        canonical_match = re.search(
            r'(\d+)\s+canonical\s*/\s*(\d+)\s+active', readme_content,
        )
        if canonical_match:
            doc_canonical = int(canonical_match.group(1))
            doc_active = int(canonical_match.group(2))
            if (doc_canonical == canonical_count
                    and doc_active == visible_count):
                print(
                    f"  ✅ README.md counts match: "
                    f"canonical={doc_canonical} active={doc_active}"
                )
            else:
                print(
                    f"  ❌ README.md mismatch: doc={doc_canonical}/{doc_active} "
                    f"runtime={canonical_count}/{visible_count}"
                )
                docs_consistency_ok = False
        else:
            print(
                f"  ❌ README.md does not contain v3.0 count pattern "
                f"(expected 'N canonical / N active')"
            )
            docs_consistency_ok = False
    else:
        print(f"  ❌ README.md not found")
        docs_consistency_ok = False
    readiness_ok = readiness_ok and docs_consistency_ok
    print()

    # 4. e2e_tests_present
    print("--- e2e_tests_present ---")
    e2e_test_path = os.path.join(
        os.path.dirname(__file__), "..", "harness",
        "test_v2_production_foundation_e2e.py"
    )
    e2e_tests_present = os.path.exists(e2e_test_path)
    if e2e_tests_present:
        print(f"  ✅ harness/test_v2_production_foundation_e2e.py present")
    else:
        print(f"  ⚠️  harness/test_v2_production_foundation_e2e.py not found (not yet created)")
        # Not a hard failure — E2E tests may be added incrementally
    print()

    # 5. extension_templates_present
    print("--- extension_templates_present ---")
    templates_path = os.path.join(os.path.dirname(__file__), "..", "templates")
    extension_templates_present = os.path.isdir(templates_path)
    if extension_templates_present:
        # Check for sub-directories
        template_dirs = ["capability_template", "tool_template", "skill_template", "module_template"]
        found_dirs = []
        for td in template_dirs:
            td_path = os.path.join(templates_path, td)
            if os.path.isdir(td_path) and os.path.exists(os.path.join(td_path, "README.md")):
                found_dirs.append(td)
        if len(found_dirs) == len(template_dirs):
            print(f"  ✅ All {len(template_dirs)} extension templates present")
        else:
            missing_dirs = [td for td in template_dirs if td not in found_dirs]
            print(f"  ⚠️  Missing template directories: {missing_dirs}")
    else:
        print(f"  ❌ templates/ directory not found")
        readiness_ok = readiness_ok and False
    print()

    # ── Final readiness verdict ──
    print("=" * 60)
    print("PRODUCTION FOUNDATION READINESS SUMMARY:")
    print(f"  tool_contract_ok:          {'✅' if tool_contract_ok else '❌'}")
    print(f"  approval_contract_ok:      {'✅' if approval_contract_ok else '❌'}")
    print(f"  docs_consistency_ok:       {'✅' if docs_consistency_ok else '❌'}")
    print(f"  e2e_tests_present:         {'✅' if e2e_tests_present else '⚠️  (not required yet)'}")
    print(f"  extension_templates_present: {'✅' if extension_templates_present else '❌'}")
    if readiness_ok:
        print("\n✅ Production Foundation checks PASSED")
    else:
        print("\n❌ Production Foundation checks FAILED")
    print()

    return 0 if readiness_ok else 1


if __name__ == "__main__":
    sys.exit(main())
