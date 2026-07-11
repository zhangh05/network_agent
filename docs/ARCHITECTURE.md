# Architecture

This document describes the current Network Agent architecture only.

## Runtime Flow

```text
HTTP / WebSocket / SSE / Job entry
  -> AgentApp.submit_user_message (agent/app/facade.py)
  -> AgentThread + SessionManager (agent/core/thread.py)
  -> run_ssot_turn (agent/runtime/ssot_runtime.py)
  -> QueryLoop (core/runtime_engine/query_loop.py)
  -> LLM function calling + bounded tracking/retry/finalization
  -> ToolRuntimeClient.invoke / ToolRuntime.invoke_raw (core/runtime_engine/)
  -> registered canonical handlers
  -> AgentResult + RuntimeEvent timeline
```

After each turn, `run_ssot_turn` triggers LLM-driven memory writing (`agent/runtime/memory_write/llm_memory.py`), persists through `MemoryWriteGate`, and indexes into ContextStore for retrieval.

There is no public direct handler dispatch path. Any new entrypoint must converge at the SSOT runtime boundary before tool invocation.

## Runtime State

Durable runtime state is stored as:

- `TaskState`
- `RuntimeStep`
- `RuntimeEvent`
- `RuntimeCheckpoint`

The frontend timeline consumes runtime events and tool results instead of inferring state from ad hoc UI flags.

## Tool Boundary

The public tool namespace has 29 canonical IDs. `core/tools/tool_namespace.py`, `core/tools/manifest_registry.py`, and the default registry must remain count-aligned.

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

### Memory Pipeline

```text
1. Generation  (per turn end)
     run_ssot_turn → generate_memories() → LLM produces JSON memory items

2. Write
     MemoryRecord → MemoryWriteGate.write(status/confidence gating)
     MemoryStore._save() → disk JSON file
                      → ContextStore.put(item_type="memory_hit") [BM25 index]

3. Retrieval (per turn start, auto-injection)
     UnifiedRetriever.search_memory(BM25)
       → run_ssot_turn.retrieved_context_block
       → QueryLoop governed-context data boundary

4. Retrieval (evidence pipeline, explicit)
     MemoryQueryPlanner → MemoryRetriever → UnifiedRetriever.search_memory()
                        → MemoryItem list for response composition

5. Lifecycle
     confirm / reject / expire via MemoryStore API
     TTL auto-cleanup via cleanup_expired()
```

Key modules:
- `agent/runtime/memory_write/llm_memory.py` — LLM generation after each turn
- `agent/runtime/memory_write/llm_gate.py` — LLM quality scoring (1-5)
- `workspace/memory_governance.py` — MemoryRecord, MemoryStore, MemoryWriteGate
- `core/context/context_store.py` — BM25 index for retrieval

## Prompt Boundary

`core/runtime_engine/prompt_contract.py` is the production prompt SSOT. It owns
the QueryLoop planner contract, final-response contract, subagent system
constraints, and the delimited turn envelope. QueryLoop receives all canonical
tool schemas through function calling; it does not duplicate the catalog in
prompt text or use rules to hide tools.

Conversation history and governed memory/knowledge retrieval are injected as
explicit `data_only` sections. The current user request has its own boundary,
so retrieved text cannot silently become a system instruction. Task-specific
templates under `prompts/templates/` are separate non-runtime LLM jobs such as
memory gating, report summaries, and knowledge answers.
