# Tool Runtime Integration Contract v0.3

> **Status**: Integration contract established — no real device execution  
> **Version**: v0.3  
> **Date**: 2026-06-09  
> **Depends on**: [Tool Runtime](./TOOL_RUNTIME.md)

Current full harness evidence: `1351 passed, 7 skipped`.

Current integration status: `ToolRuntimeContext`, `ToolRuntimeClient`, safe trace metadata integration, HTTP Tool API, Tool Catalog UI, and supervised Agent Tool Bridge are implemented. `ToolRuntimeClient.invoke()` writes allowlisted metadata to the observability trace store when `trace_id` is provided in context.

Public Tool HTTP APIs and Tool Catalog UI exist in v0.3. Agent code still must not freely call arbitrary tools; ordinary business orchestration stays behind Capability → Skill → Module, while explicit low-risk tool requests may go through the supervised Agent Tool Bridge.

---

## 1. Purpose

Define the integration boundary between Tool Runtime and the rest of the Network Agent system — Module, Skill, Agent, Job, Trace, Artifact.

This contract ensures that:
- Module / Service layers have a **standard, controlled** way to invoke tools
- Tool invocations carry proper **context** (workspace, run, job, caller identity)
- Tool results enter trace/audit as **safe metadata only**
- **Agent never directly calls arbitrary tools**
- **Agent Tool Bridge calls only enabled low-risk tools automatically, medium tools as explicit dry-run, and blocks high-risk tools for approval**
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
| `session_id` | str\|None | Current session (v3.1+) |
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
  Agent → Agent Tool Bridge → ToolRuntimeClient (explicit safe low-risk tool request)

WRONG:
  Agent → ToolRuntimeClient (bypassing Module)
  Agent → high-risk ToolRuntimeClient call without approval
  Skill Adapter → ToolRuntimeClient (bypassing Module business logic)
```

**Current status**: `agent/nodes/tool_planner.py` implements Agent Tool Bridge. It handles explicit tool catalog questions, direct tool IDs, and a small set of natural-language mappings to low-risk tools such as `runtime.health`, `run.list_recent`, `workspace.get_metadata`, `artifact.list`, and `knowledge.search`.

Safety behavior:
- low risk + enabled + no approval required: execute through `ToolRuntimeClient`
- medium risk: dry-run only when the user explicitly asks for dry-run/预演
- high risk or `requires_approval`: block and route the user to Tool Catalog approval

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
9. Public Tool HTTP APIs must enforce policy and approval status.
10. Tool UI must not cache approval IDs in persistent browser storage.
11. Tool invocations use independent `ToolInvocation`/`ToolResult` — not legacy `tool_calls`/`tool_results`.
12. Tool output must be redacted before return.

---

## 13. Non-Goals

This v0.1 integration contract explicitly does NOT:

- Require config_translation to use Tool Runtime
- Modify Job Runtime main logic
- Add real device execution
- Add SSH / Telnet / SNMP / nmap / ping sweep
- Add arbitrary shell
- Modify existing Module boundaries

---

## 14. Future Phases

- v0.4: Job-level tool batching and progress tracking
- v1.0: Real device dry-run validation (no execution, schema check only)
