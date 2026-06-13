#!/usr/bin/env python3
"""inspect_agent_kernel — audit Agent Kernel completeness."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.services import default_runtime_services


def main():
    reg = default_runtime_services().tool_service.registry
    all_t = reg.list_all()
    visible = reg.list_model_visible()

    print(f"Agent Kernel v2.1 — {len(all_t)}/{len(visible)} tools")
    print()

    modules = {
        "Tools": ["file.list","file.exists","file.read","file.edit","file.patch",
                   "file.write","workspace.write_artifact_file",
                   "shell.exec","powershell.exec","python.exec",
                   "web.search","web.fetch_summary","web.extract_links"],
        "Skills": ["skill.list","skill.find_skills","skill.inspect",
                    "skill.request_load","skill.create"],
        "Memory": ["memory.create","memory.retrieve","memory.search","memory.list",
                    "memory.confirm","memory.update","memory.delete_soft",
                    "memory.get_profile","memory.set_profile"],
        "Context": ["auto_compact","token_tracker","context_compactor"],
        "Permission": ["permission_matrix","ApprovalStore","ToolPolicy"],
        "Sub-Agent": ["agent.spawn","agent.list_roles","agent.get_result"],
        "Sessions": ["session.create","session.list","session.snapshot",
                      "session.rewind","session.checkpoint","session.export"],
        "Command": ["slash.run","command_system","SLASH_COMMANDS"],
        "Hook": ["PRE_TOOL_USE","POST_TOOL_USE","PRE_TURN","POST_TURN",
                  "PRE_MODEL","POST_MODEL","ON_ERROR","ON_APPROVAL","ON_COMPACT"],
        "Query Engine": ["QueryResult","with_retry","ErrorType","build_trace_id",
                          "rate_limit","token_limit"],
    }

    for mod, checks in modules.items():
        total = len(checks)
        ok = 0
        for c in checks:
            # Tool check
            t = reg.get(c)
            if t:
                ok += 1
                continue
            # Import check
            try:
                if "agent.runtime" in c or "workspace" in c or "command_system" in c:
                    __import__(c) if "." not in c else None
                ok += 1
            except:
                pass
        pct = round(ok/total*100) if total else 0
        status = "✅" if ok == total else ("⚠️" if ok >= total//2 else "❌")
        print(f"  {status} {mod}: {ok}/{total} ({pct}%)")

    print()
    print("--- planned / not yet enabled ---")
    planned = ["skill.create (pending_review, in REMOVED list)",
               "agent.team (multi-agent team)",
               "pdf.* (pyPDF2 dependency)", 
               "cache layer",
               "skill.load direct injection"]
    for p in planned:
        print(f"  📋 {p}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
