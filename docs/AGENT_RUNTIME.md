# Agent Runtime

## Graph Architecture

Agent runtime uses **LangGraph** as primary execution engine, with a deterministic fallback runtime preserved for cases where LLM is blocked or unavailable.

### Graph Nodes (7 Trace Nodes)

```
router → context_loader → planner → executor → verifier → composer → memory_writer
```

| Node | Role |
|------|------|
| `router` | Resolves intent via Registry/Capability lookup |
| `context_loader` | Calls Context Runtime to build context bundle |
| `planner` | Produces execution plan from resolved capability |
| `executor` | Executes via capability → skill → adapter → module chain |
| `verifier` | Validates execution output against capability contract |
| `composer` | Assembles final response text |
| `memory_writer` | Persists run summary to Memory store |

### Router

- Resolves user intent against Capability registry
- Matches intent string → `capability_id` → dispatches to planner
- Unknown intent → default to `context_qa` or `response_compose`

### Executor Chain

```
capability → skill → adapter → module
```

- Capability: registry contract defining what can be done
- Skill: wraps module with entrypoints, LLM call flags, red lines
- Adapter: normalizes IO between skill and module
- Module: implementation unit (no direct LLM, no hardcoded paths)

### Context Loader

Calls `context.builder.build_context_bundle(context_ref)` from Context Runtime. Produces a `ContextBundle` containing execution context (for deterministic nodes) and safe LLM context (for LLM nodes).

### Composer

Uses prompt task selection via `_select_prompt_task()`:
- Determines which prompt template to use based on run context
- Routes to: `context_qa`, `job_failure`, `manual_review`, `report`, `artifact`, `result_summarize`, `response_compose`

### LLM Blocked / Deterministic Fallback

When LLM is unavailable or blocked by policy:
- Planner falls back to static plan map
- Composer uses deterministic text templates (no provider call)
- Verifier skips LLM-based checks
- Run still completes with degraded state marker

### Trace

Currently 7 trace nodes are recorded per run, each with:
- Node type, start/end timestamps, input/output metadata (no secrets)
- Trace stored in run record, never includes full config or report content
