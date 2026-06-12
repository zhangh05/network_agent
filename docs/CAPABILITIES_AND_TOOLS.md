# Capabilities And Tools

This document reflects current source and runtime construction.

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

## Public YAML Registry API

`GET /api/capabilities` uses `registry.loader.load_capabilities()`, not the runtime capability registry above.

Current public projection:

| Capability | Status | Module | Skill |
|---|---|---|---|
| `config.translate` | enabled | `config_translation` | `config_translation` |
| `config.review` | enabled | `config_translation` | `config_translation` |
| `knowledge.search` | enabled | `knowledge_base` | `knowledge_search` |
| `topology.draw` | planned | `topology` | `topology_draw` |
| `inspection.analyze` | planned | `inspection` | `inspection_analyze` |

## Tool Counts

Current runtime construction:

- Registered tools: 76
- Model-visible tools: 70
- Runtime capabilities: 7 total, 4 enabled, 3 planned

Registered but not model-visible:

- `weather.current`: disabled
- `weather.forecast`: disabled
- `news.search`: disabled
- `command.approved_exec`: disabled high-risk runtime tool
- `powershell.approved_script`: disabled high-risk runtime tool
- `knowledge.read_source`: backend/admin callable, `callable_by_llm=False`

## Safety Rules

- Tool visibility is fail-closed.
- Unknown LLM tool calls are rejected by `ToolRouter`.
- Disabled tools are not exposed to the model.
- High-risk runtime tools require approval state.
- Real device access and config push are not exposed to the model.
