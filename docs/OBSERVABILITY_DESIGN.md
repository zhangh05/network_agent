# Observability Design

## Overview

统一 Agent 可观测系统。Trace 用于**故障排查和性能分析**，**不存储完整敏感内容**。每次 `/api/agent/run` 生成完整 trace 记录。

Trace 存放位置: `workspaces/{workspace_id}/runs/{run_id}.trace.json`

## Agent Trace (7 Nodes)

每个节点记录 `node_start` / `node_end` 事件，含 `duration_ms`、`status`、`metadata`。

```
router → context → planner → executor → verifier → composer → memory
```

| 事件 | 携带元数据 |
|------|-----------|
| router_start/end | intent, confidence, selected_skill |
| context_start/end | context_id, ref_type, item_count, budget (见下方 Context metadata) |
| planner_start/end | plan_steps, selected_capability |
| executor_start/end | skill_name, module_name, adapter_called |
| verifier_start/end | result_valid, gate_pass |
| composer_start/end | llm_calls, llm_metadata, config_source |
| memory_start/end | memory_written, workspace_updated, run_record_written, session_associated (v3.1+) |

## Context Metadata (trace 内）

| 字段 | 说明 |
|------|------|
| context_id | 上下文标识 |
| ref_type | 引用类型 (project, workspace, run, artifact) |
| resolved | 是否成功解析 |
| item_count | 上下文条目数 |
| budget | token/char 预算 |

## Prompt Metadata (trace 内）

| 字段 | 说明 |
|------|------|
| prompt_task | 任务类型 |
| prompt_id | 模板 ID |
| prompt_version | 模板版本 |
| runtime_used | 使用的 runtime |
| rendered_prompt_used | 是否使用渲染后的 prompt |
| policy_pass | 安全策略是否通过 |
| context_chars | 上下文字符数 |
| output_accepted | 输出是否通过策略 |

## Artifact 事件

| 事件 | 说明 |
|------|------|
| artifact_saved | 产物保存 (artifact_id, scope, type, size) |
| artifact_read | 产物读取 |
| artifact_promoted | 产物升级 (temp → workspace) |

## Report 事件

| 事件 | 说明 |
|------|------|
| report_render_start/end | 报告渲染 |
| report_export_start/end | 报告导出 (format, size) |

## Job 事件

| 事件 | 说明 |
|------|------|
| job_created | 任务创建 |
| job_queued | 入队 |
| job_started | 开始执行 |
| job_progress | 进度更新 |
| job_run_started/finished | 内部 Agent run 起止 |
| job_artifact_saved | 任务关联产物 |
| job_report_created | 任务关联报告 |
| job_succeeded / job_failed / job_cancelled | 任务终态 |

## TraceRecord 汇总字段

| 字段 | 说明 |
|------|------|
| trace_id | Trace 唯一 ID |
| run_id | 关联运行 |
| workspace_id | 关联工作区 |
| events | TraceEvent 列表 |
| node_count | 节点数 |
| skill_call_count / module_call_count | 调用计数 |
| llm_call_count / memory_write_count | LLM/记忆计数 |
| total_duration_ms | 总耗时 |

## NEVER store in trace

| 禁止存储内容 |
|-------------|
| prompt 全文 |
| safe_llm_context 全文 |
| source_config 全文 |
| deployable_config 全文 |
| key / password / token / community |
| absolute path |

所有 trace 写入经过 redaction 层处理。
