# Frontend v1.0 — Capability-driven Agent Workbench

> **Frontend v1.0**（前一基线）：废弃旧单文件前端 `frontend/index.html`，重写为 **Capability-driven Agent Workbench**。
> **Frontend v1.0.1**（当前基线）：将 v1.0 接入**真实后端** + 10 个 Playwright E2E。详见 [FRONTEND_API_E2E_V101.md](FRONTEND_API_E2E_V101.md)。
> 旧前端保留为 `frontend/legacy/index.html.legacy`（legacy 备份，不继续扩展）。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| 废弃单文件 legacy | 新 `frontend/index.html` 仅含 Vite root + `<script type="module" src="/src/main.tsx">`；legacy 移到 `legacy/` 子目录 |
| Capability-driven | 页面**不**硬编码 Tool count / capability 状态；从 `/api/capabilities` 动态读取 |
| 三栏工作台 | 左 Workspace/Sessions/Runs · 中 Agent 对话与结果 · 右 Turn Inspector |
| 类型严格 | 9 个 TypeScript 类型严格映射后端 dataclass `as_dict()`，**不**在组件中猜字段 |
| API 收敛 | 10 个 axios 模块（agent/sessions/workspaces/capabilities/tools/knowledge/artifacts/reviews/runtime_audit/settings）；错误统一转 `ApiError` |
| 业务规则不下放到前端 | 章节、分数、命中、扩展词、capability 状态全部来自后端；前端只**展示** |
| planned 不可调用 | Capability Center 对 `status=planned` 的 capability 只渲染状态徽标 + "(not callable)" 标签，**不**渲染调用按钮 |
| 可复现测试 | 10 个 Vitest 测试文件覆盖 10 类断言（AgentResult 渲染、tool_calls 卡片、artifact 卡片、source_summary、review 状态、planned 无按钮、API error、empty state、session 切换、inspector 展开/收起） |

## 2. 不变量（强约束）

| 约束 | 说明 |
|---|---|
| **不**改后端 Runtime 主链 | 0 改动 `agent/runtime/loop.py` 等核心文件 |
| **不**新增后端 Tool | Tool count = 73（基线） |
| **不**启用 planned | topology / inspection / cmdb 仍 0 启用 |
| **不**接真实设备 | 0 启用 |
| **不**开 SSH / Telnet / SNMP / nmap | 0 启用 |
| **`config.push` 永久禁止** | 0 触碰 |
| **不**在前端复制业务规则 | diff / scoring / extraction 都在后端 |
| **不**继续堆叠旧单文件页面 | legacy 只读 |
| **不**硬编码 Tool count = 73 / capability 状态 | 全部从 `/api/capabilities` 读取 |

## 3. 技术栈

- **React 18** + **TypeScript 5** (strict) + **Vite 5**
- **React Router 6**（`BrowserRouter` + `Routes`）
- **Zustand 4**（persisted middleware）· 轻量状态管理
- **Axios** · 错误统一转 `ApiError`
- **Vitest 2** + **@testing-library/react 16** + **happy-dom 15** · 单测
- **不**引入 Material-UI / Ant Design / Chakra 等大型 UI 框架

## 4. 目录结构

```
frontend/
├── index.html                       # Vite root（仅 <div id="root"> + /src/main.tsx）
├── package.json                     # React 18 / Vite 5 / TS 5 / Zustand 4
├── tsconfig.json / tsconfig.app.json / tsconfig.node.json
├── vite.config.ts                   # 含 /api proxy → 127.0.0.1:8010
├── .gitignore
├── README.md
├── src/
│   ├── main.tsx                     # ReactDOM.createRoot + App
│   ├── app/App.tsx                  # 顶层路由 + 顶栏 + AppLayout × 7 route
│   ├── api/
│   │   ├── client.ts                # Axios 封装 + 错误转 ApiError
│   │   └── index.ts                 # 10 个 API 模块
│   ├── types/index.ts               # 9 个 TS 类型（strict 1:1 映射）
│   ├── stores/
│   │   ├── session.ts               # workspace/session/UI state (persisted)
│   │   ├── workbench.ts             # chat history + latest AgentResult
│   │   └── toast.ts                 # 全局 toast
│   ├── layouts/
│   │   ├── AppLayout.tsx            # 三栏 grid（cols 1/2/3）
│   │   ├── Sidebar.tsx              # 左
│   │   └── Inspector.tsx            # 右（Turn Inspector）
│   ├── components/
│   │   ├── common.tsx               # AsyncView / Empty / Error / Loading / Badge / StatusDot / Code / Collapsible / useAsync
│   │   └── ToastHost.tsx
│   ├── pages/
│   │   ├── AgentWorkbench/AgentWorkbench.tsx
│   │   ├── KnowledgeLibrary/KnowledgeLibrary.tsx
│   │   ├── ArtifactCenter/ArtifactCenter.tsx
│   │   ├── ReviewCenter/ReviewCenter.tsx
│   │   ├── CapabilityCenter/CapabilityCenter.tsx
│   │   ├── RuntimeAudit/RuntimeAudit.tsx
│   │   └── Settings/Settings.tsx
│   ├── styles/global.css            # CSS variables（light/dark）+ 三栏 grid + 卡片
│   └── test/                        # 10 个 Vitest 测试 + mockServer.ts + setup.ts
└── legacy/
    └── index.html.legacy            # 旧单文件前端（保留，not served by Vite）
```

