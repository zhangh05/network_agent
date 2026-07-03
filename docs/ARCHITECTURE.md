# Architecture

This document describes the current Network Agent architecture only.

## Runtime Flow

```text
HTTP / WebSocket / SSE / Job entry
  -> AgentApp.submit_user_message
  -> SessionManager + AgentThread
  -> SSOT Runtime adapter
  -> SSOTRuntimeEngine
  -> QueryLoop
  -> ToolRuntimeClient.invoke / ToolRuntime.invoke_raw
  -> registered canonical handlers
  -> AgentResult + RuntimeEvent timeline
```

There is no public direct handler dispatch path. Any new entrypoint must converge at the SSOT runtime boundary before tool invocation.

## Runtime State

Durable runtime state is stored as:

- `TaskState`
- `RuntimeStep`
- `RuntimeEvent`
- `RuntimeCheckpoint`

The frontend timeline consumes runtime events and tool results instead of inferring state from ad hoc UI flags.

## Tool Boundary

The public tool namespace has 22 canonical IDs. `core/tools/tool_namespace.py`, `core/tools/manifest_registry.py`, and the default registry must remain count-aligned.

Tool execution requires:

- canonical tool id
- manifest
- explicit `requested_by`
- workspace/session/run context when available
- risk policy
- redacted result
- audit/trace event

## Business Capability Boundary

`agent/capabilities/catalog.py` is a catalog, not a dispatcher. It maps business capability descriptions to recommended canonical tools for prompt/UI guidance.

## Workspace Boundary

No backend route should silently create or infer a workspace. Missing or invalid `workspace_id` returns a client error. Runtime stores, memory, artifacts, sessions, runs, and approvals are all workspace-scoped.

## Memory Boundary

Memory is governed by `MemoryWriteGate`. Raw writers are not active paths. Retrieval returns only active, non-expired records in the same workspace and relevant scope.
