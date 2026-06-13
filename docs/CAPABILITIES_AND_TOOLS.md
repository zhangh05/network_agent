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

- Registered tools: 86
- Model-visible tools: 86
- Runtime capabilities: 7 total, 4 enabled, 3 planned

Registered but not model-visible:

- `knowledge.read_source`: backend/admin callable, `callable_by_llm=False`

Removed duplicate/auxiliary runtime tools:

- Runtime `knowledge.*` helpers were removed from ToolRuntime registration in favor of capability-level `knowledge.query` / import / chunk tools.
- Runtime `artifact.search`, `artifact.read_content_safe`, `artifact.tag`, and `artifact.delete_soft` were removed in favor of capability-level `artifact.list` / `artifact.read` / `artifact.diff` / `artifact.export` plus `artifact.save_result`.
- Smoke-test and preview-only tools such as `command.dry_run_echo`, `runtime.selfcheck`, retention/archive previews, and session create/archive were removed from the default ToolRuntime catalog.

Enabled model-visible runtime tools with extra execution gates:

- `weather.current` and `weather.forecast`: medium-risk real-time tools backed first by structured Open-Meteo public weather data, with public Web search as fallback.
- `news.search`: medium-risk real-time information tool backed by public Web search.
- `shell.exec`, `powershell.exec`, and `python.exec`: high-risk approved execution surfaces. They are visible to the LLM, but policy requires `approval_id` and allowlisted `command_id` / `script_id`; arbitrary shell, PowerShell, or Python text is not accepted.

## Safety Rules

- Tool visibility is fail-closed.
- Unknown LLM tool calls are rejected by `ToolRouter`.
- Disabled tools are not exposed to the model.
- Pure chat, capability-discovery, and business turns expose the curated model-visible primary tool catalog after the registry safety filter. Registered auxiliary compatibility tools remain callable by backend/API paths but are not default LLM choices.
- LLM-visible tool descriptions include `tool_id`, `risk`, `source`, and `approval` metadata so the model sees the safety context before choosing a tool.
- LLM-visible tool descriptions preserve the full runtime guidance text; OpenAI-compatible parameters are normalized to `type=object`, `properties`, and `required` for every tool.
- Capability tool handlers fail fast if their `handler_ref` cannot be resolved.
- Capability tools override same-id general runtime tools when they define the active business contract.
- High-risk runtime tools are visible and require user approval via the frontend approval dialog before execution.
- Real device access and config push are not exposed to the model.
