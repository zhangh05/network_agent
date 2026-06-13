#!/usr/bin/env python3
"""inspect_runtime_tools — audit tool registry and check docs consistency."""

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
    needs_approval = [t for t in all_tools if getattr(t, 'requires_approval', False)]

    print(f"registered tools:       {len(all_tools)}")
    print(f"model-visible tools:    {len(visible)}")
    print(f"not model-visible:      {[t.tool_id for t in hidden]}")
    print()

    print("=== high-risk tools ===")
    for t in high_risk:
        print(f"  {t.tool_id:40s} risk={t.risk_level} approval={t.requires_approval}")
    print()

    print("=== requires_approval tools ===")
    for t in needs_approval:
        print(f"  {t.tool_id:40s}")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
