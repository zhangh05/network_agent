# Frontend / Backend API Alignment v0.2

> **Baseline**: `7eb0e61` — 18 API integration tests passed, 0 failed

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

## Frontend UI Features (v0.2)

| Feature | Description |
|---------|-------------|
| System Status Panel | Dynamic grid from `/api/runtime/health` — 10 components with color-coded status dots (ok/warning/error) + summary counts |
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
| `na_settings` | UI preferences | object |

- Conversation history is NOT stored in localStorage
- Run history is server-authoritative (workspace/run_store)

## Redaction / Safety

- Backend removes full source_config, deployable_config, prompt, safe_context from API responses
- `user_input_summary` truncated to 120 chars in run records
- quality_summary carries counts only (no full config)
- Frontend uses `esc()` for HTML-safe display
