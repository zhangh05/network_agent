# 架构设计

## 核心设计原则

1. **单一数据源**：所有可检索数据存储在 `context/items.jsonl`，通过 `item_type` 区分
2. **统一检索**：单一 BM25 引擎，memory 和 knowledge 共享评分管线
3. **Schema 驱动**：每种 item_type 有字段白名单，压缩/脱敏按 schema 执行
4. **最小权限 + 基线保障**：工具按场景过滤，但始终保证 15+ 基线工具可用
5. **三级压缩**：RAG → Auto-compact → 会话历史，逐级降级

## 数据流

```
                    ┌─────────────────────────────────────────┐
                    │           ContextStore                   │
                    │         (items.jsonl)                    │
                    │                                         │
  知识上传 ──→ ingestion ──→  knowledge_source + chunk         │
  记忆写入 ──→ writer ─────→  memory_hit                       │
  画像更新 ──→ tools ──────→  profile                          │
                    └──────────────┬──────────────────────────┘
                                   │
                          UnifiedRetriever (BM25)
                                   │
                    ┌──────────────┴──────────────────────────┐
                    │           SafeContext                    │
                    │  memory_hits[] + knowledge_hits[]        │
                    │  + citations[] + context_sources[]       │
                    └──────────────┬──────────────────────────┘
                                   │
                          Prompt Renderer
                                   │
                              LLM Request
```

## 模块职责

| 模块 | 职责 | 关键文件 |
|------|------|---------|
| `context/context_store.py` | 统一 JSONL 存储 + GC | put/get/list/delete/compact |
| `context/unified_retriever.py` | BM25 检索 + 去重 | search/search_memory/search_knowledge |
| `context/schema_registry.py` | 字段白名单 | strip_by_schema/allowed_fields |
| `context/compressor.py` | Schema 驱动压缩 | compress_context_items |
| `context/builder.py` | 上下文构建管道 | build_context_bundle |
| `context/loader.py` | ContextItem 加载 | load_context_items |
| `agent/runtime/loop.py` | Agent 循环（最多 8 步） | run_turn |
| `agent/runtime/tool_planner.py` | 工具规划 + 基线注入 | deterministic_plan_tools |
| `agent/runtime/context_builder.py` | TurnContext 组装 + auto-compact | build_turn_context |

## 工具系统

### action_class 分级

| 级别 | 说明 | 审批 |
|------|------|------|
| read | 只读操作 | 无 |
| write | 写入操作 | 无 |
| mutate | 破坏性变更 | 需确认 |
| execute | 系统命令执行 | 审批门控 |
| external | 外部网络访问 | 无 |

### 基线工具集

每个场景始终注入的 14 个工具：

```python
_BASELINE_TOOLS = [
    "web.search", "web.page.summarize", "web.docs.official_search",
    "knowledge.search", "knowledge.source.list",
    "memory.search", "memory.list", "memory.create",
    "workspace.file.read", "workspace.file.list",
    "host.shell.exec",
    "agent.result.get", "agent.role.list",
    "skill.list",
]
```

### 路由逻辑

`tool_category_router.py` 提取意图信号（web/knowledge/host/network/memory/...），添加对应类别工具，叠加在基线之上。

## 上下文预算

| 模型 | 窗口 | RAG 预算 (25%) | Auto-compact (85%) |
|------|------|---------------|-------------------|
| MiniMax M3 | 245K | 61K chars | 52K tokens |
| GPT-4o | 128K | 32K chars | 109K tokens |
| DeepSeek V3 | 128K | 32K chars | 109K tokens |
