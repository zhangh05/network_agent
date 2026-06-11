# Capabilities and Tools

This document reflects current source.

## Runtime Capability Registry

Defined in `agent/capabilities/builtin.py`.

| Capability | Status | Module | Tools |
|---|---|---|---:|
| `config_translation` | enabled | `config_translation` | 1 |
| `knowledge` | enabled | `knowledge` | 12 |
| `artifact` | enabled | `artifact` | 4 |
| `review` | enabled | `review` | 2 |
| `topology` | planned | `topology` | 2 |
| `inspection` | planned | `inspection` | 2 |
| `cmdb` | planned | `cmdb` | 3 |

Planned capabilities are not callable.

## Public YAML Registry API

`GET /api/capabilities` uses `registry.loader.load_capabilities()`, not the runtime registry above.

Current public projection:

| Capability | Status | Module | Skill |
|---|---|---|---|
| `config.translate` | enabled | `config_translation` | `config_translation` |
| `config.review` | enabled | `config_translation` | `config_translation` |
| `knowledge.search` | enabled | `knowledge_base` | `knowledge_search` |
| `topology.draw` | planned | `topology` | `topology_draw` |
| `inspection.analyze` | planned | `inspection` | `inspection_analyze` |

## Tool Counts

Current runtime counts:

- Registered tools: 73
- Model-visible tools: 70
- ToolRuntime tools: 55
- Runtime capability tools: 18

Registered but not model-visible:

- `command.approved_exec`: disabled high-risk runtime tool
- `powershell.approved_script`: disabled high-risk runtime tool
- `knowledge.read_source`: backend/admin callable, but `callable_by_llm=False`

## Safety Rules

- Tool visibility is fail-closed.
- Unknown LLM tool calls are rejected by `ToolRouter`.
- High-risk runtime tools require the approval path.
- Real device access and config push are not exposed to the model.
