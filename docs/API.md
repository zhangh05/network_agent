# API

Current API routes are Flask routes registered by `backend/main.py` and `backend/api/*_routes.py`.

## Core

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Basic process health |
| GET | `/api/version` | Version metadata |
| GET | `/api/runtime/summary` | Safe runtime counts for UI status: capability totals and tool visibility |
| GET | `/api/agent/status` | Agent status |
| POST | `/api/agent/message` | Main Codex-style runtime turn |
| POST | `/api/agent/run` | Legacy-compatible agent run, supports `stream=true` |

## Sessions

| Method | Path |
|---|---|
| GET/POST | `/api/sessions` |
| GET | `/api/sessions/default` |
| GET/PUT/DELETE | `/api/sessions/<session_id>` |
| POST | `/api/sessions/<session_id>/archive` |
| POST | `/api/sessions/<session_id>/restore` |
| POST | `/api/sessions/<session_id>/soft-delete` |
| GET | `/api/sessions/<session_id>/messages` |

## Workspaces and Runs

| Method | Path |
|---|---|
| GET | `/api/workspaces` |
| GET | `/api/workspaces/<ws_id>/state` |
| DELETE | `/api/workspaces/<ws_id>` |
| POST | `/api/workspaces/<ws_id>/rename` |
| GET | `/api/runs/recent` |
| GET | `/api/runs/<run_id>` |
| GET | `/api/workspaces/<ws_id>/runs` |
| GET | `/api/workspaces/<ws_id>/history` |
| GET | `/api/workspaces/<ws_id>/runs/<run_id>` |
| GET | `/api/workspaces/<ws_id>/runs/<run_id>/trace` |

`GET /api/workspaces` returns `default` first when present and includes frontend-friendly metadata:

- `workspace_id`, `name`, `created_at`, `is_default`
- compatibility counts: `runs_count`, `artifacts_count`, `memory_count`
- `stats.session_count` counts active sessions; `stats.artifact_count` and `stats.knowledge_source_count` are workspace counts.

`GET /api/runtime/summary` is read-only and does not expose tool invocation. Current fields:

- `capabilities.total`, `capabilities.enabled`, `capabilities.planned`, `capabilities.disabled`
- `tools.registered`, `tools.model_visible`, `tools.hidden_or_non_llm`

## Tools

| Method | Path |
|---|---|
| GET | `/api/tools/catalog` |
| POST | `/api/tools/invoke` |
| POST | `/api/tools/dry-run` |
| GET | `/api/tools/history` |
| GET/POST | `/api/tools/approvals` |
| PUT | `/api/tools/approvals/<approval_id>/approve` |
| PUT | `/api/tools/approvals/<approval_id>/reject` |
| GET | `/api/tools/permissions` |

## Knowledge

| Method | Path |
|---|---|
| GET | `/api/knowledge/sources` |
| POST | `/api/knowledge/sources/from-artifact` |
| POST | `/api/knowledge/sources/<source_id>/reindex` |
| GET | `/api/knowledge/search` |
| GET | `/api/knowledge/chunks/<chunk_id>` |

## Artifacts and Reviews

| Method | Path |
|---|---|
| GET/POST | `/api/workspaces/<ws_id>/artifacts` |
| POST | `/api/workspaces/<ws_id>/artifacts/upload` |
| GET/DELETE | `/api/workspaces/<ws_id>/artifacts/<artifact_id>` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/content` |
| POST | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/promote` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/summarize` |
| GET | `/api/workspaces/<ws_id>/review-items` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/review-items` |
| PUT | `/api/review-items/<item_id>` |

## LLM Settings

| Method | Path |
|---|---|
| GET | `/api/agent/llm/status` |
| POST | `/api/agent/llm/test` |
| GET/POST/DELETE | `/api/agent/llm/config` |
