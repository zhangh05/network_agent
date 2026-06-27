# API 契约规则

## 原则

1. **Backend 为唯一权威来源**。前端类型定义必须从后端 API 响应派生，不得自行定义独立的结构。
2. **响应格式统一**。所有成功响应 `{ok: true, ...data}`，错误响应 `{ok: false, error: "message"}`。
3. **workspace_id 全局强制**。非法或空 workspace_id 返回 400。
4. **级联清理**。删除资源时必须同步清理关联数据。

## 通用参数

| 参数 | 位置 | 类型 | 要求 |
|------|------|------|------|
| `workspace_id` | path/query | string | 必填，非空，须为合法 ID |
| `session_id` | query/body | string | 可选，允许 null |
| `limit` | query | int | 可选，默认 50，最大 500 |

## 错误码

| HTTP 状态码 | 含义 | 场景 |
|-------------|------|------|
| 400 | 参数错误 | 缺失必填参数、workspace_id 为空 |
| 404 | 不存在 | 资源 ID 不存在 |
| 413 | 负载过大 | 消息/文件超过大小限制 |
| 500 | 服务端错误 | 未预期的运行时错误 |

## 响应格式

成功：
```json
{
  "ok": true,
  "session": { ... },
  "messages": [ ... ]
}
```

错误：
```json
{
  "ok": false,
  "error": "描述性错误信息",
  "error_type": "provider_timeout"
}
```

错误类型（`error_type`）：
- `provider_timeout` — 可重试
- `provider_error` — 可重试
- `api_key` — 不可重试，需检查配置
- `forbidden_function` — 可重试，换方式
- `syntax_error` — 可重试
- `caller_identity` — 不可重试
- `network` — 可重试

## WebSocket 协议

连接：`ws://host/ws/agent`

客户端发送：
```json
{"type": "message", "user_input": "...", "session_id": "...", "workspace_id": "..."}
```

服务端推送：
```json
{"type": "token", "content": "流式文本片段"}
{"type": "event", "name": "tool_call", "data": {"tool_id": "...", ...}}
{"type": "done", "session_id": "...", "turn_id": "...", "final_response": "...", "tool_calls": [...], "errors": [], ...}
{"type": "error", "message": "..."}
```
