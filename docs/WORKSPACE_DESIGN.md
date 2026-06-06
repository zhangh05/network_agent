# Workspace Design

## Overview

工作区运行时系统：状态摘要、运行历史、产物存储。**不保存完整配置和 secrets**。

## Storage

```
workspaces/{id}/
├── workspace.yaml          # 工作区元数据
├── state.json              # 当前状态摘要
├── runs/                   # 运行记录
│   └── {run_id}.json
└── artifacts/              # 产物文件
    ├── inputs/
    ├── outputs/
    ├── reports/
    └── temp/
```

## Schema: WorkspaceState

| 字段 | 说明 |
|------|------|
| workspace_id | 工作区 ID |
| name | 名称 |
| last_run_id | 最近运行 ID |
| last_intent | 最近意图 |
| last_active_module | 最近活跃模块 |
| last_result_summary | 结果摘要 (≤200 chars) |
| last_result_counts | 计数 (deployable_lines, manual_review_count, etc.) |
| last_manual_review_samples | 人工复核样本 (≤5) |
| last_unsupported_samples | 不支持样本 (≤5) |
| last_audit_summary | 审计摘要 |
| runs_count | 运行记录数 (实时统计) |
| memory_count | 记忆数 (实时统计) |
| artifacts_count | 产物数 (实时统计) |
| llm_metadata | LLM 元数据 |

## Schema: RunRecord

| 字段 | 说明 |
|------|------|
| run_id | 运行 ID |
| workspace_id | 工作区 |
| intent / active_module / selected_skill | 意图信息 |
| result_counts | 计数 (无完整配置) |
| llm_metadata | LLM 使用情况 |
| memory_written / workspace_updated | 记忆/状态写入标记 |

## Safety

- State 不保存 source_config / deployable_config (>500 chars 截断)
- Run 不保存完整配置
- Run 不保存 key / secrets
- 完整配置仅允许作为 sensitive artifact

## API

- `GET /api/workspaces` — 工作区列表 (runs_count 真实统计)
- `GET /api/workspaces/{id}/state` — 状态 (sanitized)
- `GET /api/workspaces/{id}/runs` — 运行列表
- `GET /api/workspaces/{id}/runs/{run_id}` — 单次运行
- `GET /api/workspaces/{id}/artifacts` — 产物列表
- `GET /api/workspaces/{id}/artifacts/{artifact_id}` — 产物详情
