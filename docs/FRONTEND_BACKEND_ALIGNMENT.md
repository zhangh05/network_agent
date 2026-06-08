# Frontend / Backend API Alignment v0.8

> **Baseline**: Tool Runtime Interactive UI v0.3 — 211 tests, 0 skipped
> **Commit**: 36d251d (2026-06-08)
> **Tools**: 55 total (7 v0.1 + 48 v0.2)

## New API Endpoints (v0.3)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tools/catalog` | GET | Read-only tool catalog (55 tools) |
| `/api/tools/invoke` | POST | Execute tool through full safety pipeline |
| `/api/tools/dry-run` | POST | Preview invocation without execution |
| `/api/tools/history` | GET | Execution history (per workspace, optional status filter) |
| `/api/tools/approvals` | GET | List pending approval requests |
| `/api/tools/approvals` | POST | Submit high-risk tool approval request |
| `/api/tools/approvals/<id>/approve` | PUT | Approve a pending request |
| `/api/tools/approvals/<id>/reject` | PUT | Reject a pending request |
| `/api/tools/permissions` | GET | Workspace-level permission summary |
| `/api/runtime/health?workspace_id=` | GET | Per-workspace runtime health |
| `/api/runs/recent?workspace_id=` | GET | Per-workspace recent runs |
| `/api/jobs?workspace_id=` | GET | Per-workspace jobs list |

## Frontend Features Added (v0.3)

- **Interactive Tool Catalog** — 3-tab layout: Catalog | Exec History | Approvals
- **Tool Search & Filter** — search by name/description, filter by risk level + category
- **Invoke Modal** — auto-generated parameter forms from ToolSpec input_schema
- **Risk Routing** — low→Execute, medium→Dry Run+Execute, high→Request Approval
- **Execution History** — status filter (success/failed/blocked/dry_run), Replay button
- **Approval Queue** — pending requests with Approve/Reject controls (with confirm dialog)
- **ESC Key** — closes invoke modal
- **Permissions Button** — shows workspace-level tool permission summary
- Refresh button (top bar) — reloads all dashboard data
- Workspace-scoped system status

## Frontend API Usage

| Page Area | API Called | Backend Route | Status |
|-----------|-----------|---------------|--------|
| System Status | `/api/runtime/health` | `@app.route("/api/runtime/health")` | ✅ |
| System Status | `/api/health` | `@app.route("/api/health")` | ✅ |
| System Status | `/api/version` | `@app.route("/api/version")` | ✅ |
| Dashboard Stats | `/api/modules` | `@app.route("/api/modules")` | ✅ |
| Dashboard Stats | `/api/skills` | `@app.route("/api/skills")` | ✅ |
| Dashboard Stats | `/api/jobs` | `@app.route("/api/jobs")` | ✅ |
| Dashboard Stats | `/api/memory/status` | `@app.route("/api/memory/status")` | ✅ |
| Dashboard Stats | `/api/memory/list?limit=100` | `@app.route("/api/memory/list")` | ✅ |
| Dashboard Stats | `/api/runs/recent?limit=5` | `@app.route("/api/runs/recent")` | ✅ |
| Dashboard Stats | `/api/workspaces` | `@app.route("/api/workspaces")` | ✅ |
| Dashboard Stats | `/api/workspaces/default/archive/preview` | `@app.route("/api/workspaces/<ws_id>/archive/preview")` | ✅ |
| Settings | `/api/agent/llm/config` (GET + POST) | `@app.route("/api/agent/llm/config")` | ✅ |
| Agent Chat | `POST /api/agent/run` | `@app.route("/api/agent/run")` | ✅ |
| Config Translate | `POST /api/modules/config-translation/translate` | `@app.route("/api/modules/config-translation/translate")` | ✅ |
| **Session List** | `GET /api/sessions?status=active` | `@app.route("/api/sessions")` | ✅ v3.1 |
| **Session Default** | `GET /api/sessions/default` | `@app.route("/api/sessions/default")` | ✅ v3.1 |
| **Session Detail** | `GET /api/sessions/<id>?include_messages=1` | `@app.route("/api/sessions/<session_id>")` | ✅ v3.1 |
| **Session Create** | `POST /api/sessions` | `@app.route("/api/sessions", methods=["POST"])` | ✅ v3.1 |
| **Session Archive** | `POST /api/sessions/<id>/archive` | `@app.route("/api/sessions/<id>/archive")` | ✅ v3.1 |
| **Session Restore** | `POST /api/sessions/<id>/restore` | `@app.route("/api/sessions/<id>/restore")` | ✅ v3.1 |
| **Session Soft Delete** | `POST /api/sessions/<id>/soft-delete` | `@app.route("/api/sessions/<id>/soft-delete")` | ✅ v3.1 |
| **Knowledge Sources** | `GET /api/knowledge/sources` | `@app.route("/api/knowledge/sources")` | ✅ v0.1 |
| **Session Rename** | `PUT /api/sessions/<id>` | `@app.route("/api/sessions/<session_id>", methods=["PUT"])` | ✅ v0.6 |
| **Workspace Delete** | `DELETE /api/workspaces/<id>` | `@app.route("/api/workspaces/<ws_id>", methods=["DELETE"])` | ✅ v0.6 |
| **Workspace Rename** | `POST /api/workspaces/<id>/rename` | `@app.route("/api/workspaces/<ws_id>/rename")` | ✅ v0.6 |
| **Knowledge Reindex** | `POST /api/knowledge/sources/<id>/reindex` | `@app.route("/api/knowledge/sources/<id>/reindex")` | ✅ v0.1 |
| **Knowledge Search** | `GET /api/knowledge/search?q=...` | `@app.route("/api/knowledge/search")` | ✅ v0.1 |
| **Knowledge Chunk** | `GET /api/knowledge/chunks/<id>` | `@app.route("/api/knowledge/chunks/<id>")` | ✅ v0.1 |
| **Tool Catalog** | `GET /api/tools/catalog` | `@app.route("/api/tools/catalog")` | ✅ v0.3 |
| **Tool Invoke** | `POST /api/tools/invoke` | `@app.route("/api/tools/invoke")` | ✅ v0.3 |
| **Tool Dry Run** | `POST /api/tools/dry-run` | `@app.route("/api/tools/dry-run")` | ✅ v0.3 |
| **Tool History** | `GET /api/tools/history` | `@app.route("/api/tools/history")` | ✅ v0.3 |
| **Tool Approvals** | `GET /api/tools/approvals` | `@app.route("/api/tools/approvals")` | ✅ v0.3 |
| **Tool Approvals** | `POST /api/tools/approvals` | `@app.route("/api/tools/approvals")` | ✅ v0.3 |
| **Tool Approve** | `PUT /api/tools/approvals/<id>/approve` | `@app.route("/api/tools/approvals/<id>/approve")` | ✅ v0.3 |
| **Tool Reject** | `PUT /api/tools/approvals/<id>/reject` | `@app.route("/api/tools/approvals/<id>/reject")` | ✅ v0.3 |
| **Tool Permissions** | `GET /api/tools/permissions` | `@app.route("/api/tools/permissions")` | ✅ v0.3 |

