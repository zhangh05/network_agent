# Memory Design

## Overview

Agent 原生记忆系统，JSONL backend。

## Storage

- 主文件: `memory/data/memories.jsonl`
- 删除记录: `memory/data/.deleted_memories.json` (tombstone)
- 旧文件 `memory_records.jsonl` 自动迁移

## Schema: MemoryRecord

| 字段 | 类型 | 说明 |
|------|------|------|
| memory_id | str | 唯一 ID |
| scope | str | short_term / project / long_term |
| memory_type | str | decision / user_preference / project_state / device_profile / translation_rule / troubleshooting_case / run_summary / knowledge_note |
| title | str | 标题 |
| summary | str | 摘要 |
| content | str | 正文 |
| tags | list[str] | 标签 |
| project_id | str | 关联项目 |
| source | str | agent / user / system / user_confirmed |
| confidence | str | system_generated / user_confirmed / inferred / imported |
| sensitivity | str | public / internal / sensitive |
| created_at | str | 创建时间 ISO |
| updated_at | str | 更新时间 ISO |
| expires_at | str? | 过期时间 |
| metadata | dict | 元数据 |
| redaction_applied | bool | 是否已脱敏 |

## Policy

写入规则：
- 不保存完整 source_config / deployable_config
- Secrets 必须 redaction (password, key, community, etc.)
- long_term / decision / translation_rule 必须 user_confirmed
- LLM 生成内容默认 short_term 或 run_summary

## Redaction

脱敏模式覆盖：
- password, secret, community, pre-shared-key
- API key, token, Authorization
- IPsec key, RADIUS/TACACS key
- MINIMAX/OPENAI/DEEPSEEK API key

脱敏格式: `[REDACTED_SECRET]`

## API

- `GET /api/memory/status` — 系统状态
- `GET /api/memory/list?scope=&memory_type=&project_id=&limit=` — 列表
- `POST /api/memory/search` — 搜索 (keyword + tags + project_id + memory_type + scope + limit)
- `POST /api/memory/write` — 写入 (redaction + policy)
- `POST /api/memory/confirm` — 用户确认写入
- `DELETE /api/memory/{id}` — tombstone 删除

## Harness Isolation

pytest 使用临时目录，不污染正式 `memory/data/`。
