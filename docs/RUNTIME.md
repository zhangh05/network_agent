# Runtime

The active runtime is the Codex-style loop under `agent/runtime/`.

> **v2.1.2**: Added comprehensive tool-use intelligence — scene-based routing,
> host/device boundary distinction, unified approval phrasing, tool failure
> fallback strategies, and `tool_decision` transparency in AgentResult.
> See [TOOL_USE_POLICY.md](TOOL_USE_POLICY.md) for the full policy.

## Main Flow

1. `backend/api/agent_routes.py` receives `POST /api/agent/message`.
2. `AgentApp.submit_user_message()` creates or reuses an `AgentSession`.
3. `AgentThread.submit()` submits an `AgentOp`.
4. `AgentSession` creates an `AgentTurn`.
5. `agent/runtime/loop.py::run_turn()` builds context, calls the LLM, handles tool calls, and returns `AgentResult`.
6. `_persist_run_record()` writes run/session/message state for UI history and audit pages.

## Runtime Services

`agent/runtime/services.py::default_runtime_services()` wires:

- `ToolRouter`
- `ToolRegistry`
- `SkillRegistry`
- `ModuleRegistry`
- `SkillSelector`
- audit event, trace, and rollout recorders
- runtime `CapabilityRegistry`

## Context Build

Runtime context includes:

- user request and recent session history
- compacted conversation state
- workspace metadata
- available capabilities, skills, and model-visible tools
- unified RAG evidence from `context/retrieval.py`
- knowledge citations (`[K...]`) and memory citations (`[M...]`)

The v2.1.2 system prompt (`agent/runtime/prompts.py`) now includes:
- **6 Tool-Use Principles** (P1-P6): host/device boundary, tool-first mindset,
  approval strategy, failure→fallback, output structure, scene-based selection.
- **Prohibited Phrases**: "没有真实设备访问能力" is ONLY allowed for remote device
  connection requests — NEVER for local host queries, uploaded files, or
  knowledge base searches.
- **Scene-based routing**: The tool adapter prompt
  (`agent/llm/tool_adapter.py::build_system_prompt_with_tools`) provides A-J
  scene categories with recommended tools for each.

## Tool Loop

- `ToolRouter.model_visible_tools()` returns OpenAI-compatible tool definitions.
- LLM-safe tool names use `__` instead of `.`.
- LLM-visible tool descriptions include safety metadata: `tool_id`, `risk`, `source`, and `approval`.
- Tool parameter schemas are normalized before reaching the LLM so every function has an object schema with `properties` and `required`.
- `ToolRouter.build_tool_call()` rejects unknown or non-visible tool calls.
- `ToolRouter.dispatch()` executes through registered capability handlers or ToolRuntime.
- Capability handlers must resolve at registry build time; a broken `handler_ref` fails fast.
- Capability tools are the business contract and override same-id general runtime tools when both exist.
- `ToolResult` data is projected through a small allowlist before it returns to LLM context.
- SSH, Telnet, SNMP, nmap, ping sweep, and config push are not exposed to the model.
- The Agent does not directly call arbitrary implementation functions.
- Any public Tool HTTP API must remain policy and approval gated, with high-risk execution requiring an approved `approval_id`.
- Sub-agent tool (`agent.spawn`) delegates work to child agent threads with `max_turns≤3`, restricted tool set, and no recursive nesting.
- `shell.exec` / `powershell.exec` are high-risk tools that run ON THE LOCAL HOST — NOT on remote network devices.
  They require approval via the approval dialog.

### v2.1.2 Tool Decision Transparency

Each `AgentResult` now includes:

- **`tool_decision`**: structured dict with `needed`, `selected_tools`, `failed_tools`,
  `blocked_by`, `approval_required`, and `reason` fields.
- **`no_tool_reason`**: human-readable string explaining why no tools were called
  (e.g., `tools_not_needed`, `blocked_by_hook`, `token_limit_exceeded`).

The frontend Inspector and RunsPage display `tool_decision` in a new "工具决策"
collapsible section.

### Execution Model

- A Module orchestrates Tool use for business behavior; a Skill provides task instructions.
  Skill does not bypass its Module service.
- The Agent routes model-visible requests through `ToolRouter`, then through a
  capability handler or Tool Runtime `ToolInvocation`.

### v2.1.2 Approval Strategy

Unified approval phrasing:
- Read-only: "可以执行。该命令只读不修改系统，按策略需要批准。将执行 {command}。请回复'批准执行'。"
- Write: "可以使用 {tool_id} 写入 workspace artifact。请回复'批准执行'。"
- Delete: "需明确批准。将删除/软删除 {target}，范围 {scope}。请回复'批准删除'。"

### v2.1.2 Failure → Fallback

Each tool category has explicit fallback paths (see `_default_tool_next_actions`
in `tool_runtime/general_tools/registry.py` and [TOOL_USE_POLICY.md](TOOL_USE_POLICY.md)).

## Persistence

Runs are stored under `workspaces/<workspace_id>/runs/`. Session messages are stored under `workspaces/<workspace_id>/sessions/`. Runtime status files under `workspaces/_runtime/` are operational state and should not be committed as documentation.

## Deterministic Compatibility Pipeline

`agent/legacy/` remains as a deterministic compatibility pipeline for
registry-backed module turns, knowledge queries, trace/timeline projection, and
release regression coverage. It is reached only through current entry points
such as `POST /api/agent/message`; it is not a separate public Agent API.