## Frontend UI Features (v0.3)

| Feature | Description |
|---------|-------------|
| System Status Panel | Dynamic grid from `/api/runtime/health` — 10 components with color-coded status dots (ok/warning/error) + summary counts |
| **Session Bar** | Session title (click to toggle list) + "+" (new session) + "☰" (list toggle). Auto-title from first message |
| **Session List** | Dropdown list of active sessions with last-update time. ⋮ menu per session: archive / soft-delete |
| **Chat Auto-Restore** | Page load reads `na_current_session_id` from localStorage, fetches messages from `/api/sessions/<id>?include_messages=1`, renders full chat history |
| Agent Chat | Collapsible metadata (▶ 详情 toggle), spinner animation, XSS-safe `esc()` on all user-facing text, 8s timeout via `AbortController` |
| Translate Audit Tab | Rich quality_summary dashboard: grid counters, source residue items, silent drop items, warnings |
| Recent Runs | Status badges: green=ok, red=error, yellow=planned. Quality badges for residue/drop/review |
| Agent Chat Reply | `translate_config` result auto-syncs to translate page (`lastTranslate = d.result`) |
| Localization | All error/fallback text in Chinese (不可用, 后端 JSONL 存储, 查询完成) |

## Fallback Behavior

All API calls use `apiFetch()` with 8s timeout and `.catch()` handlers. On failure:
- Dashboard stats show "—" or "不可用"
- System status shows "后端不可用" or "诊断不可用"
- Recent runs shows "历史加载失败"
- No fake/placeholder data is shown

## localStorage Policy

| Key | Purpose | Type |
|-----|---------|------|
| `na_workspace_id` | Current workspace ID | string |
| `na_current_session_id` | Current session ID pointer | string |
| `na_settings` | UI preferences (lang, theme, font size, autosave) | object |
| `tool_approval_<tool_id>` | Cached approval_id for high-risk tools | string |

- **Conversation history is NOT stored in localStorage** — loaded from `/api/sessions/<id>?include_messages=1`
- **Legacy keys auto-cleaned** — any `na_chat_*` or `na_history_*` keys are removed on init
- **Workspace switch clears session** — changing workspace resets `na_current_session_id` so the new workspace's default session is loaded
- Run history is server-authoritative (workspace/run_store)

## Redaction / Safety

- Backend removes full source_config, deployable_config, prompt, safe_context from API responses
- `user_input_summary` truncated to 120 chars in run records
- quality_summary carries counts only (no full config)
- Frontend uses `esc()` for HTML-safe display
