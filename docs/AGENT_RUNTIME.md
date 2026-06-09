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

### Graph Nodes (7 Trace Nodes)

```
router → context_loader → planner → executor → verifier → composer → memory_writer
```

| Node | Role |
|------|------|
| `router` | Resolves intent via Registry/Capability lookup |
| `context_loader` | Calls Context Runtime to build context bundle |
| `planner` | Produces execution plan from resolved capability |
| `executor` | Executes via capability → skill → adapter → module chain; for assistant_chat, may use supervised Tool Bridge for explicit safe tool requests |
| `verifier` | Validates execution output against capability contract |
| `composer` | Assembles final response text |
| `memory_writer` | Persists run summary to Memory store + associates with session (v3.1+) |

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

`agent/nodes/tool_planner.py` is called from the executor for `assistant_chat` only. It handles explicit tool catalog questions and direct safe tool requests without turning the Agent into an arbitrary tool runner.

Rules:
- low-risk enabled tools can execute through `ToolRuntimeClient`
- medium-risk tools require explicit dry-run/预演 wording and run as dry-run
- high-risk or `requires_approval` tools are blocked with approval guidance
- returned `tool_invocations` contain safe metadata only

### Trace

Currently 7 trace nodes are recorded per run, each with:
- Node type, start/end timestamps, input/output metadata (no secrets)
- Trace stored in run record, never includes full config or report content
