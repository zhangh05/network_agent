# API

Current API routes are Flask routes registered by `backend/main.py` and `backend/api/*_routes.py`.

## Core

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Process health and loaded skill count |
| GET | `/api/version` | Version metadata |
| GET | `/api/runtime/summary` | Capability and tool counts for UI status |
| GET | `/api/agent/status` | Agent status |
| POST | `/api/agent/message` | Main Codex-style runtime turn |
| POST | `/api/agent/run` | Legacy-compatible agent run; supports `stream=true` |

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

## Workspaces, Runs, Traces, Reports

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
| GET | `/api/workspaces/<ws_id>/traces` |
| GET | `/api/agent/runs/<run_id>/trace` |
| POST | `/api/reports/create` |
| POST | `/api/workspaces/<ws_id>/runs/<run_id>/report` |
| GET | `/api/workspaces/<ws_id>/reports` |
| GET | `/api/workspaces/<ws_id>/reports/<artifact_id>/content` |

`GET /api/workspaces` ensures `default` exists, returns it first when present, and includes frontend-friendly `name`, `created_at`, `is_default`, compatibility counts, and `stats`.

`GET /api/runs/recent` returns up to `limit` (default 10, max 100) recent agent runs for `?workspace_id=`. Only runs from **active** sessions are included—archived and deleted sessions are excluded—so the sidebar's session list and recent runs stay in sync. Each run carries a `session_title` field for frontend association display.

## Tools And Runtime Maintenance

| Method | Path |
|---|---|
| GET | `/api/runtime/health` |
| GET | `/api/runtime/selfcheck` |
| GET | `/api/tools/catalog` |
| POST | `/api/tools/invoke` |
| POST | `/api/tools/dry-run` |
| GET | `/api/tools/history` |
| GET/POST | `/api/tools/approvals` |
| PUT | `/api/tools/approvals/<approval_id>/approve` |
| PUT | `/api/tools/approvals/<approval_id>/reject` |
| GET | `/api/tools/permissions` |
| GET | `/api/workspaces/<ws_id>/selfcheck` |
| GET | `/api/workspaces/<ws_id>/retention/preview` |
| POST | `/api/workspaces/<ws_id>/retention/apply` |
| GET | `/api/workspaces/<ws_id>/retention/audits` |
| GET | `/api/workspaces/<ws_id>/retention/audits/<audit_id>` |
| GET | `/api/workspaces/<ws_id>/archive/preview` |
| POST | `/api/workspaces/<ws_id>/archive/apply` |
| GET | `/api/workspaces/<ws_id>/archive/audits` |
| GET | `/api/workspaces/<ws_id>/archive/audits/<audit_id>` |

`/api/tools/invoke` is policy and approval gated. `/api/tools/dry-run` is the safe planning/check path.
High-risk tools use `approval_id` as a top-level invoke field after `/api/tools/approvals/<approval_id>/approve`; the approval must match tool and workspace. `approval_id` inside ordinary tool arguments is not trusted by the Agent/LLM path.

## Knowledge

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload local Markdown/text/HTML/DOCX/PDF and index it |
| GET | `/api/knowledge/sources` | List workspace knowledge sources |
| POST | `/api/knowledge/sources/from-artifact` | Create a knowledge source from a safe artifact excerpt |
| POST | `/api/knowledge/sources/<source_id>/reindex` | Rebuild a source index |
| GET | `/api/knowledge/search` | Search safe excerpts |
| GET | `/api/knowledge/chunks/<chunk_id>` | Read a safe chunk view |

## Memory

| Method | Path |
|---|---|
| GET | `/api/memory/status` |
| POST | `/api/memory/write` |
| POST | `/api/memory/search` |
| GET | `/api/memory/list` |
| POST | `/api/memory/confirm` |
| DELETE | `/api/memory/<memory_id>` |

Memory writes are redacted and policy checked. Confirmed writes are projected into RAG knowledge best-effort and may report conflict metadata.

## Artifacts And Reviews

| Method | Path |
|---|---|
| GET/POST | `/api/workspaces/<ws_id>/artifacts` |
| POST | `/api/workspaces/<ws_id>/artifacts/upload` |
| GET/DELETE | `/api/workspaces/<ws_id>/artifacts/<artifact_id>` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/content` |
| POST | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/promote` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/summarize` |
| GET | `/api/workspaces/<ws_id>/runs/<run_id>/artifacts` |
| GET | `/api/workspaces/<ws_id>/review-items` |
| GET | `/api/workspaces/<ws_id>/artifacts/<artifact_id>/review-items` |
| PUT | `/api/review-items/<item_id>` |

## Jobs

| Method | Path |
|---|---|
| GET/POST | `/api/jobs` |
| GET | `/api/jobs/<job_id>` |
| GET | `/api/workspaces/<ws_id>/jobs` |
| GET | `/api/workspaces/<ws_id>/jobs/<job_id>` |
| POST | `/api/jobs/<job_id>/cancel` |
| POST | `/api/jobs/<job_id>/retry` |
| GET | `/api/jobs/<job_id>/events` |
| GET | `/api/jobs/<job_id>/logs` |
| GET | `/api/jobs/<job_id>/artifacts` |
| POST | `/api/jobs/worker/run-once` |
| GET | `/api/jobs/worker/status` |

## Context And Prompts

| Method | Path |
|---|---|
| GET | `/api/context/status` |
| POST | `/api/context/resolve` |
| POST | `/api/context/build` |
| GET | `/api/prompts` |
| GET | `/api/prompts/<prompt_id>` |
| POST | `/api/prompts/render` |
| GET | `/api/harness/status` |

## LLM Settings

| Method | Path |
|---|---|
| GET | `/api/agent/llm/status` |
| POST | `/api/agent/llm/test` |
| GET/POST/DELETE | `/api/agent/llm/config` |

## Modules And Registries

| Method | Path |
|---|---|
| GET | `/api/skills` |
| GET | `/api/modules` |
| GET | `/api/modules/<module_name>/status` |
| GET | `/api/capabilities` |
| GET | `/api/registry/status` |
| POST | `/api/registry/reload` |
| POST | `/api/modules/config-translation/translate` |
