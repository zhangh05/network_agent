# Knowledge / Index Runtime Foundation v0.1

**Date:** 2026-06-07
**Commit base:** a869430
**Status:** ✅ 1191 passed, 7 skipped

## 定位

本轮不是完整 RAG。是 **Safe Local RAG Foundation** 的索引/搜索层。

## 数据流

```
Artifact (文件管理)
  → Knowledge Source (索引元数据)
    → Safe Chunk (安全分块)
      → Local Index (JSONL 索引)
        → Search Result (安全搜索)
```

- Artifacts 负责文件管理
- Knowledge / Index 负责让文件能被 Agent 安全检索
- 暂时不做自动 RAG 回答生成

## 模块结构

```
knowledge/
  __init__.py       — 模块说明
  schemas.py        — KnowledgeSource, SafeChunk, SearchResult
  policy.py         — 索引策略、安全门控、secret 检测
  chunker.py        — 文本安全分块
  store.py          — JSONL 本地索引存储
  indexer.py        — 索引编排
  search.py         — keyword + metadata 搜索

backend/api/
  knowledge_routes.py  — API 路由

harness/
  test_knowledge_index_runtime.py  — 43 tests
```

## Knowledge Source

- 来源：Artifact（workspace/artifact 内）
- 不读取任意本机路径
- 每个 source 关联 artifact_id
- 记录：source_id, artifact_id, title, artifact_type, sensitivity, lifecycle, status, chunk_ids, chunk_count

### 允许索引的类型

| artifact_type | 可索引 | 默认自动 |
|---------------|--------|----------|
| knowledge_doc | ✅ | ✅ |
| report | ✅ | ✅ |
| inspection_log | ✅ | — |
| input_config | ✅ | — |
| output_config | ✅ | — |
| topology_json | ✅ | — |
| export | ✅ | — |
| temp | ⚠️ | ❌ (默认不) |

### 安全门控

| 条件 | 结果 |
|------|------|
| lifecycle=deleted | ❌ 拒绝 |
| lifecycle=quarantined | ❌ 拒绝 |
| sensitivity=secret | ❌ 拒绝 |
| sensitivity=sensitive | ⚠️ 仅 metadata，不生成 LLM chunks |
| sensitivity=internal/public | ✅ 正常索引 |

## Safe Chunk

- 文本分块：800 字符/chunk，150 字符 overlap
- 每 chunk 保存：safe_excerpt (≤200 chars)，不保存完整原文
- Secret 检测 + 脱敏：password, token, api_key, community 等
- 敏感 chunk 标记 llm_safe=False
- 不保存 absolute path

## Local Index Store

- 格式：JSONL（sources.jsonl + chunks.jsonl）
- 位置：`workspaces/<ws_id>/indexes/knowledge/`
- 不引入外部向量库
- 按 workspace_id 隔离

## Search API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge/sources` | GET | 列出 sources，统计 |
| `/api/knowledge/sources/from-artifact` | POST | 从 artifact 创建 source |
| `/api/knowledge/sources/<id>/reindex` | POST | 重新索引 |
| `/api/knowledge/search?q=...` | GET | keyword + metadata 搜索 |
| `/api/knowledge/chunks/<id>` | GET | chunk 详情 |

搜索支持过滤：artifact_type, sensitivity, source_id, artifact_id, limit。

搜索结果返回：title, summary, safe_excerpt, artifact_type, sensitivity, score。
不返回：full file, full config, absolute path, secrets。

## 前端增强

在 Artifacts 页面：
- 每行显示 Indexed / Not indexed / Index failed 状态
- Add to Knowledge Index (★) 按钮
- Re-index (↺) 按钮
- Search knowledge 搜索框 + 结果区
- 结果区显示 title, type, sensitivity, summary, safe_excerpt, score
- 提示"搜索结果为安全摘录，不是全文"

## 安全红线

| 禁止项 | 状态 |
|--------|------|
| 不读 workspace/artifact 外任意路径 | ✅ |
| 不索引 absolute path | ✅ |
| 不写 full config 到 index | ✅ |
| 不写 secrets 到 chunk | ✅ |
| 不接外部向量库 | ✅ |
| 不接真实设备 | ✅ |
| LLM 不参与 chunking/indexing | ✅ |

## 未做（后续 v0.2）

- Agent 自动 RAG 回答
- 自动 context injection
- Embedding / 向量检索
- Rerank
- PDF/OCR
- LLM source citation answer
