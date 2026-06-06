# Memory Design

## Overview

Agent 原生记忆系统，JSONL backend (`memory/data/memories.jsonl`)。Memory 仅存储**摘要、决策、偏好、运行/任务摘要**，**不存储完整敏感内容**。所有写入走 redaction + policy 门控。

## Memory 类型

| memory_type | 说明 | 写入时机 |
|-------------|------|----------|
| `run_summary` | Agent 运行摘要 | agent run 完成时 |
| `job_summary` | Job 任务摘要 | job succeeded / failed / cancelled 时 |
| `decision` | 用户决策记录 | 用户确认操作时 |
| `user_preference` | 用户偏好 | 用户设置变更时 |
| `project_state` | 项目状态摘要 | 项目状态变更时 |
| `translation_rule` | 翻译规则记忆 | 人工复核确认规则时 |
| `artifact_summary` | 产物摘要 | 产物保存时 |

## Schema (核心字段)

| 字段 | 说明 |
|------|------|
| memory_id | 唯一 ID |
| memory_type | 见上表 |
| scope | short_term / project / long_term |
| title | 标题 |
| summary | 摘要 (≤500 chars) |
| tags | 标签列表 |
| source | agent / user / system / user_confirmed |
| confidence | system_generated / user_confirmed / inferred |
| sensitivity | public / internal / sensitive |
| redaction_applied | 是否已脱敏 |

## 写入规则

- `run_summary` — agent run 完成后自动写入，仅含摘要
- `job_summary` — job 结束后写入，含状态、时长、artifact 引用
- `artifact_refs` — 仅存 `artifact_id` + `summary`，不存完整内容
- `decision` / `translation_rule` / `user_preference` — 必须 `user_confirmed`
- `report` artifact — 仅存引用和摘要，不存完整报告内容

## 安全规则：NEVER store

| 禁止存储内容 | 说明 |
|-------------|------|
| source_config | 源配置文件全文 |
| deployable_config | 可部署配置全文 |
| report full content | 审计报告完整内容 |
| key / secret / password | 任何密钥 |
| community / token | 网络密钥字符串 |
| absolute path | 本地绝对路径 |

## Redaction 覆盖

```
password, secret, community, pre-shared-key, API key,
token, Authorization, IPsec key, RADIUS/TACACS key,
MINIMAX/OPENAI/DEEPSEEK/OLLAMA key
→ [REDACTED_SECRET]
```

## API

| 端点 | 说明 |
|------|------|
| `GET /api/memory/status` | 系统状态 |
| `GET /api/memory/list` | 记忆列表 (scope/memory_type/project_id 筛选) |
| `POST /api/memory/search` | 搜索 |
| `POST /api/memory/write` | 写入 (redaction + policy) |
| `POST /api/memory/confirm` | 用户确认写入 |
| `DELETE /api/memory/{id}` | tombstone 删除 |

## Harness 隔离

pytest 使用临时目录，不污染正式 `memory/data/`。