## 5. 三栏布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  Brand · Version  │  NavLinks (Agent/Knowledge/...)  │  Actions  │ ← 48px topbar
├──────────┬─────────────────────────────────────────┬───────────────┤
│          │                                         │               │
│  LEFT    │              CENTER                     │    RIGHT      │
│          │                                         │               │
│ Workspa. │  Page (AgentWorkbench / Knowledge /     │  Turn         │
│ Sessions │   Artifacts / Reviews / Capabilities /  │  Inspector    │
│ Recent   │   Runtime Audit / Settings)             │  (collapsible │
│ Runs     │                                         │   sections)   │
│          │                                         │               │
└──────────┴─────────────────────────────────────────┴───────────────┘
```

- `AppLayout cols={1|2|3}`：cols=3 时启用 Inspector；cols=2 时只显示左/中；cols=1 时只显示中
- 1280px+ 桌面布局；`≥480px` 时三栏可折叠
- 浅色/深色主题：CSS variable + `data-theme="dark"`

## 6. 页面

| 路由 | 页面 | 三栏 | 主要交互 |
|---|---|---|---|
| `/workbench` | AgentWorkbench | 3 | chat / tool call 卡片 / source summary / errors |
| `/knowledge` | KnowledgeLibrary | 2 | source list / search / reindex / scope 切换 |
| `/artifacts` | ArtifactCenter | 2 | list / detail / preview-diff-metadata tabs / sensitivity / authoritative / deployable |
| `/reviews` | ReviewCenter | 1 | pending/accepted/ignored/modified 过滤 / 编辑 user_note + status / **不**改 artifact |
| `/capabilities` | CapabilityCenter | 1 | 从 `/api/capabilities` 动态读；planned 仅展示状态 + "(not callable)" |
| `/audit` | RuntimeAudit | 2 | turn timeline / 选中后看 events / model I/O / tool calls |
| `/settings` | Settings | 1 | LLM provider / model / base_url（read + write） |

## 7. 类型（9 个核心类型）

`src/types/index.ts` — 与后端 `as_dict()` 字段 1:1 映射：

```ts
AgentResult     // ok/final_response/events/trace_id/session_id/turn_id/tool_calls/warnings/errors/metadata
ToolCallResult  // call_id/tool_id/ok/result/error/duration_ms
RuntimeEvent    // event_id/event_type/occurred_at/payload
Artifact        // artifact_id/authoritative/deployable_config/sensitivity/metadata
ReviewItem      // item_id/artifact_id/severity/category/status/user_note
KnowledgeSource // source_id/title/source_type/scope/tags/enabled/chunk_count
KnowledgeChunk  // chunk_id/source_id/chapter/section/subsection/content
CapabilityManifest
  ├── module   // CapabilityModuleSpec
  ├── skills   // CapabilitySkillSpec[]
  ├── tools    // CapabilityToolRef[] (callable_by_llm, risk_level, forbidden, ...)
  ├── outputs  // CapabilityOutputSpec[]
  └── safety   // CapabilitySafetySpec (real_device_access, allows_config_push, ...)
