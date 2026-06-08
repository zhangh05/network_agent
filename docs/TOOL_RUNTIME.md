# Tool Runtime

Network Agent Tool Runtime provides safe, auditable, policy-controlled tool execution.

## Version History

- **v0.1**: 7 built-in tools (artifact, parser, report, command — low risk only)
- **v0.2**: 55 tools across 11 categories. See [TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md](TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md)
- **v0.3 (current)**: Interactive UI with invoke, dry-run, history, and approval workflows. See below.
- Integration details: see [TOOL_RUNTIME_INTEGRATION.md](TOOL_RUNTIME_INTEGRATION.md)

## Current State (v0.3)

- **55 tools** registered (7 v0.1 + 48 v0.2)
- **11 categories**: artifact, parser, report, command, knowledge, web, session, runtime, text, workspace, powershell
- **9 API endpoints** (1 read-only catalog + 8 interactive)
- **Interactive UI**: 3-tab Tool Catalog with invoke, history, and approvals
- **No real device access** (SSH/Telnet/SNMP/Nmap forbidden)
- **No config push** (forbidden)
- **No arbitrary shell** (shell.exec, powershell.exec, command.exec forbidden)

## Architecture

```
ToolInvocation → ToolExecutor
                   ├── ToolRegistry (lookup ToolSpec + Handler)
                   ├── _validate_arguments (schema check)
                   ├── ToolPolicy.check (risk + approval + safety)
                   ├── execute handler
                   ├── redact_tool_output (deep redaction)
                   └── ToolResult (status + output + policy_decision)

Frontend UI:
  Tool Catalog (search + filter) → Invoke Modal (param form)
    ├── risk=low   → Execute button
    ├── risk=medium → Dry Run + Execute buttons
    └── risk=high  → Request Approval button
                                   ↓
                            Approval Queue (approve/reject)
                                   ↓
                            Exec History (status filter + replay)
```

## Risk Levels

| Level | Behavior |
|-------|----------|
| low | Always allowed, read-only |
| medium | Allowed, dry_run supported, writes artifact only |
| high | Default disabled, requires `approval_id`, allowlisted only |

## Forbidden Tools

12 tools permanently blocked at policy level. See `tool_runtime/policy.py` for full list.

## APIs (v0.3)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tools/catalog` | GET | Read-only tool metadata (55 tools) |
| `/api/tools/invoke` | POST | Execute tool through full safety pipeline |
| `/api/tools/dry-run` | POST | Preview invocation without execution |
| `/api/tools/history` | GET | Execution history (per workspace, optional status filter) |
| `/api/tools/approvals` | GET | List pending approval requests |
| `/api/tools/approvals` | POST | Submit approval request for high-risk tool |
| `/api/tools/approvals/<id>/approve` | PUT | Approve a pending request |
| `/api/tools/approvals/<id>/reject` | PUT | Reject a pending request |
| `/api/tools/permissions` | GET | Workspace-level tool permission summary |

## Invoke Flow

```
User clicks tool card
  → Invoke modal with auto-generated parameter form
  → User fills params, clicks Execute / Dry Run / Request Approval
  → POST /api/tools/invoke (or dry-run / approvals)
  → Backend: ToolPolicy.check → ToolExecutor.execute → redaction → ToolResult
  → Result displayed inline in modal
  → Recorded in execution history (JSON-persisted, 200-entry limit)
```

## Safety Guarantees

1. No tool can execute arbitrary shell commands
2. No tool can access files outside workspace
3. No tool can connect to private/internal networks
4. No tool can push config to real devices
5. All outputs are redacted (password/token/path masking)
6. Audit metadata is written for every invocation
7. High-risk tools require approval_id
8. Execution history is thread-safe and persisted to JSON
