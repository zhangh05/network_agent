# Runtime

The active runtime is the Codex-style loop under `agent/runtime/`.

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

The system prompt requires citation ids when context sources are present and tells the model to say when evidence is insufficient. It also directs the model to proactively call Web, knowledge, artifact, or runtime tools for current facts, vendor/standards documentation, URL summaries, news/weather, and citation-heavy answers instead of guessing from memory.

Per-turn skill selection controls which skill instructions are injected, not which primary tools are hidden from the LLM. The runtime builds a fresh `ToolRouter` for each turn and exposes the curated model-visible primary catalog after the registry safety filter. Duplicate runtime helpers and smoke-test tools are removed from registration or kept backend-only, so pure chat, capability discovery, and business turns can call strong tools such as Web search, webpage summary, structured weather, knowledge query/import/chunk tools, artifact tools, review tools, and config translation when needed.

Every LLM-visible tool description includes `tool_id`, `risk`, `source`, and `approval` metadata. The model sees the risk context before deciding to call a tool, while disabled, forbidden, planned, or non-LLM-callable tools remain absent from the tool list.

## Tool Loop

- `ToolRouter.model_visible_tools()` returns OpenAI-compatible tool definitions.
- LLM-safe tool names use `__` instead of `.`.
- LLM-visible tool descriptions include safety metadata: `tool_id`, `risk`, `source`, and `approval`.
- Tool parameter schemas are normalized before reaching the LLM so every function has an object schema with `properties` and `required`.
- `ToolRouter.build_tool_call()` rejects unknown or non-visible tool calls.
- `ToolRouter.dispatch()` executes through registered capability handlers or ToolRuntime.
- Capability handlers must resolve at registry build time; a broken `handler_ref` fails fast.
- Capability tools are the business contract and override same-id general runtime tools when both exist.
- `ToolResult` data is projected through a small allowlist before it returns to LLM context. Citation-ready web fields, source summaries, warnings, next actions, artifact ids, and safe previews are preserved; arbitrary raw content, source configs, deployable configs, secrets, and tokens are not.
- SSH, Telnet, SNMP, nmap, ping sweep, and config push are not exposed to the model.
- The Agent does not directly call arbitrary implementation functions. It routes model-visible requests through `ToolRouter`, then through a capability handler or Tool Runtime `ToolInvocation`.
- A Module orchestrates Tool use for business behavior; a Skill provides task instructions. Skill does not bypass its Module service.
- Any public Tool HTTP API must remain policy and approval gated, with high-risk execution requiring an approved `approval_id`.
- Sub-agent tool (`agent.spawn`) delegates work to child agent threads with `max_turns≤3`, restricted tool set (no sub-agent spawning), and no recursive nesting. Sub-agents cannot spawn further sub-agents.
- `python.exec` is a high-risk approved execution tool that runs allowlisted Python scripts with `approval_id` gating, similar to `shell.exec` and `powershell.exec`.

## Persistence

Runs are stored under `workspaces/<workspace_id>/runs/`. Session messages are stored under `workspaces/<workspace_id>/sessions/`. Runtime status files under `workspaces/_runtime/` are operational state and should not be committed as documentation.

## Legacy Runtime

`agent/legacy/` (historical only, `/api/agent/run` REMOVED in v2.1.1). It is not the primary Workbench path.
