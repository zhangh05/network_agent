# Retired Surfaces

Network Agent is a **new design platform**, not a legacy framework migration.

The following names are **retired/prohibited surfaces** that have been physically removed from the codebase. They are preserved here only as a record of what must **never be restored**.

## Retired API

| Name | Status | Replacement |
|------|--------|-------------|
| `/api/translate` | **RETIRED** | `POST /api/modules/config-translation/translate` |
| Port 8020 | **RETIRED** | Unified port 8010 |

## Retired Code

| Name | Status | Replacement |
|------|--------|-------------|
| `backend/services/config_translation` | **RETIRED** | `modules/config_translation/backend/service.py` |
| `GraphAgent` | **RETIRED** | LangGraph `agent/graph.py` → `agent/nodes/*.py` |
| `network-translator` | **RETIRED** | `modules/config_translation/core/rule_translator.py` |
| `legacy/apps/` | **PHYSICALLY REMOVED** | None — removed entirely |

## Retired Naming

| Name | Status | Current |
|------|--------|---------|
| `tool_calls`/`tool_results` in agent/state | **DEPRECATED** alias | `skill_calls`/`skill_results` (primary) |
| `external_tool` as skill type | **DEPRECATED** | `ToolSpec`/`ToolRegistry` (Tool Runtime) |
| `MiniMax-M1` as default model | **PROHIBITED** | `MiniMax-M3` |

## Retired Defaults

| Pattern | Status | Current |
|---------|--------|---------|
| `old PROMPTS` as default prompt path | **PROHIBITED** | `prompts/registry.yaml` |

## Current Formal Entries

| API | Description |
|-----|-------------|
| `POST /api/agent/run` | Agent execution |
| `POST /api/modules/config-translation/translate` | Config translation |
| `POST /api/jobs` | Job management |
| `GET /api/runs/recent` | Recent run history |
| `GET /api/runtime/health` | Runtime diagnostics |
| `GET /api/runtime/selfcheck` | Workspace selfcheck |
| `GET /api/workspaces/<id>/retention/preview` | Retention preview |
| `GET /api/workspaces/<id>/archive/preview` | Archive preview |

## Anti-Regression

- `harness/test_ui_api_contract.py` — checks that retired surfaces are absent
- `harness/test_design_purity_antiregression.py` — 37 regression gates
- `harness/test_source_integrity_runtime_safety.py` — format + boundary + redaction

Any attempt to restore a retired surface **will fail the test suite**.
