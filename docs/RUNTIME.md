# Runtime

The active runtime is the Codex-style loop under `agent/runtime/`.

## Main Flow

1. `backend/api/agent_routes.py` receives `POST /api/agent/message`.
2. `AgentApp.submit_user_message()` creates or reuses an `AgentSession`.
3. `AgentThread.submit()` submits an `AgentOp`.
4. `AgentSession` creates an `AgentTurn`.
5. `agent/runtime/loop.py::run_turn()` builds context, calls the LLM, handles tool calls, and returns `AgentResult`.
6. `_persist_run_record()` best-effort writes a run record so sessions can reconstruct messages.

## Runtime Services

`agent/runtime/services.py::default_runtime_services()` wires:

- `ToolRouter`
- `ToolRegistry`
- `SkillRegistry`
- `ModuleRegistry`
- `SkillSelector`
- audit event, trace, and rollout recorders
- runtime `CapabilityRegistry`

## Tool Loop

- `ToolRouter.model_visible_tools()` returns OpenAI-format tool definitions.
- LLM-safe tool names use `__` instead of `.`.
- `ToolRouter.build_tool_call()` rejects unknown or non-visible tool calls.
- `ToolRouter.dispatch()` executes through registered capability handlers or ToolRuntime.
- The Agent does not directly call arbitrary tools; it goes through `ToolRouter`.
- Capability modules orchestrate tools and business services; a skill does not bypass its module boundary.
- `ToolResult` data must be summarized or redacted before it is placed back into LLM context.
- The public Tool HTTP API (`/api/tools/invoke`) is policy and approval gated.
- Tool invocation objects are represented by ToolRuntime `ToolInvocation`, not legacy `agent/state.py` `tool_calls`.
- SSH, Telnet, SNMP, and nmap are not exposed to the model.

## Persistence

New runtime turns are projected into legacy-compatible run records by `_persist_run_record()` in `agent/runtime/loop.py`. This is why `GET /api/sessions/<id>/messages` can reconstruct chat history.

## Legacy Runtime

`agent/legacy/` remains for compatibility with `/api/agent/run`. It is not the primary runtime path.
