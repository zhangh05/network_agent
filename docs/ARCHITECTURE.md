# 架构详解

## 统一上下文架构 (v3.1.0)

### ContextStore

单一 JSONL 存储，所有可检索数据通过 `item_type` 区分：

```
workspaces/default/context/items.jsonl
├── knowledge_chunk  (205 条)  — 文档片段
├── knowledge_source (34 条)   — 文档来源
├── memory_hit       (23 条)   — Agent 记忆
└── profile          (1 条)    — 用户画像
```

特性：追加写入、墓碑删除、last-write-wins、compact GC。

### UnifiedRetriever

单一 BM25 引擎：

- CJK bigram/trigram 分词
- field-weighted scoring (title 3x, chapter 2x, tags 2.5x, content 1x)
- scope boost (session 1.5x, workspace 1.2x, global 1x)
- query expansion (网络领域同义词字典)
- Jaccard sibling 去重 (>75%)
- 30 秒自动 reindex

### Schema Registry

每种 item_type 定义字段白名单：

```python
_TYPE_EXTENSIONS = {
    "memory_hit": {"memory_id", "memory_type", "score", "confidence", "tags", ...},
    "knowledge_chunk": {"chunk_id", "chapter", "section", "index_text", "score", ...},
    "profile": {"profile_id", "profile_field", "value", "confidence"},
}
```

compressor 按白名单 strip，不再用黑名单。

## 知识库管线

```
文件上传 → ingestion.py → parsers → chunking.py → ContextStore
                              ↓
                      NormalizedDocument
                              ↓
                   parent chunks (1200-3000 chars)
                              ↓
                   child chunks (400-800 chars, 80 overlap)
```

支持格式：TXT、Markdown、PDF、JSON、YAML。

## 记忆系统

```
Agent/用户 → writer.py → 脱敏 → 策略检查 → 冲突扫描 → ContextStore
```

记忆类型：knowledge_note、decision、translation_rule、user_preference、run_summary。

## 前后端通信

- **WebSocket** `/ws/agent` — 流式 token + 事件
- **HTTP** `/api/agent/message` — 非流式 fallback (POST /api/agent/message)
- **REST** `/api/knowledge/*`, `/api/memory/*`, `/api/files/*` — CRUD

## ToolRuntime

工具运行时 (`tool_runtime/`) 管理 104 个注册工具的生命周期：注册、分类、路由、执行、审批。ToolRouter 根据用户意图选择 candidate tools，ToolRuntime 通过 `dispatch()` 执行，结果经 ToolResult 标准化后返回。
