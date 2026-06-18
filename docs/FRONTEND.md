# 前端架构

## 技术栈

- React 18 + TypeScript
- Vite 5 (dev server + build)
- Zustand (状态管理)
- React Router (路由)

## 页面结构

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | AgentWorkbench | 主聊天界面 |
| `/knowledge` | KnowledgeLibrary | 知识库管理 |
| `/memory` | MemoryPage | 记忆管理 |
| `/files` | FileManager | 统一文件管理 |
| `/artifacts` | ArtifactCenter | 制品中心 |
| `/settings` | Settings | LLM/系统设置 |
| `/runs` | RunsPage | 运行记录 |
| `/audit` | RuntimeAudit | 审计日志 |
| `/diagnostics` | Diagnostics | 系统诊断 |

## 状态管理 (Zustand)

| Store | 文件 | 职责 |
|-------|------|------|
| `workbench` | `stores/workbench.ts` | 聊天历史、发送状态、latestResult |
| `session` | `stores/session.ts` | 当前 session/workspace |
| `ui` | `stores/ui.ts` | UI 状态（侧栏、主题） |

persist middleware 持久化到 localStorage。

## 通信模式

### WebSocket 流式

```typescript
ws = new WebSocket("/ws/agent")
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  if (data.type === "token") appendToken(data.content)
  if (data.type === "event") handleEvent(data)
  if (data.type === "done") setLatestResult(data)
}
```

### HTTP Fallback

```typescript
const res = await apiRequest("/api/agent/message", { method: "POST", body: { message, workspace_id } })
appendAssistant(res.final_response, res)
setLatestResult(res)
```

## 文件管理

`/api/files` 返回三种来源的数据：

1. **文件系统** — `files/upload/` 和 `files/agent/` 的 record.json
2. **知识源** — ContextStore `knowledge_source` 项
3. **记忆** — ContextStore `memory_hit` 项

前端通过 `type` 字段过滤标签：all/pcap/knowledge/memory/artifact/general。
删除操作自动判断来源（文件系统 or ContextStore），真实删除。
