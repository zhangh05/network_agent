# Tool Runtime Integration Contract v0.1

> **Status**: Integration contract established — no real device execution  
> **Version**: v0.1  
> **Date**: 2026-06-07  
> **Depends on**: [Tool Runtime Foundation v0.1](./TOOL_RUNTIME.md)

Current closure baseline: `ac6cadd`. Baseline harness evidence: `850 passed, 7 skipped, 0 failed`.

Current integration status: `ToolRuntimeContext`, `ToolRuntimeClient`, and safe trace metadata integration are implemented. `ToolRuntimeClient.invoke()` writes allowlisted metadata to the observability trace store when `trace_id` is provided in context.

No public Tool invoke HTTP API exists. No Tool invoke UI exists. Agent code must not freely call tools; Module/Service code remains the controlled caller boundary.

---

## 1. Purpose

Define the integration boundary between Tool Runtime and the rest of the Network Agent system — Module, Skill, Agent, Job, Trace, Artifact.

This contract ensures that:
- Module / Service layers have a **standard, controlled** way to invoke tools
- Tool invocations carry proper **context** (workspace, run, job, caller identity)
- Tool results enter trace/audit as **safe metadata only**
- **Agent never directly calls arbitrary tools**
- The system remains auditable and policy-gated

---

## 2. Current Tool Runtime Foundation

Tool Runtime Foundation v0.1 provides:
- `ToolSpec`, `ToolInvocation`, `ToolResult`, `PolicyDecision` (independent data model)
- `ToolRegistry` (registration + discovery, no execution)
- `ToolPolicy` (8 checks, v0.1 blocks medium/high/forbidden tools)
- `ToolExecutor` (validate → policy → execute → redact → audit pipeline)
- 7 low-risk built-in tools (artifact, parser, report, command)

This contract does NOT add new tools — it defines how the existing runtime is called.

---

## 3. Integration Boundary

```
Agent Runtime              Tool Runtime
─────────────              ────────────
Agent                      ToolExecutor
  → Capability               → ToolPolicy
    → Skill Adapter            → Redaction
      → Module Service         → Audit
        → ToolRuntimeClient  → Tool Provider
          → ToolInvocation
```

