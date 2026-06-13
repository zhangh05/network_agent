# Capabilities And Tools

This document reflects current source and runtime construction. It connects the
runtime capability registry, ToolRuntime catalog, and LLM-visible ToolRouter
surface.

## Runtime Capability Registry

Runtime capabilities are defined in `agent/capabilities/builtin.py`.

| Capability | Status |
|---|---|
| `config_translation` | enabled |
| `knowledge` | enabled |
| `artifact` | enabled |
| `review` | enabled |
| `topology` | planned |
| `inspection` | planned |
| `cmdb` | planned |

Planned capabilities are registered for roadmap visibility but are not callable.

## Public Registry API

`GET /api/capabilities` uses `registry.loader.load_capabilities()`, which projects the runtime `CapabilityRegistry` into the public registry shape. Legacy ids such as `config.translate`, `config.review`, and `knowledge.search` are compatibility aliases for lookup, not the canonical public rows.

Current public projection:

| Capability | Status | Module | Skill |
|---|---|---|---|
| `config_translation` | enabled | `config_translation` | `config_translation` |
| `knowledge` | enabled | `knowledge` | `knowledge_query` |
| `artifact` | enabled | `artifact` | `artifact_management` |
| `review` | enabled | `review` | `review_flow` |
| `topology` | planned | `topology` | `topology` |
| `inspection` | planned | `inspection` | `inspection` |
| `cmdb` | planned | `cmdb` | `cmdb` |

## Tool Counts

Current runtime construction:

- Registered tools: 76
- Model-visible tools: 75
- Runtime capabilities: 7 total, 4 enabled, 3 planned

Registered but not model-visible:

- `knowledge.read_source`: backend/admin callable, `callable_by_llm=False`

Enabled model-visible runtime tools with extra execution gates:

- `weather.current`, `weather.forecast`, and `news.search`: medium-risk real-time information tools backed by public Web search.
- `command.approved_exec` and `powershell.approved_script`: high-risk approved execution surfaces. They are visible to the LLM, but policy requires `approval_id` and allowlisted `command_id` / `script_id`; arbitrary shell or PowerShell text is not accepted.

## Safety Rules

- Tool visibility is fail-closed.
- Unknown LLM tool calls are rejected by `ToolRouter`.
- Disabled tools are not exposed to the model.
- Pure chat, capability-discovery, and business turns expose the full model-visible tool catalog after the registry safety filter.
- LLM-visible tool descriptions include `tool_id`, `risk`, `source`, and `approval` metadata so the model sees the safety context before choosing a tool.
- Capability tool handlers fail fast if their `handler_ref` cannot be resolved.
- Capability tools override same-id general runtime tools when they define the active business contract.
- High-risk runtime tools are visible but require approval state and allowlisted ids before execution.
- Real device access and config push are not exposed to the model.
