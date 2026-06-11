# Agent Runtime

> **Status (v1.0.2)**：v0.6+ 起实际生效的 runtime 是 **Codex-style agentic loop**（`agent/runtime/loop.py` + `agent/core/{session,thread,turn,turn_context,op}.py`），**不**是 LangGraph。本文档**主体**（Graph Architecture / Nodes / Tool Planner / Trace / SSE / Rate Limiting）描述的是**早期 v0.4-v0.5 的 LangGraph runtime**，仅作为历史参考。新 runtime 的关键路径见末尾 **§ 14 新 runtime (Codex-style loop)**。

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
| `assistant_chat` | `_compose_assistant_chat()` → try `safe_generate("assistant_chat")` (which wraps `invoke_llm()`, the unified entry point) with MiniMax-M3 → fallback `_assistant_response(state)` |
| `response_compose` / business | `safe_generate(task)` via prompt runtime → `invoke_llm()` |
| `context_qa` | `_compose_context_qa()` |
| Unknown | `_deterministic(state)` fallback |

### LLM Orchestrator

`agent/nodes/llm_orchestrator.py::orchestrate()` — agentic loop execution for `assistant_chat` and `knowledge_query` intents.

Flow:
1. LLM enabled → build tool definitions → send to LLM with function calling → parse tool calls → execute via ToolPolicy/ToolExecutor → feed results back to LLM → loop (up to 10 steps) → compose final response
2. LLM disabled → `_handle_llm_disabled()` → keyword-based tool matching → deterministic execution → compose response
3. LLM blocked → graceful degradation with `fallback_reason` recorded

Each LLM call passes through `invoke_llm()` (single entry point) → `provider.generate()`. Callers use `safe_generate()` (public API) which wraps `invoke_llm()` with non-blocking input/output policy checks and returns `SafeLLMOutput`.

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
- Tool names use bidirectional mapping: `.` (internal) ↔ `__` (LLM-safe), via `to_llm_tool_name()` / `from_llm_tool_name()`
- `invoke_llm()` sends tools with LLM-safe names; orchestrator converts back before `_execute_tool()`
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

## 14. 新 runtime (Codex-style loop, v0.6+, 实际生效)

v0.6+ 起, 实际响应 `/api/agent/message` 请求的是 `agent/runtime/loop.py::run_turn`（Codex-style 多步 LLM 工具调用循环）, 不是上文描述的 LangGraph。

### 14.1 关键类

| 类 | 文件 | 字段 |
|---|---|---|
| `AgentSession` | `agent/core/session.py` | `session_id`, `workspace_id`, `services` |
| `AgentThread` | `agent/core/thread.py` | `thread_id`, `turns[]`, `messages[]` |
| `AgentTurn` | `agent/core/turn.py` | `turn_id`, `op`, `final_response`, `tool_calls[]`, `warnings[]`, `errors[]`, `context: TurnContext` |
| `AgentOp` | `agent/protocol/op.py` | `user_input`, `session_id`, `workspace_id`, `intent` |
| `TurnContext` | `agent/core/turn_context.py` | `turn_id`, `session_id`, `workspace_id`, `user_input`, `module_snapshot`, `skill_snapshot`, `capability_manifest`, `tools_available`, `system_prompt`, `memory_summary`, `metadata` |
| `AgentResult` | `agent/runtime/result.py` | `ok`, `final_response`, `events[]`, `trace_id`, `session_id`, `turn_id`, `tool_calls[]`, `warnings[]`, `errors[]`, `metadata` |
| `RuntimeContextMessage` | `agent/protocol/message.py` | 注入到 LLM 的 system message |

### 14.2 run_turn 主循环

```python
def run_turn(session, turn, services=None) -> AgentResult:
    context = services.context_builder.build(turn)
    messages = _build_initial_messages(context, services)

    for step in range(MAX_STEPS):         # MAX_STEPS = 8
        resp = invoke_llm(messages, services)
        if resp.has_tool_calls:
            for tc in resp.tool_calls:
                tool_result = services.tool_runtime.invoke(tc)
                messages.append(tool_result)
            continue
        else:
            return _build_success_result(...)

    return _build_max_steps_result(...)
```

**4 个 return 出口**：
1. `success` — LLM 没 tool_call, 直接出 final_response
2. `provider_error` — `invoke_llm` 抛错 (LLM 服务不可用)
3. `timeout` — `invoke_llm` 抛 `TimeoutError`
4. `max_steps` — 跑满 8 步仍没收敛

### 14.3 run 落盘（v1.0.2 fix）

**Bug**：v0.6+ 的新 runtime 用 dataclass-based `Turn/Session/TurnContext`, 跟 legacy `NetworkAgentState` 字段对不上. legacy `agent/legacy/memory_writer.py` 调 `write_run_record()` 落盘 + 触发 `add_run_to_session()`. 新 runtime 4 个 return 出口都没调, `session.run_ids` 永远 `[]`, `/api/sessions/<id>/messages` 永远 `[]`, 前端 plan-C background fetch 永远空.

**Fix**（`agent/runtime/loop.py::run_turn`）:
- 加 `_persist_run_record(session, turn, result, context)` adapter, 把 dataclass 字段投影成 `SimpleNamespace`, 让 `write_run_record()` 能识别.
- 4 个 return 出口前各调一次.
- `try/except Exception: pass` 包裹 — 持久化失败**不**会炸 turn.
- 失败也是历史（failed turn 也落盘）.

Adapter 投影映射:

| legacy NetworkAgentState | 新 runtime (dataclass) |
|---|---|
| `state.request_id` | `turn.turn_id` |
| `state.session_id` | `session.session_id` |
| `state.user_input` | `turn.op.user_input` |
| `state.intent` | `context.metadata["intent"]` |
| `state.context["llm"]` | `context.metadata["llm"]` |
| `state.active_module` | `context.module_snapshot["module_id"]` |
| `state.selected_skill` | `context.skill_snapshot["skill_id"]` |
| `state.runtime_mode` | `"codex_v1"` (常量) |
| `state.final_response` | `result.final_response` |
| `state.warnings` | `result.warnings` |
| `state.trace_id` | `result.trace_id` |
| `state.error` | `result.errors[0]` if any |
| `state.skill_results` | `result.tool_calls[*].metadata` 里 `deployable_config` / `manual_review` / `unsupported` / `semantic_near` / `audit` key |

### 14.4 Live 验证（v1.0.2）

```bash
$ SID=$(curl -s -X POST /api/sessions -d '{"workspace_id":"default","title":"t"}' | jq -r .session.session_id)
$ curl -X POST /api/agent/message -d "{\"message\":\"hi\",\"workspace_id\":\"default\",\"session_id\":\"$SID\"}" -m 90
{"ok":true,"turn_id":"01c13c6b-...","session_id":"c621dbdbde06400c", ...}

$ curl /api/sessions/$SID?workspace_id=default
{ "session": { "run_ids": ["01c13c6b-..."] } }  # v1.0.2 之前永远 []

$ curl /api/sessions/$SID/messages
{ "ok":true,"count":2,"messages":[
  {"role":"user",      "content":"hi",                  "run_id":"01c13c6b-..."},
  {"role":"assistant", "content":"Hi! 👋 ...",         "run_id":"01c13c6b-..."}
]}
```

### 14.5 测试

- `harness/test_loop_persistence.py` (3 case)
  - `test_persist_creates_run_record_and_links_to_session` — success 路径, `get_run` + `get_session` 都拿得到
  - `test_persist_handles_failed_turn` — `ok=False` 也落盘
  - `test_persist_isolates_two_turns` — 同 session 多 turn 累积, `get_session_messages` 拿得到
