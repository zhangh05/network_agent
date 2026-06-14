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

- Registered tools: 88
- Model-visible tools: 88
- Runtime capabilities: 7 total, 4 enabled, 3 planned
- Canonical namespace ids: 88
- Execution tool ids: 88
- Legacy aliases: compatibility only; aliases are not registered as tools

## v2.2 Tool Namespace

The v2.2 tool namespace separates display/routing ids from execution ids:

```text
User request
→ Category
→ Group
→ Tool Action
→ canonical_tool_id
→ legacy alias mapping
→ policy / approval
→ executor
```

Execution remains on the stable 88 ids. LLM and frontend catalog surfaces use
canonical ids such as:

| Category | Example canonical id | Execution id |
|---|---|---|
| host | `host.shell.exec` | `shell.exec` |
| workspace | `workspace.file.read` | `file.read` |
| workspace | `workspace.artifact.save` | `artifact.save_result` |
| network | `network.config.parse` | `parser.parse_config_text` |
| web | `web.docs.official_search` | `web.official_doc_search` |
| runtime | `run.list` | `run.list_recent` |
| memory | `memory.profile.get` | `memory.get_profile` |
| report_data | `report.markdown.render` | `report.render_markdown` |
| agent | `agent.role.list` | `agent.list_roles` |

Namespace source and checks:

- `tool_runtime/tool_namespace.py`
- `tool_runtime/tool_namespace_data.py`
- `baselines/canonical_tool_ids_v2.2.txt`
- `baselines/execution_tool_ids_v2.2.txt`
- `baselines/tool_aliases_v2.2.json`
- `scripts/inspect_tool_namespace.py`

`GET /api/tools/catalog` returns both a flat compatibility list and a
`categories[]` tree for frontend directory display.

## v2.2.1 Tool Chain Routing

v2.2.1 keeps the same namespace/execution/alias mapping and upgrades the
runtime scene router from a single category/group decision to a multi-category
tool-chain plan:

```text
User request
→ signals
→ primary_category
→ categories[]
→ groups{}
→ candidate_tools[]
→ tool_chain[]
→ ToolRouter canonical function names
```

Example request:

```text
帮我分析上传的华三配置，并整理成报告保存
```

Expected routing shape:

```text
primary_category: network
categories: workspace, network, report_data
candidate_tools:
  workspace.file.read
  workspace.file.preview
  network.config.parse
  network.interface.extract
  network.route.extract
  report.markdown.render
  workspace.artifact.save
```

`tool_chain[]` orders the LLM's work:

1. Read uploaded or workspace files.
2. Parse the network configuration offline.
3. Extract interface and route facts.
4. Render and save the report artifact.

Host tools are included only for explicit local-machine requests. Network
configuration analysis uses `network.*` offline text tools, not `host.shell.*`.

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
