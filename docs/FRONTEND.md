# 前端开发指南

技术栈：React 18, TypeScript, Vite, Zustand, react-virtuoso

## 入口文件

- `src/app/App.tsx` — 路由定义
- `src/pages/AgentWorkbench/AgentWorkbench.tsx` — 主工作台页面

## 状态管理 (Zustand)

### WorkbenchStore (`src/stores/workbench.ts`)

核心消息状态：

```typescript
interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  status: "streaming" | "ready" | "error";
  created_at: string;
  result?: AgentResult;
  toolCalls?: InlineToolCall[];
  error?: string;
  trace_id?: string;
}
```

关键方法：
- `appendUser(text, session)` — 添加用户消息
- `appendAssistantStreaming(session)` — 创建流式占位消息
- `updateAssistant(msgId, patch, session)` — 更新消息（流式写入）
- `appendAssistant(text, result, session)` — 添加完整消息
- `mergeFromBackend(session, serverMsgs)` — 从后端同步
- `switchSession(sessionId)` — 切换会话

### SessionStore (`src/stores/session.ts`)

管理会话列表、当前会话、workspace 选择。

## 对话流程

### WebSocket 流式路径（主路径）

```
用户发送 → appendUser + appendAssistantStreaming → WS connect
  → token 事件 → updateAssistant(msgId, {text: cumulated})
  → tool_call → updateAssistant(msgId, {toolCalls: [...live]})
  → done → updateAssistant(msgId, {status, text, result, toolCalls})
  → finally → setSending(false)
```

### HTTP 回退路径

```
WS 不可用 → agentApi.run() → updateAssistant(msgId, {text, result, ...})
```

## 渲染架构

Virtuoso 虚拟列表 + `renderMsg` 回调：

```tsx
<Virtuoso
  data={visibleHistory}
  itemContent={(idx, m) => renderMsg(m, idx, total)}
  followOutput="auto"
/>
```

`renderMsg` 根据消息 status 渲染不同内容：
- `streaming` + 无文本 → 输入指示器（三个点）+ "思考中…"
- `streaming` + 有文本 → StreamingContent 组件
- `streaming` + toolCalls → 实时工具调用 chips
- `ready` → Markdown 渲染 + ResultInline + 工具卡片
- `error` → 错误提示 + 可重试按钮

## API 客户端 (`src/api/`)

| 文件 | 对应端点 |
|------|---------|
| `agent.ts` | `/api/agent/*` |
| `sessions.ts` | `/api/workspaces/<ws>/sessions/*` |
| `jobs.ts` | `/api/workspaces/<ws>/jobs/*` |
| `artifacts.ts` | `/api/workspaces/<ws>/artifacts/*` |
| `client.ts` | 通用 HTTP 客户端 (apiRequest) |

## CSS 约定

- 全局样式：`src/styles/global.css` (~3600 行)
- 使用 CSS 自定义属性：`--ok`, `--danger`, `--surface-2`, `--border-2`, `--brand`
- 不使用 Tailwind CSS
- 动画：`@keyframes pulse`, `soft-sweep`, `subtle-pop`, `fadeInStream`
- 间距使用 px（非 rem/em）

## 添加新页面

1. 在 `src/pages/` 创建目录和 `.tsx`
2. 在 `src/app/App.tsx` 添加路由
3. 如需新 API，在 `src/api/` 添加客户端

## 现有页面

| 路由 | 页面 |
|------|------|
| `/workbench` | AgentWorkbench |
| `/jobs` | JobsPage |
| `/runs` | RunsPage |
| `/packet` | PacketAnalysis |
| `/artifacts` | ArtifactCenter |
| `/knowledge` | KnowledgeLibrary |
| `/memory` | MemoryPage |
| `/cmdb` | CMDBPage |
| `/capabilities` | CapabilityCenter |
| `/settings` | Settings |
| `/diagnostics` | Diagnostics |
