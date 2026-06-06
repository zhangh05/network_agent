# Workspace Design

## Overview

工作区运行时系统，管理状态摘要、运行历史、产物存储。**不保存完整配置和 secrets**。

## 目录结构

```
workspaces/default/
├── workspace.yaml           # 工作区元数据
├── state.json               # 当前状态摘要
├── runs/                    # 运行记录 (.json + .trace.json)
├── artifacts/               # 产物文件
│   ├── inputs/
│   ├── outputs/
│   ├── reports/
│   └── temp/
├── jobs/                    # Job 记录
└── indexes/                 # 本地索引
```

## Workspace State 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| workspace_id | str | 工作区 ID |
| name | str | 名称 |
| last_run_id | str | 最近运行 ID |
| last_job_id | str | 最近任务 ID |
| last_result | str | 最近结果摘要 (≤200 chars) |
| current_artifacts | list | 当前产物引用列表 |
| artifact_counts | dict | 各类产物计数 |
| last_input_artifact | object | 最近输入产物引用 |
| last_output_artifact | object | 最近输出产物引用 |
| last_report_artifact | object | 最近报告产物引用 |
| job_total | int | 任务总数 |
| job_queued | int | 排队中 |
| job_running | int | 运行中 |
| job_succeeded | int | 已成功 |
| job_failed | int | 已失败 |
| job_cancelled | int | 已取消 |
| recent_jobs | list | 最近任务摘要 (≤10) |
| current_report_artifact_id | str | 当前报告产物 ID |
| current_topology_artifact_id | str | 当前拓扑产物 ID |
| runs_count | int | 运行记录总数 |
| llm_metadata | object | LLM 使用元数据 |

## 归属规则

- **Job 默认归属当前 workspace** — 任务创建时自动关联
- **Artifact 归属 scope**: `workspace` / `run` / `shared` / `temp`
- `workspace` scope — 工作区级别共享产物
- `run` scope — 单次运行私有产物
- `shared` scope — 跨模块共享（需显式授权）
- `temp` scope — 临时文件，会话结束清理

## 跨工作区访问

- 默认拒绝跨 workspace 访问
- shared scope artifact 可跨模块访问，但仍限于同一 workspace
- 跨 workspace 共享需显式配置白名单

## RunRecord

| 字段 | 说明 |
|------|------|
| run_id | 运行 ID |
| workspace_id | 关联工作区 |
| intent / active_module / selected_skill | 意图与路由信息 |
| result_counts | 结果统计（不含完整配置） |
| llm_metadata | LLM 使用信息 |
| memory_written | 是否写入记忆 |
| trace_id | 关联 trace |

## 安全约束

- State 不保存 source_config / deployable_config 全文
- Run 不保存完整配置 / key / secrets
- 完整配置文件仅允许作为 sensitive artifact 存储
- sensitive artifact 标记并限制 API 直接读取

## API

| 端点 | 说明 |
|------|------|
| `GET /api/workspaces` | 工作区列表 |
| `GET /api/workspaces/{id}/state` | 工作区状态 |
| `GET /api/workspaces/{id}/runs` | 运行历史 |
| `GET /api/workspaces/{id}/runs/{run_id}` | 单次运行详情 |
| `GET /api/workspaces/{id}/artifacts` | 产物列表 |
| `GET /api/workspaces/{id}/artifacts/{id}` | 产物详情 |

## 测试隔离

Harness 测试使用临时 workspace 目录 (`tmp_path`)，不污染 `workspaces/default/`。
