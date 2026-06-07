# Frontend / Backend API Alignment v0.1

> **Baseline**: `cbaa60e` — 1006 passed, 7 skipped, 0 failed

## Frontend API Usage

| Page Area | API Called | Backend Route | Status |
|-----------|-----------|---------------|--------|
| System Status | `/api/health` | `@app.route("/api/health")` | ✅ |
| System Status | `/api/version` | `@app.route("/api/version")` | ✅ |
| Dashboard Stats | `/api/modules` | `@app.route("/api/modules")` | ✅ |
| Dashboard Stats | `/api/skills` | `@app.route("/api/skills")` | ✅ |
| Dashboard Stats | `/api/jobs` | `@app.route("/api/jobs")` | ✅ |
| Dashboard Stats | `/api/memory/status` | `@app.route("/api/memory/status")` | ✅ |
| Dashboard Stats | `/api/memory/list?limit=100` | `@app.route("/api/memory/list")` | ✅ |
| Dashboard Stats | `/api/runs/recent?limit=5` | `@app.route("/api/runs/recent")` | ✅ |
| Dashboard Stats | `/api/runtime/health` | `@app.route("/api/runtime/health")` | ✅ |
| Dashboard Stats | `/api/workspaces` | `@app.route("/api/workspaces")` | ✅ |
| Dashboard Stats | `/api/workspaces/default/archive/preview` | `@app.route("/api/workspaces/<ws_id>/archive/preview")` | ✅ |
| Settings | `/api/agent/llm/config` (via settings page) | `@app.route("/api/agent/llm/config")` | ✅ |

## Backend APIs Not Yet Used by Frontend

| API | Purpose | Suggested UI Use |
|-----|---------|-----------------|
| `POST /api/agent/run` | Agent execution | Agent Chat (primary entry) |
| `POST /api/modules/config-translation/translate` | Direct translation | Config Translation page |
| `GET /api/agent/status` | Agent runtime status | System Status |
| `GET /api/capabilities` | Capability listing | Agent Chat hints |
| `GET /api/registry/status` | Registry status | System Status |
| `GET /api/prompts` | Prompt templates | Settings |
| `GET /api/runtime/selfcheck` | Workspace selfcheck | System Status |
| `GET /api/workspaces/<id>/history` | Workspace history | Recent Runs table |
| `GET /api/workspaces/<id>/state` | Workspace state | Workspace settings |
| `GET /api/workspaces/<id>/retention/preview` | Retention preview | System Status |
| `GET /api/workspaces/<id>/retention/audits` | Retention audits | Admin panel |

## Fallback Behavior

All API calls use `apiFetch()` with `.catch()` handlers. On failure:
- Dashboard stats show "—" or "unavailable"
- System status shows "backend unavailable"
- Recent runs shows "历史加载失败"
- No fake/placeholder data is shown

## localStorage Policy

| Key | Purpose | Type |
|-----|---------|------|
| `na_workspace_id` | Current workspace ID | string |
| `na_settings` | UI preferences | object |

- Conversation history is NOT stored in localStorage
- Run history is server-authoritative (workspace/run_store)

## Redaction / Safety

- Backend removes full source_config, deployable_config, prompt, safe_context from API responses
- `user_input_summary` truncated to 120 chars in run records
- quality_summary carries counts only (no full config)
- Frontend uses `esc()` for HTML-safe display
