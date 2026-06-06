# Observability Design

## Overview

统一 Agent 运行可观测系统。每次 `/api/agent/run` 生成完整 trace，记录所有节点、Skill、Module、LLM、Memory/Workspace 操作。

## Trace Schema

### TraceEvent

| 字段 | 说明 |
|------|------|
| event_id | 事件唯一 ID |
| trace_id | 关联 trace |
| run_id | 关联 run |
| event_type | node_start/node_end/skill_call_start/module_call_start/llm_call_start 等 |
| name | 人类可读名称 (router, context_loader, executor, llm, ...) |
| status | started/success/failed/skipped |
| timestamp | ISO 时间戳 |
| duration_ms | 耗时 (毫秒) |
| summary | 摘要 |
| metadata | 元数据 (不含完整配置) |
| redaction_applied | 是否已脱敏 |

### TraceRecord

| 字段 | 说明 |
|------|------|
| trace_id | trace 唯一 ID |
| run_id | 关联 run |
| workspace_id | 工作区 |
| events | TraceEvent 列表 |
| node_count | 节点数 |
| skill_call_count | Skill 调用次数 |
| module_call_count | Module 调用次数 |
| llm_call_count | LLM 调用次数 |
| memory_write_count | Memory 写入次数 |
| total_duration_ms | 总耗时 |

## 存储位置

```
workspaces/{workspace_id}/runs/{run_id}.trace.json
```

## Trace 安全边界

- 不保存完整 source_config
- 不保存完整 deployable_config
- 不保存 key/password/community/token
- LLM trace 不保存 prompt 全文
- Module trace 不保存 deployable_config 全文
- 所有写入走 redaction

## Agent Timeline

```
agent_start
  → router (intent_routed)
  → context_loader (context_loaded)
  → planner
  → executor
      → skill_call_start → module_call_start → module_call_end → skill_call_end
  → verifier
  → composer (llm_call_start/end if enabled)
  → memory_writer (memory_write, workspace_update, run_record_write)
agent_end
```

## API

- `GET /api/workspaces/{ws_id}/runs/{run_id}/trace` — 获取 trace
- `GET /api/workspaces/{ws_id}/traces` — 列出 traces
- `GET /api/agent/runs/{run_id}/trace` — 按 run_id 查 trace
- `/api/agent/run` 返回 `trace_id`, `trace_available`, `timeline_summary`

## UI

Agent 运行结果显示 timeline_summary，点击 "查看运行轨迹" 获取完整 trace。
