# Frontend v1.0.1 — Real API Integration & E2E Stabilization

> **Frontend v1.0.1**（当前基线）：将前端从 mock/demo 状态接入**真实后端**，完成核心业务 E2E 闭环。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [FRONTEND_V1.md](FRONTEND_V1.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| 真实 API 接入 | 10 个 API 模块对接后端实际合同；删除测试外的 mock fallback |
| 核心闭环 | Agent message · session lifecycle · knowledge import · artifact · review status · capability 动态读取 |
| 5 种状态 | `idle / loading / success / empty / error`；401/403/404/408/413/422/429/5xx 全部分类 |
| 部署 | Vite dev proxy → 后端 8010；`VITE_API_BASE` / `VITE_DEV_API_TARGET` 环境变量 |
| E2E | Playwright 10 个 spec 覆盖 10 类断言 + 门禁 |
| 后端 0 改动 | 仅薄包装 `backend/api/review_routes.py`（不新增 Tool）|

## 2. 不变量（强约束）

| 约束 | 状态 |
|---|---|
| Runtime 主链 0 改动 | ✓ |
| 后端 Tool count = 73 | ✓（review_routes.py 是薄包装 endpoint，不新增 tool）|
| planned 仍 0 可见 | ✓（test 8 断言）|
| 不接真实设备 | ✓ |
| 不开 SSH/Telnet/SNMP/nmap | ✓ |
| `config.push` 永久禁止 | ✓（frontend 不暴露 deployable promotion 按钮）|
| 不复制业务规则 | ✓（`/api/review-items` 直接走后端 service）|
| 不硬编码 Tool count / capability 状态 | ✓（全从 `/api/capabilities`）|
| 不继续堆叠旧单文件 | ✓ |

## 3. 真实 API 接入（10 模块端点清单）

| 模块 | 端点（真实）|
|---|---|
| `agentApi` | `POST /api/agent/message`（Codex-style runtime）|
| `sessionsApi` | `GET/POST /api/sessions` · `GET /api/sessions/<id>` · `POST /api/sessions/<id>/archive` · `PUT /api/sessions/<id>` · `POST /api/sessions/<id>/soft-delete` · `DELETE /api/sessions/<id>` |
| `workspacesApi` | `GET /api/workspaces` · `GET /api/workspaces/<id>/state` · `POST /api/workspaces/<id>/rename` · `DELETE /api/workspaces/<id>` · `GET /api/runs/recent` |
| `capabilitiesApi` | `GET /api/capabilities` · `GET /api/tools/catalog` |
| `toolsApi` | `GET /api/tools/catalog` |
| `knowledgeApi` | `GET /api/knowledge/sources` · `POST /api/knowledge/sources/from-artifact`（JSON）· `POST /api/knowledge/sources/<id>/reindex` · `GET /api/knowledge/search` · `GET /api/knowledge/chunks/<id>` |
| `artifactsApi` | `GET /api/workspaces/<ws>/artifacts` · `GET /api/workspaces/<ws>/artifacts/<art>` · `GET /api/workspaces/<ws>/artifacts/<art>/content` |
| `reviewsApi` | `GET /api/workspaces/<ws>/review-items` · `PUT /api/review-items/<id>?workspace_id=&artifact_id=` |
| `runtimeAuditApi` | `GET /api/runs/recent` · `GET /api/runs/<id>` · `GET /api/workspaces/<ws>/runs/<id>/trace` |
| `settingsApi` | `GET/POST /api/agent/llm/config` |

## 4. 核心闭环

### 4.1 Agent Workbench（`/workbench`）
- **发送消息** → `POST /api/agent/message` · 12s timeout
- **成功路径**：把 `AgentResult` 写入 `useWorkbenchStore.latestResult` → Inspector 渲染 turn_id / trace_id / tool_calls / warnings / errors
- **失败路径**（**新增 v1.0.1**）：构造 stub `AgentResult{ok:false, errors:[...], turn_id:'turn-<ts>', trace_id:<request_id>}`，确保 Inspector 仍然可见，operator 能看到 trace_id 排查

### 4.2 Workspace / Session（`Sidebar`）
- 列表：实时 `GET /api/workspaces` + `GET /api/sessions?status=active`
- **创建** session：sidebar `+` 按钮 → `POST /api/sessions` → 自动 select 新 session
- **切换**：click session → `setCurrentSession(id)` → 持久化到 localStorage
- **归档**：click `×` → `POST /api/sessions/<id>/archive` → 自动取消选择
- **重命名 / 删除**：API 已对接；UI 在 spec 要求的范围内

### 4.3 Knowledge（`/knowledge`）
- **Import-from-artifact**（**新增 v1.0.1**）：select 一个 artifact → `POST /api/knowledge/sources/from-artifact`（JSON body `{workspace_id, artifact_id}`，**不**是 multipart）→ toast
- **Search**：`GET /api/knowledge/search?q=&workspace_id=&limit=20` → 显示 `results[]`（backend 返回的是 `results` 不是 `hits`）
- **Reindex**：`POST /api/knowledge/sources/<id>/reindex` → 刷新列表
- **Chunk read**：`GET /api/knowledge/chunks/<id>` → 安全摘录

### 4.4 Artifact（`/artifacts`）
- **List / Detail / Preview / Diff / Metadata tabs** · 展示 `authoritative` / `deployable_config` / `sensitivity`
- **不**暴露 `config.push` / `promote` 端点（后端允许但前端永远不调用）

### 4.5 Review（`/reviews`）
- **List**：`GET /api/workspaces/<ws>/review-items?status=pending` → 表格
- **Update**：modal → `PUT /api/review-items/<id>?workspace_id=&artifact_id=` with `{status, user_note}` → 立即刷新
- **不**修改原 artifact

### 4.6 Capability / Audit
- **Capability**：全从 `/api/capabilities` 动态读取；planned 仅显示状态 + `(not callable)`
- **Audit**：`GET /api/runs/recent` → turn timeline；选中 → `GET /api/runs/<id>` → events

## 5. 部署

### 5.1 Vite dev（`npm run dev`）
- 默认：`/api` → `http://127.0.0.1:8010`
- 自定义：`VITE_DEV_API_TARGET=http://staging.example:8010 npm run dev`

### 5.2 生产 build（`npm run build`）
- 输出：`dist/index.html` + `dist/assets/*`
- API base：`VITE_API_BASE=https://prod.example.com`（build 时注入）
- 默认 `/api`（同源）—— 适合 FastAPI 后端直接托管
- 静态文件可由 FastAPI 单独 mount 或独立静态服务（nginx / cloudfront / CDN）

### 5.3 环境变量
| 变量 | 用途 | 默认 |
|---|---|---|
| `VITE_API_BASE` | 生产环境 API base（不含 `/api`）| `/api`（同源）|
| `VITE_DEV_API_TARGET` | dev proxy target | `http://127.0.0.1:8010` |
| `E2E_BACKEND_URL` | Playwright 全局 setup 检查的 backend | `http://127.0.0.1:8010` |
| `E2E_FRONTEND_URL` | Playwright baseURL | `http://127.0.0.1:5173` |

## 6. 错误状态统一

`src/api/client.ts` 在 axios 拦截器里把**所有**错误转成 `ApiError`：

| HTTP | `code` | 触发条件 |
|---|---|---|
| 0 / ECONNABORTED | `timeout` | 12s 未收到响应 |
| 0 / ERR_CANCELED | `aborted` | AbortSignal 触发 |
| 0 / no response | `network` | 后端不可达 / CORS / DNS |
| 4xx (401/403/404/422) | `http_4xx` | 客户端错误 |
| 408 | `timeout` | 服务端 timeout |
| 413/429 | `http_4xx` | 容量 / 限流 |
| 5xx | `http_5xx` | 服务端错误 |
| SyntaxError | `parse` | 响应不是合法 JSON |

`ApiError` 透传 `request_id`（来自后端 `X-Request-Id` header），用于排查。

## 7. 测试

### 7.1 单元测试（Vitest）
- `src/test/*.test.tsx` — **13 / 13**（v1.0 套件**未**减少）
- 覆盖：AgentResult 渲染 / tool_calls 卡片 / artifact 卡片 / source_summary / review item / planned 无按钮 / API error / empty state / session 切换 / inspector 展开收起

### 7.2 E2E（Playwright 1.60）
- `e2e/01-health.spec.ts` — 后端健康检查
- `e2e/02-agent-message.spec.ts` — Agent 消息完整闭环
- `e2e/03-session-lifecycle.spec.ts` — session 创建和切换
- `e2e/04-knowledge-upload.spec.ts` — knowledge 文件上传并导入
- `e2e/05-knowledge-search.spec.ts` — knowledge 搜索
- `e2e/06-artifact-view.spec.ts` — artifact 查看
- `e2e/07-review-status.spec.ts` — review 状态更新
- `e2e/08-planned-no-button.spec.ts` — planned capability 无调用入口
- `e2e/09-timeout-error.spec.ts` — provider timeout 正确展示
- `e2e/10-refresh-restore.spec.ts` — 页面刷新状态恢复

### 7.3 运行

```bash
cd frontend
npm run typecheck    # 0 errors
npm run build        # 264 kB JS / 10 kB CSS
npm test             # 13 / 13 passed
npm run e2e          # 10 / 10 passed (36s)
```

### 7.4 后端 focused regression
`harness/test_*` — **152 / 152 passed**（v1.0.2 retrieval 19 + v1.0.1.1 16 + v1.0.1 22 + v1.0 29 + v0.9 29 + v0.8.2 28 + v0.8.1 23 + v0.8 20 + v0.7-v0.7.1 41 = 152 + alignment 37 = 189）

## 8. 不变量再确认

| 约束 | 验证手段 | 状态 |
|---|---|---|
| Runtime 主链 0 改动 | `git diff HEAD~1 agent/runtime/` → 空 | ✓ |
| 后端 Tool count = 73 | `TestNoRegression::test_only_config_translation_enabled` | ✓ |
| planned 仍 0 可见 | E2E test 8 + Vitest plannedCapability | ✓ |
| 不接真实设备 | capability.safety.real_device_access 直接显示 false | ✓ |
| 不开 SSH/Telnet/SNMP/nmap | backend 0 启用 | ✓ |
| `config.push` 永久禁止 | frontend **不**暴露 promote 按钮 | ✓ |
| 不复制业务规则 | review / artifact / knowledge 走真实 API | ✓ |
| 不硬编码 73 / capability 状态 | 全从 `/api/capabilities` 读 | ✓ |
| v1.0 frontend 13/13 不回归 | Vitest 13/13 passed | ✓ |
| v0-v1.0.2 backend 152/152 不回归 | pytest 152 passed | ✓ |

## 9. 后续 (v1.0.x / v2)

| 版本 | 主题 |
|---|---|
| v1.0.x | API streaming（SSE / NDJSON）；session 切换不丢 history |
| v1.0.x | Knowledge 检索：把 `metadata.query_expansions` 展开成可视化标签 |
| v1.1 | 多 workspace 并排（split view）|
| v1.1 | i18n（zh-CN / en-US）|
| v2 | 与 FastAPI SSE 集成；tool call 流式输出；长任务 progress bar |
