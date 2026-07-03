# AGENTS.md

This file is the handoff contract for AI coding agents working in this repository.

## Non-Negotiable Rules

1. Keep the current architecture only. Do not add compatibility branches, old tool names, fallback APIs, or historical docs.
2. All tool invocation goes through the SSOT QueryLoop runtime and registered canonical handlers. Do not add alternate planner, dispatch, or compatibility paths.
3. All tools must be one of the 22 canonical IDs in `core/tools/tool_namespace.py`.
4. `workspace_id` must be explicit and validated at API boundaries. Empty values return 400.
5. Approval is for high-risk/destructive actions, not for ordinary read/list/query operations.
6. Memory writes go through `workspace.memory_governance.MemoryWriteGate`.
7. Do not commit runtime data, provider secrets, logs, build output, caches, or workspace contents.
8. Tool definitions are the single source of truth for tool capabilities — do not hardcode tool lists in prompts.

## Current Main Chain

```
Frontend
  -> backend/main.py routes or backend/ws/agent_ws.py
  -> agent.app.facade.AgentApp
  -> SSOTRuntimeEngine
     ├─ Fast-path classifier (greetings/definitions)
     ├─ Pre-planner guard (build_operational_clarification)
     └─ QueryLoop iterative LLM+tool loop
  -> ToolRuntime.invoke_raw() → registered handlers
  -> durable state, artifacts, memory, trace
```

### QueryLoop — `core/runtime_engine/query_loop.py`

The single tool-capable runtime loop plans, invokes tools, consumes results, tracks long-running tasks, records retry metadata, and produces the final answer.

**Architecture:**
```
User input
  → Context init + contract check
  → Fast-path (greetings/definitions bypass)
  → Pre-planner clarification (ambiguous login/command requests)
  → QueryLoop.run()
     ├─ build initial messages (system prompt + user request)
     ├─ while (iterations < max):
     │    ├─ auto-compact if messages > 40K chars
     │    ├─ invoke_llm(messages, tools) → LLMResponse
     │    ├─ if tool_calls present:
     │    │    execute tools (parallel read-only, serial writes)
     │    │    append tool results to messages
     │    │    continue loop
     │    └─ if no tool_calls:
     │         return response.content as final_response
     └─ max iterations → return error
```

**5 optimisations:**
1. **Prompt Cache** — tool definitions in sorted order, system+tools prefix never changes
2. **Planner+Finalizer merged** — single LLM stream outputs both tool_calls and natural language
3. **Iterative execution** — tool results fed back to LLM for dynamic decisions
4. **Streaming tool exec** — read-only tools execute in parallel, writes serialised
5. **Auto-compact** — old turns summarised when context exceeds COMPACT_THRESHOLD_CHARS (40K)

**Key files:**

| File | Purpose |
|------|---------|
| `core/runtime_engine/query_loop.py` | QueryLoop, StreamingToolExecutor, auto-compact |
| `core/runtime_engine/engine.py` | SSOTRuntimeEngine with QueryLoop integration |
| `core/runtime_engine/models.py` | SSOTRuntimeConfig (use_query_loop, max_query_loop_iterations) |
| `core/runtime_engine/tool_runtime.py` | ToolRuntime.invoke_raw() for direct handler execution |

**Tool name format:**
- LLM API uses double-underscore: `device__manage`, `exec__run`
- Internal code uses dots: `device.manage`, `exec.run`
- `_parse_tool_calls()` normalises `__` → `.`
- `_append_tool_round()` converts `.` → `__` for assistant messages

**Read-only vs Write tools:**
```python
_READ_ONLY_TOOLS = {
    "device.manage", "web.manage", "knowledge.manage",
    "workspace.file", "workspace.artifact", "workspace.metadata.get",
    "workspace.document.pdf.extract_text", "code.search",
    "report.manage", "text.analyze", "config.manage", "pcap.manage",
    "data.manage", "browser.manage", "skill.manage",
    "memory.manage", "system.manage", "git.manage",
}
# exec.run, inspection.manage, agent.manage are WRITE tools
```

## Canonical Tools

There are exactly 22 public tool IDs:

`agent.manage`, `browser.manage`, `code.search`, `config.manage`, `data.manage`, `device.manage`, `exec.run`, `git.manage`, `inspection.manage`, `knowledge.manage`, `memory.manage`, `pcap.manage`, `report.manage`, `skill.manage`, `system.manage`, `text.analyze`, `web.manage`, `workspace.artifact`, `workspace.document.pdf.extract_text`, `workspace.file`, `workspace.filestore`, `workspace.metadata.get`

If a change needs a new operation, add it behind an existing canonical tool unless there is a strong product reason to create a new public tool.

## Review Checklist

Before committing:

- Confirm QueryLoop is the only active tool-capable runtime path.
- Verify tool name normalisation: `__` → `.` on parse, `.` → `__` on append.
- Check `invoke_raw()` handles both sync and async handlers via `asyncio.new_event_loop()`.
- Ensure compaction is idempotent (no infinite loop on `middle_count <= 1`).
- Run focused tests for the changed layer.
- Inspect `git status --short` and stage only intended source/docs/tests.

Useful commands:

```bash
# Verify tool registry consistency
python3 - <<'PY'
from core.tools.tool_namespace import TOOL_NAMESPACE
from core.tools.canonical_registry import CANONICAL_REGISTRY
print(len(TOOL_NAMESPACE), len(CANONICAL_REGISTRY))
PY

# Verify QueryLoop module
python3 -c "
from core.runtime_engine.query_loop import (
    QueryLoop, StreamingToolExecutor,
    _compact_messages, _estimate_chars,
)
print('QueryLoop OK')
"

# Frontend typecheck
npm --prefix frontend run typecheck
```

## Local Cleanup

Safe cleanup targets:

- `.DS_Store`
- `__pycache__/`
- `.pytest_cache/`
- frontend build output
- generated audit reports

Preserve:

- `workspaces/default/`
- `workspaces/_runtime/`
- `config/providers/`
- `config/llm.local.yaml`
- running backend/frontend processes unless the user asks to restart
