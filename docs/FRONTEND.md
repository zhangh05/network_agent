# Frontend

## 技术栈

React 18、TypeScript、Vite 5、React Router、Zustand、Axios、Vitest 和 Playwright。

## 页面

| Route | Component | Purpose |
|-------|-----------|---------|
| `/workbench` | `AgentWorkbench` | 对话、工具进度和结果 |
| `/files` | `FileManager` | 统一文件管理 |
| `/packet` | `PacketAnalysis` | 报文连接与 TCP 对齐分析 |
| `/runs` | `RunsPage` | 运行记录与 trace |
| `/capabilities` | `CapabilityCenter` | 能力和工具状态 |
| `/jobs` | `JobsPage` | 作业管理 |
| `/diagnostics` | `Diagnostics` | 系统诊断 |
| `/settings` | `Settings` | LLM Provider 配置 |

## 状态

| Store | Purpose |
|-------|---------|
| `useSessionStore` | 当前工作区、会话和会话列表 |
| `useWorkbenchStore` | 按会话保存消息和发送状态 |
| `useUIStore` | 主题、侧栏和检查器状态 |
| `useToastStore` | 全局通知 |

## 文件到报文分析

1. `/api/pcap/parse` 创建统一文件记录并写入 `metadata.session_id`。
2. `FileManager` 只对带有效 session 的报文显示分析入口。
3. 点击后进入 `/packet?sid={session_id}`。
4. `PacketAnalysis` 调用 `/api/pcap/session/{session_id}` 恢复连接列表。
5. 用户选择连接后调用 `/api/pcap/filter` 和 `/api/pcap/align`。

## API

- `frontend/src/api/client.ts`：Axios 实例、错误和超时策略。
- `frontend/src/api/index.ts`：业务 API 类型与封装。
- 开发代理：`/api/*` -> `VITE_DEV_API_TARGET`，默认 `http://127.0.0.1:8010`。

## 验证

```bash
cd frontend
npm test -- --run
npm run typecheck
npm run build
```