ApiError        // ok:false, code, status, message, request_id
```

**不**在组件中猜字段。**不**在 `if (cap.foo === undefined)` 之外加默认值——直接 `?.`。

## 8. API 层（10 个模块）

`src/api/index.ts`：

| 模块 | 主要端点 |
|---|---|
| `agentApi` | `POST /agent/message` |
| `sessionsApi` | `GET/POST /sessions`, `POST /sessions/{id}/archive` |
| `workspacesApi` | `GET/POST /workspaces`, `GET /workspaces/{id}/state`, `GET /runs/recent` |
| `capabilitiesApi` | `GET /capabilities` |
| `toolsApi` | `GET /tools/catalog` |
| `knowledgeApi` | `GET /knowledge/sources`, `POST /knowledge/sources/from-artifact`, `POST /knowledge/sources/{id}/reindex`, `GET /knowledge/search`, `GET /knowledge/chunks/{id}` |
| `artifactsApi` | `GET /workspaces/{id}/artifacts`, `GET /workspaces/{id}/artifacts/{art}`, `GET /workspaces/{id}/artifacts/{art}/content` |
| `reviewsApi` | `GET /workspaces/{id}/review-items`, `PUT /review-items/{id}` |
| `runtimeAuditApi` | `GET /runs/recent`, `GET /workspaces/{id}/turns/{id}`, `GET /workspaces/{id}/runs/{id}/trace` |
| `settingsApi` | `GET/POST /agent/llm/config` |

**规则**：
- 错误统一转 `ApiError`（`apiRequest` 在 `client.ts`）
- 5 种 state：`idle | loading | success | empty | error`（`AsyncState<T>`）
- 组件**不**直接调 axios；只调 `xxxApi.method(...)` 并把结果传入 `useAsync`

## 9. 状态管理

`src/stores/`（Zustand 4 + persist middleware）：

| Store | 字段 | persist? |
|---|---|---|
| `useSessionStore` | currentWorkspaceId, currentSessionId, workspaces, sessions | 部分（id only） |
| `useUIStore` | inspectorOpen, sidebarOpen, theme | 是 |
| `useWorkbenchStore` | history[], latestResult, sending | 否（in-memory） |
| `useToastStore` | messages[] | 否（in-memory） |

## 10. 样式

`src/styles/global.css` — Vanilla CSS，无大型框架：

- CSS variables：`--bg`, `--text`, `--pri`, `--success`, `--warning`, `--danger`, `--muted`, `--code-bg`, `--shadow-sm/md`, `--radius`, `--mono`, `--sans`
- 浅色 / 深色通过 `[data-theme="dark"]` 切换
- 等宽字体用于 code / pre / config / diff
- 状态色：warning / error / review 统一调色板
- 三栏可折叠：左 `«` / 右 `»` 按钮

## 11. 测试（10 个 Vitest 文件）

`src/test/` 目录 10 个测试 + 1 个 mock helper：

| # | 文件 | 覆盖 spec 八点 |
|---|---|---|
| 1 | `agentResult.test.tsx` | AgentResult 正常渲染（turn_id, trace_id, ok badge）|
| 2 | `toolCalls.test.tsx` | tool_calls 卡片（多 call + ok/failed + duration）|
| 3 | `artifactCard.test.tsx` | artifact 卡片（authoritative / sensitive）|
| 4 | `sourceSummary.test.tsx` | knowledge source_summary inline |
| 5 | `reviewItem.test.tsx` | review item status (pending / accepted)|
| 6 | `plannedCapability.test.tsx` | planned capability **不**显示调用按钮 |
| 7 | `apiError.test.tsx` | API error 状态（5xx + retry）|
| 8 | `emptyState.test.tsx` | empty state（`{items: []}` → empty）|
| 9 | `sessionSwitch.test.tsx` | session 切换写入 store |
| 10 | `inspectorToggle.test.tsx` | inspector 展开/收起 |

`mockServer.ts` 通过 `vi.spyOn(clientModule, "apiRequest")` mock 全部 HTTP；测试只关注渲染行为。

## 12. 强制不变量再确认

| 约束 | 验证手段 |
|---|---|
| Runtime 主链 0 改动 | backend tests 全过；alignment 37/37 |
| 后端 Tool count = 73 | `TestNoRegression::test_only_config_translation_enabled` 等 |
| planned 仍 0 可见 | `CapabilityCenter` 数据全从 `/api/capabilities`；前端**不**渲染 invoke 按钮（`TestPlannedCapability` 断言）|
| 不接真实设备 | 5 capability safety 字段全来自后端；前端不另写 device 接口 |
| 不开 SSH/Telnet/SNMP/nmap | backend 0 启用（capability 0 调用）|
| `config.push` 永久禁止 | capability.safety.allows_config_push 直接显示，不暴露任何写接口 |
| 不复制业务规则 | 组件不计算 diff / 不算 score / 不重写 hit；只显示 |
| 不硬编码 73 | `toolsApi.catalog` 从 `/api/tools/catalog` 读，**不**写死 73 |
| 不硬编码 capability 状态 | `CapabilityCenter` 用 `cap.status` 显示徽标；**不**写"planned 不显示"等逻辑 |
| 旧单文件不再扩展 | `frontend/legacy/index.html.legacy` 只读 |

## 13. 后续 (v1.x / v2)

| 版本 | 主题 |
|---|---|
| v1.0.x | API streaming（SSE / NDJSON）；session 切换不丢 history |
| v1.0.x | Capability Center: Skill 详情抽屉（input_schema 可视化）|
| v1.0.x | Knowledge 检索：把 `metadata.query_expansions` 展开成可视化标签 |
| v1.1 | 多 workspace 并排（split view）|
| v1.1 | i18n（zh-CN / en-US）|
| v2 | 与 FastAPI backend SSE 集成；tool call 流式输出 |
