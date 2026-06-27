# API 参考

Base URL: `http://localhost:8010`

## 核心端点

### Agent 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent/message` | 发送消息（HTTP 回退） |
| WS | `/ws/agent` | WebSocket 流式对话 |

请求体 (`POST /api/agent/message`):
```json
{
  "message": "...",
  "workspace_id": "default",
  "session_id": null
}
```

WebSocket 消息格式:
```json
{ "type": "token", "content": "..." }
{ "type": "event", "name": "tool_call", "data": {...} }
{ "type": "done", "session_id": "...", "turn_id": "...", "final_response": "..." }
{ "type": "error", "message": "..." }
```

### Session

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workspaces/<ws>/sessions` | 列出 |
| POST | `/api/workspaces/<ws>/sessions` | 创建 |
| GET | `/api/workspaces/<ws>/sessions/<id>` | 详情 |
| PUT | `/api/workspaces/<ws>/sessions/<id>` | 更新 |
| DELETE | `/api/workspaces/<ws>/sessions/<id>` | 软删除 |
| DELETE | `/api/workspaces/<ws>/sessions/<id>?permanent=1` | 永久删除 |
| POST | `/api/workspaces/<ws>/sessions/<id>/archive` | 归档 |
| POST | `/api/workspaces/<ws>/sessions/<id>/restore` | 恢复 |

### Job

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workspaces/<ws>/jobs` | 列出 |
| GET | `/api/workspaces/<ws>/jobs/<id>` | 详情 |
| POST | `/api/workspaces/<ws>/jobs/<id>/cancel` | 取消 |
| POST | `/api/workspaces/<ws>/jobs/<id>/retry` | 重试 |
| GET | `/api/workspaces/<ws>/jobs/<id>/events` | 事件列表 |
| GET | `/api/workspaces/<ws>/jobs/<id>/logs` | 日志 |

### Run

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workspaces/<ws>/runs` | 列出 |
| GET | `/api/workspaces/<ws>/runs/<id>` | 详情 |
| GET | `/api/workspaces/<ws>/runs/<id>/trace` | Trace 数据 |
| GET | `/api/workspaces/<ws>/runs/<id>/decision` | 决策报告 |

### Artifact

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workspaces/<ws>/artifacts` | 列出 |
| POST | `/api/workspaces/<ws>/artifacts` | 创建 |
| POST | `/api/workspaces/<ws>/artifacts/upload` | 上传文件 |
| GET | `/api/workspaces/<ws>/artifacts/<id>` | 详情 |
| GET | `/api/workspaces/<ws>/artifacts/<id>/content` | 内容 |
| DELETE | `/api/workspaces/<ws>/artifacts/<id>` | 删除 |

### 工具

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tools/invoke` | 直接调用工具 |
| GET | `/api/capabilities` | 能力列表 |
| GET | `/api/health` | 健康检查 |

## 通用约定

- 所有路径中的 `<ws>` 为 workspace_id，空或非法返回 400
- 响应格式：`{"ok": bool, ...}` 或 `{"ok": bool, "error": "message"}`
- 错误码：400 (参数错误), 404 (资源不存在), 413 (负载过大), 500 (服务端错误)