**Key boundaries:**
- `ToolRuntimeClient` is the **only entry point** for Module/Service code
- `ToolExecutor` is the **only execution path** (can't be bypassed)
- `ToolRegistry` is the **only source of truth** for available tools

---

## 4. Recommended Call Flow

```
Module Service
  ctx = ToolRuntimeContext(
    workspace_id=ws_id,
    run_id=run_id,
    trace_id=trace_id,
    module="config_translation",
    skill="config_translation",
    requested_by="module:config_translation",
  )
  client = get_default_tool_runtime_client()
  result = client.invoke("parser.parse_config_text",
                         {"config_text": cfg},
                         context=ctx)
  # Use result.summary (safe, redacted) — NOT result.output in LLM context
```

---

## 5. ToolRuntimeContext (`tool_runtime/context.py`)

Standard context for tool invocations:

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | str\|None | Current workspace |
| `run_id` | str\|None | Current Agent run |
| `job_id` | str\|None | Current Job |
| `capability` | str\|None | Current Capability ID |
| `skill` | str\|None | Current Skill name |
| `module` | str\|None | Current Module name |
| `requested_by` | str | Caller identity (e.g. "module:config_translation") |
| `dry_run_default` | bool | Default dry_run for all invocations |

All fields optional — tools must work with partial context.

---

## 6. ToolRuntimeClient (`tool_runtime/client.py`)

Standard client for Module/Service layers:

| Method | Returns | Description |
|--------|---------|-------------|
| `invoke(tool_id, arguments, *, dry_run, context)` | `ToolResult` | Full pipeline invocation |
| `list_tools()` | `list[dict]` | Tool metadata only (no handlers) |
| `get_tool(tool_id)` | `dict\|None` | Single tool metadata |

**Guarantees:**
- Never bypasses `ToolPolicy`
- Never calls LLM
- Never writes Memory
- Uses independent `ToolInvocation`/`ToolResult`
- All errors captured in `ToolResult`

---

## 7. Module Integration Pattern

Module services should use `ToolRuntimeClient` as follows:

```python
from tool_runtime.integration import get_default_tool_runtime_client
from tool_runtime.context import ToolRuntimeContext

class MyModuleService:
    def process(self, config_text: str, workspace_id: str, run_id: str):
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(
            workspace_id=workspace_id,
            run_id=run_id,
            module="my_module",
            requested_by="module:my_module",
        )

        # Parse config text
        parse_result = client.invoke(
            "parser.parse_config_text",
            {"config_text": config_text},
            context=ctx,
        )

        if parse_result.status != "succeeded":
            return {"ok": False, "error": parse_result.summary}

        # Use structured output (not full config!)
        line_count = parse_result.output.get("line_count", 0)
        vendor = parse_result.output.get("vendor_hint", "unknown")
        return {"ok": True, "line_count": line_count, "vendor": vendor}
```

---

## 8. Agent / Skill Boundary

**Rule**: Agent does NOT directly call arbitrary tools.

```
CORRECT:
  Agent → Capability → Skill Adapter → Module Service → ToolRuntimeClient

WRONG (v0.1):
  Agent → ToolRuntimeClient (bypassing Module)
  Skill Adapter → ToolRuntimeClient (bypassing Module business logic)
```

**Current status**: No agent code was changed. `skill_executor.py` continues to call skill adapters which call module services. The integration contract establishes the future pattern without modifying existing behavior.

If future use cases require Agent-level tool access, it must be through a **special allowlist capability** — never a default-available path.

---

## 9. Job Context Propagation

Job Runtime does NOT directly call tools. The chain is:

```
Job → run_agent() → Agent → Capability → Skill → Module → ToolRuntimeClient
```

`job_id` is propagated through `ToolRuntimeContext`:

```python
ctx = ToolRuntimeContext(job_id=job_record.job_id, ...)
client.invoke("tool.id", args, context=ctx)
```

The `job_id` appears in:
- `ToolInvocation.job_id`
- `ToolResult` (via invocation)
- Trace/audit metadata (via `build_trace_metadata_from_tool_result`)

No Job Runtime code was changed — this contract documents the pattern.

---

## 10. Trace / Audit Metadata Contract

`build_trace_metadata_from_tool_result()` (`tool_runtime/integration.py`) produces safe metadata:

**Included:**
- invocation_id, tool_id, status, duration_ms
- redacted flag, artifact_ids
- dry_run, warning_count, error_count
- output_keys (structure only, not values)
- summary (≤200 chars)
- policy decision summary (no full arguments)

**Excluded:**
- Full output content
- Full arguments
- source_config, deployable_config
- Keys, passwords, tokens, community strings
- Absolute paths

---

## 11. Artifact Reference Contract

ToolResult carries `artifact_ids` — a list of artifact ID references:

- `artifact_ids` is always a **list of strings** (artifact IDs only)
- Artifact **content** is NEVER embedded in `ToolResult.output`
- `ToolResult.summary` is always a short text summary (≤500 chars)
- Trace/audit metadata carries artifact_ids but NOT artifact content

**Current built-in tools**:
- `artifact.list` returns metadata only (artifact_id, type, summary, sensitivity)
- `artifact.read_summary` returns safe summary (no full content)
- Other tools return small structured output — no artifact writes needed

---

## 12. Security Red Lines

1. Agent must not directly call arbitrary tools.
2. Skill must not bypass Module to call tools.
3. Module is the default orchestration boundary for tools.
4. `ToolRuntimeClient` must not bypass `ToolPolicy`.
5. `ToolResult` must not go directly into LLM context.
6. `ToolResult` must be summarized and redacted before any external use.
7. Real device execution is out of scope for v0.1.
8. SSH / Telnet / SNMP / nmap / ping sweep are out of scope for v0.1.
9. No public Tool HTTP API in v0.1.
10. No Tool UI in v0.1.
11. Tool invocations use independent `ToolInvocation`/`ToolResult` — not legacy `tool_calls`/`tool_results`.
12. Tool output must be redacted before return.

---

## 13. Non-Goals

This v0.1 integration contract explicitly does NOT:

- Require config_translation to use Tool Runtime
- Modify Agent executor logic
- Modify Job Runtime main logic
- Add HTTP API endpoints for tools
- Add UI for tool invocation
- Add real device execution
- Add SSH / Telnet / SNMP / nmap / ping sweep
- Add arbitrary shell
- Modify existing Module boundaries

---

## 14. Future Phases

- v0.2: Agent-supervised tool invocation with explicit allowlist capabilities
- v0.3: Job-level tool batching and progress tracking
- v1.0: Real device dry-run validation (no execution, schema check only)
