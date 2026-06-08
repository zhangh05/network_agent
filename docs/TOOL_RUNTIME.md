# Tool Runtime

Network Agent Tool Runtime provides safe, auditable, policy-controlled tool execution.

## Version History

- **v0.1**: 7 built-in tools (artifact, parser, report, command — low risk only)
- **v0.2 (current dev)**: 55 tools across 11 categories. See [TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md](TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md)
- Integration details: see [TOOL_RUNTIME_INTEGRATION.md](TOOL_RUNTIME_INTEGRATION.md)

## Current State (v0.2)

- **55 tools** registered (7 v0.1 + 48 v0.2)
- **11 categories**: artifact, parser, report, command, knowledge, web, session, runtime, text, workspace, powershell
- **1 read-only API**: `GET /api/tools/catalog`
- **No Tool Invoke API**
- **No Tool Invoke UI**
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
```

## Risk Levels

| Level | Behavior |
|-------|----------|
| low | Always allowed, read-only |
| medium | Allowed, dry_run supported, writes artifact only |
| high | Default disabled, requires `approval_id`, allowlisted only |

## Forbidden Tools

12 tools permanently blocked at policy level. See `tool_runtime/policy.py` for full list.

## APIs

| Endpoint | Description |
|----------|-------------|
| `GET /api/tools/catalog` | Read-only tool metadata (55 tools) |

## Safety Guarantees

1. No tool can execute arbitrary shell commands
2. No tool can access files outside workspace
3. No tool can connect to private/internal networks
4. No tool can push config to real devices
5. All outputs are redacted (password/token/path masking)
6. Audit metadata is written for every invocation
7. High-risk tools require approval_id
