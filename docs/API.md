# API 参考

## Agent

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/agent/message` | 发送消息，返回 AgentResult |
| WS | `/ws/agent` | WebSocket 流式对话 |
| GET | `/api/agent/approvals/pending` | 待审批列表 |
| POST | `/api/agent/approvals/:id/resolve` | 审批决策 |

## 知识库

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/knowledge/sources` | 知识来源列表 |
| GET | `/api/knowledge/sources/:id` | 来源详情 + chunks |
| POST | `/api/knowledge/upload` | 上传文档 (multipart) |
| GET | `/api/knowledge/search?q=` | BM25 搜索 |
| DELETE | `/api/knowledge/sources/:id` | 删除来源 + chunks |
| PATCH | `/api/knowledge/sources/:id` | 重命名 |
| POST | `/api/knowledge/sources/:id/reindex` | 重建索引 |
| GET | `/api/knowledge/chunks/:id` | chunk 详情 |

## 记忆

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/memory/list` | 记忆列表 |
| POST | `/api/memory/search` | 记忆搜索 |
| POST | `/api/memory/write` | 写入记忆 |
| POST | `/api/memory/confirm` | 确认记忆 |
| DELETE | `/api/memory/:id` | 删除记忆 |
| GET | `/api/memory/status` | 系统状态 |

## 文件管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/files` | 文件列表（含 ContextStore 项） |
| GET | `/api/files/:id` | 文件详情 |
| GET | `/api/files/:id/content` | 文件内容 |
| POST | `/api/files` | 创建/上传文件 |
| PUT | `/api/files/:id` | 更新元数据 |
| DELETE | `/api/files/:id` | 删除（文件系统 + ContextStore） |

## Session

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions/:id/messages` | 消息历史 |

## 工具

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/tools/catalog` | 工具目录 (104 个) |
| POST | `/api/tools/invoke` | 手动调用工具 |
| GET | `/api/tools/permissions` | 权限配置 |

## LLM 配置

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/agent/llm/config` | 当前配置 |
| POST | `/api/agent/llm/config` | 更新配置 |
| GET | `/api/agent/llm/providers` | Provider 列表 |
| POST | `/api/agent/llm/test` | 连接测试 |

## 运行时

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/version` | 版本信息 |
| GET | `/api/runtime/summary` | 运行时摘要 |
| GET | `/api/runtime/health` | 组件健康 |
