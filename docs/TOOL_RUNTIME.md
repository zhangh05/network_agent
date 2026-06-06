# Tool Runtime Foundation v0.1

> **Status**: Foundation established — no real device execution  
> **Version**: v0.1  
> **Date**: 2026-06-07  
> **Commit**: (see latest)

---

## 1. Purpose

Tool Runtime provides a secure, auditable, policy-controlled execution layer for atomic operations within Network Agent.

- Tools are **atomic actions** with schema-validated inputs and structured outputs.
- Tools are **executed by Module Services**, not called directly by the Agent.
- All tool calls pass through **unified safety pipeline**: policy → redaction → audit.

---

## 2. Relationship to Module / Skill / Capability

```
Agent
  → Capability (contract)
    → Skill Adapter (thin pass-through)
      → Module Service (business orchestration)
        → Tool Runtime (security & execution layer)
          → Tool (atomic action)
```

**Tool Runtime is NOT:**
- A replacement for Skill or Capability
- A way to execute arbitrary commands
- A shell or command executor
- A real device access layer

**Tool Runtime is:**
- A reusable, policy-gated execution base
- A safety layer for atomic operations
- A traceable, redacted, auditable runtime

---

## 3. Call Flow

```
ToolInvocation
  → ToolRegistry.get_tool(tool_id) → ToolSpec
  → ToolPolicy.check(spec, invocation) → PolicyDecision
  → if blocked: return ToolResult(status="blocked")
  → if dry_run: execute dry-run handler
  → else: execute handler
  → redact output
  → build audit event
  → return ToolResult
```

---

## 4. Core Data Structures

### ToolSpec (`tool_runtime/schemas.py`)

| Field | Type | Description |
|-------|------|-------------|
| `tool_id` | str | Unique identifier, e.g. `"parser.parse_config_text"` |
| `name` | str | Human-readable name |
| `description` | str | What the tool does |
| `category` | str | `artifact` | `parser` | `report` | `command` |
| `risk_level` | str | `low` | `medium` | `high` | `forbidden` |
| `enabled` | bool | Whether the tool is active |
| `input_schema` | dict | JSON Schema for arguments |
| `timeout_seconds` | int | Max execution time (default 30) |
| `dry_run_supported` | bool | Whether dry-run mode works |
| `writes_artifact` | bool | Whether output is artifact-backed |
| `reads_artifact` | bool | Whether tool reads from artifact store |

### ToolInvocation (`tool_runtime/schemas.py`)

| Field | Type | Description |
|-------|------|-------------|
| `invocation_id` | str | Unique invocation ID (uuid4 hex) |
| `tool_id` | str | Which tool to invoke |
| `arguments` | dict | Tool arguments (schema-validated) |
| `workspace_id` | str | Optional workspace context |
| `run_id` | str | Optional Agent run context |
| `dry_run` | bool | If true, execute dry-run path |

### ToolResult (`tool_runtime/schemas.py`)

| Field | Type | Description |
|-------|------|-------------|
| `status` | str | `succeeded` | `failed` | `blocked` | `dry_run` |
| `output` | dict | Redacted tool output |
| `summary` | str | Safe summary (max 500 chars) |
| `duration_ms` | int | Execution time in milliseconds |
| `redacted` | bool | Whether output was redacted |
| `policy_decision` | PolicyDecision | Result of policy check |

---

## 5. ToolRegistry (`tool_runtime/registry.py`)

Stores `ToolSpec` + handler function pairs. Does NOT execute tools.

| Method | Description |
|--------|-------------|
| `register_tool(spec, handler)` | Register a tool (raises on duplicate or forbidden risk) |
| `get_tool(tool_id)` | Get ToolSpec metadata |
| `get_handler(tool_id)` | Get handler function |
| `list_tools()` | List all tools as metadata dicts (no handlers) |
| `is_enabled(tool_id)` | Check if registered and enabled |

---

## 6. ToolPolicy (`tool_runtime/policy.py`)

v0.1 policy checks:

