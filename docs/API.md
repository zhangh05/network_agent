# API

所有业务接口使用 `/api` 前缀。错误响应至少包含 `ok: false` 和 `error`。

## Agent 与 LLM

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/agent/message` | 执行完整 Agent turn |
| GET | `/api/agent/status` | Agent 状态 |
| GET | `/api/agent/usage` | Token 用量 |
| GET | `/api/agent/llm/status` | 当前 LLM 状态 |
| POST | `/api/agent/llm/test` | 测试 Provider |
| GET | `/api/agent/llm/providers` | 列出 Provider |
| GET/POST/DELETE | `/api/agent/llm/providers/{provider_id}` | 读取、保存或重置 Provider |
| POST | `/api/agent/llm/activate` | 激活 Provider |

## 工作区、会话与运行

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/workspaces` | 列出或创建工作区 |
| GET | `/api/workspaces/{workspace_id}/state` | 读取工作区状态 |
| DELETE | `/api/workspaces/{workspace_id}` | 删除工作区 |
| POST | `/api/workspaces/{workspace_id}/rename` | 重命名工作区 |
| GET/POST | `/api/sessions` | 列出或创建会话 |
| GET/PUT/DELETE | `/api/sessions/{session_id}` | 读取、更新或删除会话 |
| POST | `/api/sessions/{session_id}/archive` | 归档会话 |
| POST | `/api/sessions/{session_id}/restore` | 恢复会话 |
| GET | `/api/sessions/{session_id}/messages` | 读取消息 |
| GET | `/api/runs/recent` | 按工作区和会话读取最近运行 |
| GET | `/api/workspaces/{workspace_id}/runs/{run_id}` | 读取运行 |
| GET | `/api/workspaces/{workspace_id}/runs/{run_id}/trace` | 读取 trace |

## 文件与制品

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/files` | 列出或创建统一文件记录 |
| GET/PUT/DELETE | `/api/files/{file_id}` | 读取、更新或删除文件 |
| GET | `/api/files/{file_id}/content` | 读取文件内容 |
| GET/POST | `/api/workspaces/{workspace_id}/artifacts` | 列出或创建制品 |
| POST | `/api/workspaces/{workspace_id}/artifacts/upload` | 上传制品 |
| GET/DELETE | `/api/workspaces/{workspace_id}/artifacts/{artifact_id}` | 读取或删除制品 |
| GET | `/api/workspaces/{workspace_id}/artifacts/{artifact_id}/content` | 读取制品内容 |
| POST | `/api/workspaces/{workspace_id}/artifacts/{artifact_id}/promote` | 提升制品 |

文件类型包括 `pcap`、`pcap_analysis`、`knowledge`、`memory`、`artifact` 和 `general`。

## 报文分析

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/pcap/parse` | 保存并解析 pcap，创建可恢复 session |
| GET | `/api/pcap/session/{session_id}` | 从内存或磁盘恢复分析 session |
| POST | `/api/pcap/filter` | 按五元组筛选报文 |
| POST | `/api/pcap/align` | TCP 序列对齐与异常分析 |

文件管理页通过报文记录的 `metadata.session_id` 跳转到 `/packet?sid={session_id}`。

## 知识库

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/knowledge/upload` | 导入并索引文档 |
| GET | `/api/knowledge/sources` | 列出知识来源 |
| POST | `/api/knowledge/sources/from-artifact` | 将制品导入知识库 |
| GET/PATCH/DELETE | `/api/knowledge/sources/{source_id}` | 读取、重命名或删除来源 |
| POST | `/api/knowledge/sources/{source_id}/reindex` | 重建来源索引 |
| GET | `/api/knowledge/search` | 使用 `q`、`workspace_id`、`limit`、`source_id` 检索 |
| GET | `/api/knowledge/chunks/{chunk_id}` | 读取安全分块摘要 |

## 工具、审批与维护

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/tools/catalog` | 当前工具目录 |
| POST | `/api/tools/invoke` | 调用工具 |
| POST | `/api/tools/dry-run` | 校验工具调用但不执行 |
| GET | `/api/tools/history` | 工具历史 |
| GET/POST | `/api/tools/approvals` | 审批列表或创建审批 |
| PUT | `/api/tools/approvals/{approval_id}/approve` | 通过审批 |
| PUT | `/api/tools/approvals/{approval_id}/reject` | 拒绝审批 |
| GET | `/api/runtime/summary` | 运行时能力摘要 |
| GET | `/api/runtime/health` | 运行时健康状态 |
| GET | `/api/runtime/selfcheck` | 运行时自检 |
| GET/POST | `/api/workspaces/{workspace_id}/retention/{preview|apply}` | 保留策略 |
| GET/POST | `/api/workspaces/{workspace_id}/archive/{preview|apply}` | 归档 |

## 记忆与作业

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/memory/status` | 记忆状态 |
| GET | `/api/memory/list` | 列出记忆 |
| POST | `/api/memory/search` | 搜索记忆 |
| POST | `/api/memory/write` | 写入记忆 |
| POST | `/api/memory/confirm` | 确认记忆 |
| DELETE | `/api/memory/{memory_id}` | 删除记忆 |
| GET/POST | `/api/jobs` | 列出或创建作业 |
| GET | `/api/jobs/{job_id}` | 作业详情 |
| POST | `/api/jobs/{job_id}/cancel` | 取消作业 |
| POST | `/api/jobs/{job_id}/retry` | 重试作业 |
| GET | `/api/jobs/{job_id}/events` | 作业事件 |
