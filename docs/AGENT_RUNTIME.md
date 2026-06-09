# Agent Runtime

## Graph Architecture

Agent runtime uses **LangGraph** as primary execution engine, with a deterministic fallback runtime preserved for cases where LLM is blocked or unavailable.

### Entry Point

```python
def run_agent(
    user_input: str,
    workspace_id: str = "default",
    session_id: str | None = None,   # v3.1+ — associates run with conversation session
    intent: str = "",
    payload: dict | None = None,
    context_ref: str = "",
) -> dict:
```

When `session_id` is provided:
1. `NetworkAgentState.session_id` is set before graph execution
2. `memory_writer` → `write_run_record()` auto-associates the run with the session
3. First user input auto-titles the session (if title is generic)

### Graph Nodes (8 Trace Nodes)

```
router → context_loader → planner → skill_executor (orchestrator for chat/knowledge) → verifier → composer → memory_writer
```

| Node | Role |
|------|------|
| `router` | Resolves intent via Registry/Capability lookup |
| `context_loader` | Calls Context Runtime v0.2 to build context bundle (dynamic budget + dedup) |
| `planner` | Produces execution plan from resolved capability |
| `skill_executor` | Executes via capability → skill → adapter → module chain; for assistant_chat/knowledge_query, delegates to llm_orchestrator for agentic loop |
| `llm_orchestrator` | (embedded in executor) LLM agentic loop with function calling; disabled fallback via deterministic tool queries |
| `verifier` | Validates execution output against capability contract |
| `composer` | Assembles final response text (4 intent-specific paths) |
| `memory_writer` | Persists run summary to Memory store + associates with session; runs cleanup_expired + compact |

### Router

`agent/nodes/intent_router.py::_infer()` — keyword-based intent inference with ordered matching:

1. **assistant_first** (greetings, identity, help) → `assistant_chat`
2. **context_qa** (result/explanation queries) → `context_qa`
3. **LLM-related** (模型/llm/状态 etc, unless config-related) → `assistant_chat`
4. **INTENTS dict** (ordered) → first match wins:
   - `translate_config`: 翻译/厂商名 + config keywords (hostname, interface, ip address, ospf, vlan, acl, gigabitethernet, network 10./172./192.168., etc.)
   - `topology_draw`, `inspection_analyze`, `knowledge_search`, etc.
5. **Question-ending** (？/?/吗/呢) → `assistant_chat`
6. **Default** → `assistant_chat`

Config text detection: user can paste raw network config (e.g. `hostname R1\ninterface G0/0/1\n ip address 10.1.1.1`) and the router will match `translate_config` keywords without requiring explicit "translate" command.

### Composer

`agent/nodes/composer.py::compose()`:

| Intent | Path |
|--------|------|
| `assistant_chat` | `_compose_assistant_chat()` → try `safe_generate("assistant_chat")` with MiniMax-M3 → fallback `_assistant_response(state)` |
| `response_compose` / business | `safe_generate(task)` via prompt runtime |
| `context_qa` | `_compose_context_qa()` |
| Unknown | `_deterministic(state)` fallback |

### LLM Orchestrator

`agent/nodes/llm_orchestrator.py::orchestrate()` — agentic loop execution for `assistant_chat` and `knowledge_query` intents.

Flow:
1. LLM enabled → build tool definitions → send to LLM with function calling → parse tool calls → execute via ToolPolicy/ToolExecutor → feed results back to LLM → loop (up to 10 steps) → compose final response
2. LLM disabled → `_handle_llm_disabled()` → keyword-based tool matching → deterministic execution → compose response
3. LLM blocked → graceful degradation with `fallback_reason` recorded

Each LLM call passes through `safe_generate()` with input/output policy checks.

### LLM Blocked / Deterministic Fallback

When LLM is unavailable or blocked by policy:
- `_compose_assistant_chat()` catches all exceptions and falls to deterministic template
- Fallback reasons recorded in `state.context.llm.fallback_reason`:
  - `"llm disabled"` — config `enabled=false` or provider `disabled`
  - `"prompt_text_blocked"` — rendered prompt text fails input policy check
  - `"prompt_output_blocked"` — LLM output fails output policy check
  - `"response_policy: ..."` — LLM policy `check_response()` violation
  - `"provider unavailable: ..."` — API call exception
- Run still completes with degraded state marker

### Agent Tool Bridge

Tool execution for `assistant_chat` / `knowledge_query` is handled by the **LLM Orchestrator** (`agent/nodes/llm_orchestrator.py`), not the legacy `tool_planner.py`.

Rules:
- low-risk enabled tools can execute through `ToolRuntimeClient`
- medium-risk tools require explicit dry-run/预演 wording and run as dry-run
- high-risk or `requires_approval` tools are blocked with approval guidance
- returned `tool_invocations` contain safe metadata only

Note: `agent/nodes/tool_planner.py` contains legacy code superseded by `llm_orchestrator.py::_handle_llm_disabled()`. Consider removal.

### Trace

Currently 8 trace nodes are recorded per run, each with:
- Node type, start/end timestamps, input/output metadata (no secrets)
- Trace stored in run record, never includes full config or report content

## SSE Streaming

`POST /api/agent/run` with `stream=true` enables real-time Server-Sent Events:

| Event Type | Description |
|-----------|-------------|
| `node_start` | Node execution begins (node name, step index) |
| `node_progress` | Progress update from node (message, percent) |
| `tool_call` | LLM orchestrator calls a tool (tool name, args) |
| `tool_result` | Tool execution result (status, summary) |
| `text_chunk` | LLM-generated text chunk (streaming) |
| `node_end` | Node execution complete (elapsed, metadata) |
| `error` | Error occurred (node, message) |
| `done` | Full execution complete (final response) |

Implemented in `backend/api/sse.py`. The stream endpoint strips sensitive fields before emitting.

## Rate Limiting

IP-based rate limiting via `backend/core/rate_limit.py`:

- Per-IP token bucket algorithm
- Configurable bucket capacity and refill rate
- Applied as Flask `@app.before_request` middleware
- Returns 429 with `Retry-After` header when exceeded
- Tests disabled (`na_rate_limit_disabled=1`) via `test_platform_runtime_closure_v02.py`

## Context Compressor v0.2

`context/compressor.py` — v0.2 improvements:
- **Dynamic budget**: `resolve_budget_for_model()` allocates token budgets per model (MiniMax 64k, Qwen 128k, etc.)
- **Semantic deduplication**: removes redundant entries based on content similarity
- **Regex-sensitive keys**: patterns like `password`, `secret`, `community`, `snmp`, `tacacs`, `radius`, `key_string` trigger redaction
- Used by `context_loader` node for LLM context compaction

## Lifecycle Utilities

`runtime/lifecycle_base.py` — shared utilities extracted from `runtime/archive.py` and `runtime/retention.py`:

- `is_safe_path(base, target)` — path traversal prevention
- `get_active_refs(workspace_root)` — scans for active run references
- `scan_directory(path, pattern)` — safe directory scanning
- `write_audit(workspace_root, records)` — audit trail logging

Eliminates ~80 lines of duplicated code between archive and retention modules.