1. Tool exists in registry
2. Tool is enabled
3. Tool is not in v0.1 forbidden list
4. Category is allowed (`artifact`, `parser`, `report`, `command`)
5. Risk level is `low` (medium/high/forbidden blocked)
6. Dry-run is supported if requested
7. Timeout ≤ 60 seconds
8. Arguments safe (no SSH/SNMP/shell injection)

### v0.1 Forbidden Tool IDs

```
ssh.exec        telnet.exec      snmp.walk
nmap.scan       ping.sweep       command.exec
shell.exec      device.exec      config.push
file.read_any   file.write_any
```

---

## 7. ToolExecutor (`tool_runtime/executor.py`)

Entry point: `ToolExecutor(registry, policy).execute(invocation) → ToolResult`

Pipeline:
1. Validate invocation + lookup ToolSpec
2. Validate arguments against input_schema
3. Run ToolPolicy.check()
4. If blocked → return `blocked`
5. If dry_run → execute handler with dry-run contract
6. Execute handler
7. Redact output
8. Return structured ToolResult

**Guarantee**: Never raises exceptions — all errors are captured in ToolResult.

---

## 8. Redaction (`tool_runtime/redaction.py`)

Recursive redaction of dict/list/str outputs.

| Pattern | Replacement |
|---------|-------------|
| `password/passwd/secret/community` + value | `[REDACTED]` |
| `sk-xxxx...` API keys | `sk-xxxx****[REDACTED]` |
| `Bearer xxx...` tokens | `Bearer [REDACTED]` |
| API key assignments | `key_name=[REDACTED]` |
| Absolute Unix paths | `[PATH_REDACTED]` |

---

## 9. Audit / Trace (`tool_runtime/audit.py`)

Lightweight audit event builder. Records:
- invocation_id, tool_id, status, duration_ms
- risk_level, dry_run, workspace_id, run_id
- artifact_ids, redacted flag
- policy decision summary

Does NOT record: full arguments, full output, keys, passwords, paths.

---

## 10. v0.1 Allowed Tools

| tool_id | Category | Description |
|---------|----------|-------------|
| `artifact.list` | artifact | List artifact metadata summaries |
| `artifact.read_summary` | artifact | Read safe summary of one artifact |
| `parser.parse_config_text` | parser | Shallow parse config text (stats only) |
| `parser.extract_interfaces` | parser | Extract interface names (no full blocks) |
| `parser.extract_routes` | parser | Extract route summaries (IPs masked) |
| `report.render_from_safe_summary` | report | Render markdown from safe summary |
| `command.dry_run_echo` | command | Test dry-run chain (never executes) |

All tools: risk_level=`low`, dry_run_supported=`True`.

---

## 11. v0.1 Forbidden Tools (blocked at policy)

ssh.exec, telnet.exec, snmp.walk, nmap.scan, ping.sweep, command.exec, shell.exec, device.exec, config.push, file.read_any, file.write_any.

These have NO handler implementation. They are blocked by ToolPolicy before execution is attempted.

---

## 12. Non-Goals

This v0.1 foundation explicitly does **NOT**:

- Execute real device commands
- Provide SSH/Telnet/SNMP/nmap/ping sweep
- Provide arbitrary shell access
- Push configuration to devices
- Offer a Tool UI
- Integrate with topology/inspection/CMDB/knowledge modules
- Add HTTP API endpoints for tools
- Modify config_translation or translate_bundle
- Use legacy `tool_calls`/`tool_results` as Tool Runtime contracts

---

## 13. Security Red Lines

1. Agent must not execute arbitrary tools without capability gating
2. Tool Runtime must not become an arbitrary shell
3. Real device execution is out of scope for v0.1
4. All tools must be registered in ToolRegistry
5. Tool inputs must be schema-validated
6. Tool calls must be policy-checked
7. Tool outputs must be redacted
8. Tool results must be auditable
9. Sensitive output must be summarized — never dumped into LLM context
10. Tools must not write to Memory
11. Tools must not call LLM
12. Tools must not generate or modify deployable_config

---

## 14. Future Phases

- v0.2: medium-risk tools with explicit approval
- v0.3: dry-run real device command path (no execution, validation only)
- v1.0: real device execution with approval, audit, and rollback
