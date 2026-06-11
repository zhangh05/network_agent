# Knowledge Store Management v1.0

> **2026-06-10 更新**：v1.0 之后已经迈入 **v1.0.1 — Document Ingestion & Book Library**。
>
> v1.0 把 `knowledge` capability 从"分散的 `query`"升级为**完整后端知识库能力**（5 个新 tool + 保留 query），KnowledgeStore 用 JSONL 存数据，token-overlap 做检索。
> 详细见 [KNOWLEDGE_STORE_V10.md](KNOWLEDGE_STORE_V10.md)。
>
> v1.0.1 在 v1.0 之上**新增**：
> - `parsers/` 子包（md / txt / html / docx / text-pdf）
> - `chunking.py`（结构优先 + 保护块 + 父子分块）
> - `index.py`（纯 Python BM25 + scope boost）
> - `ingestion.py`（file → NormalizedDocument → Source + chunks）
> - 6 个新 knowledge tool（import_file / list_chunks / search_chunks / read_chunk / read_parent / reindex_source）
> - `knowledge.query` 改为 3 段 fallback：chunk→v1.0 store→legacy loader
> - Tool count 67 → 73（+6）
> 详细见 [DOCUMENT_INGESTION_BOOK_LIBRARY_V101.md](DOCUMENT_INGESTION_BOOK_LIBRARY_V101.md)。

> 把 `knowledge.query` 从"查询已有上下文 / loader"升级为**完整后端知识库能力**：导入、列表、读取、删除 / 禁用、查询、`source_summary` 展开。
> 本轮只做后端，不做前端。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CAPABILITY_MANIFEST_V08.md](CAPABILITY_MANIFEST_V08.md) · [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md) · [ARTIFACT_REVIEW_FLOW_V09.md](ARTIFACT_REVIEW_FLOW_V09.md)

## 1. 目标

让 LLM 能像管理一个本地知识库一样管理 workspace 的资料：
- 导入文档（**不伪造来源**）
- 列出已导入的 source 记录
- 读取单个 source 的 content + metadata
- 软禁用 / 软删除 source
- 用 token-overlap scoring 查询 source（**不要求向量库**）
- `source_summary` 展开：每个 snippet ≤ 200 字符
- **无 hits 时返回空 summary**（不伪造）
- **不依赖外部数据库**：本地 JSONL 文件即可

## 2. 新增 Tools (v1.0, 全部 enabled)

| tool_id | 用途 | 风险 |
|---|---|---|
| `knowledge.import_document` | 导入文本到 workspace knowledge store | low |
| `knowledge.list_sources` | 列出 source 记录 | low |
| `knowledge.read_source` | 读取单条 source 的 content + metadata | low |
| `knowledge.disable_source` | 软禁用 source（不再被 query 命中） | low |
| `knowledge.delete_source` | 软删除 source（保留 audit trail） | low |
| `knowledge.query` | **v0.7.1 保留**，现由 KnowledgeStore 驱动 | low |

## 3. KnowledgeStore 实现

### 3.1 存储路径

```
{ws_root}/{workspace_id}/knowledge/
    sources.jsonl     # 一行一条 Source（jsonl 格式）
    index.json        # 元数据：version / source_count / last_query_at
```

`ws_root` 解析逻辑（与 review service 保持一致）：
1. 优先 `workspace.manager.WS_ROOT`（**被 `harness/conftest.py` monkeypatch 为 temp dir**）
2. fallback `artifacts.store._get_ws_root()`

**无外部 DB 依赖**（spec 严禁）；纯文件 + 内存索引。

### 3.2 Source 记录结构

```python
{
  "source_id":  "ksrc_xxxxxxxxxxxxxxxx",   # 16 hex，ksrc_ 前缀
  "title":      str,                       # ≤ 500 chars
  "content":    str,                       # ≤ 200_000 chars（截断）
  "source":     str,                       # caller-supplied origin label
                                            # (local path 会被 redact 成
                                            # "redacted-local-path")
  "enabled":    bool,                      # soft-disable flag
  "deleted":    bool,                      # soft-delete flag
  "created_at": "2026-06-10T16:08:15.277384+00:00",
  "updated_at": "2026-06-10T16:08:15.278523+00:00",
  "metadata":   dict                       # caller-supplied arbitrary
}
```

### 3.3 公开视图

`_public_view(rec, include_content=False)`:
- `list_sources` 返回的 view：**不含 content**，**不含本地路径**
- `read_source` 返回的 view：**含 content**

### 3.4 并发安全

- per-workspace `threading.RLock`（store 是 process-local）
- JSONL 写入：写到 `sources.jsonl.tmp` 再 `Path.replace()`（POSIX atomic）

## 4. Query Scoring

v1.0 使用**轻量级 token 重叠打分**，**不**使用向量库：

```python
def _score(query_tokens, source):
    title_tokens   = set(_tokenize(source["title"]))
    content_lower  = source["content"].lower()
    source_label   = source["source"].lower()
    total = 0.0
    for tok in query_tokens:
        if tok in title_tokens:        total += 2.0   # title 命中权重
        if tok in content_lower:       total += 1.0   # content 命中
        if tok in source_label:        total += 0.5   # source label 命中
    return total / len(query_tokens)   # ∈ [0, 3.5]
```

排序：按 score 降序，相同 score 按 created_at 升序。

**不透明性**：score 是 token 重叠的确定性函数，**不**重新排序，**不**虚构额外 source。metadata 显式记录 `retrieval_backend=local_store, scoring=token_overlap_v1`。

## 5. source_summary 行为

`source_summary` 是 query 结果的"轻量引用视图"，**只**由真实 hit 派生：
- 最多 5 条
- 每条 snippet ≤ **200 字符**
- snippet 居中策略：query token 在 content 中的位置 ± 60 字符
- 无 hits → `source_summary=[]`（**不伪造**）

| 场景 | source_count | source_summary |
|---|---|---|
| store 有匹配 source | `> 0` | `[{title, source, score, snippet}, ...]` |
| store 无匹配 source | `0` | `[]` |
| store 完全空 + legacy loader 有命中 | `> 0` | （从 legacy loader 派生） |
| store 完全空 + legacy loader 不可用 | `0` | `[]`（+warning `store_empty, legacy_loader_unavailable`） |

## 6. Tool count 变化

| 维度 | v0.9 | v1.0 |
|---|---|---|
| 计划新增 tool_ids | — | 5（knowledge.import/list/read/disable/delete）+ 1（knowledge.query 保留） |
| Capability 层 enabled tool 数 | 8 | **13**（+5） |
| 实际 catalog 总数 | 62 | **67**（+5） |
| 差异原因 | — | 5 个新 tool_ids 都未在 ToolRuntime catalog 中出现，**无**去重 |

**spec 预测 67**；**实际 67** ✓

## 7. CapabilityRegistry 变化

| 维度 | v0.9 | v1.0 |
|---|---|---|
| `list_all()` | 7 | **7**（不变） |
| `list_enabled()` | 4 | **4**（不变） |
| `list_planned()` | 3 | **3**（不变） |
| `visible_tool_ids()` | 8 | **13**（+5） |
| Skills enabled | 5 | **5**（不变；`knowledge_query` intent_patterns 增加 `import` / `list` / `disable` / `delete`） |

## 8. 兼容性路径

v0.7.1 的 `context.knowledge_loader` 仍保留：
- 当 store **没有 enabled source** 时，`query_knowledge` 走 legacy loader 路径
- 命中 → 返回 legacy 结果（标注 `retrieval_backend=legacy_loader`）
- 不命中 → 标注 `retrieval_backend=local_store, store_empty, legacy_loader_unavailable`
- v0.7.1 capability tests 41/41 零回归

## 9. 不变量

| 强制 | 说明 |
|---|---|
| **不伪造 source** | source_id 由 store 生成，content/title 由 caller 提供 |
| **不伪造 score** | score 是 token 重叠的确定性函数；不 re-rank、不造额外 source |
| **不伪造 snippet** | snippet 来自真实 content，居中截取 ≤ 200 字符 |
| **不暴露本地路径** | caller 传 `/Users/...` 等路径时，存储用 `redacted-local-path` 替换 |
| **不接真实设备** | 6 个 knowledge tool 全部 `real_device_access=False` |
| **不开 SSH/Telnet/SNMP/nmap** | 0 启用；ToolRuntime 拦截表未触碰 |
| **config.push 永久禁止** | 0 触碰 |
| **planned 永不暴露** | topology / inspection / cmdb 仍是 `callable_by_llm=False` |
| **v0.7.1 capability tests 零回归** | 41/41 passed |
| **Runtime 主链** | 0 改动 |

## 10. 模块接入现状

| Module | service 函数 | `to_module_result` | `ToolResult.from_module_result` |
|---|---|---|---|
| `config_translation` | `translate_config()` | ✓ | ✓ |
| **`knowledge` (UPGRADED v1.0)** | `query_knowledge` / `import_document` / `list_sources` / `read_source` / `disable_source` / `delete_source` | ✓ | ✓ |
| `artifact` | `list_artifacts_for_session` / `read_artifact` / `diff_artifacts` / `export_artifact` | ✓ | ✓ |
| `review` | `list_review_items` / `update_review_item` | ✓ | ✓ |
| `topology` (planned) | — | — | — |
| `inspection` (planned) | — | — | — |
| `cmdb` (planned) | — | — | — |

## 11. 后续 (v1.0.x / v1.1)

| 版本 | 主题 |
|---|---|
| v1.0.x | 前端 API 对齐（FastAPI 路由 / SSE 推送 store 变化） |
| v1.0.x | embedding-based scoring（可选，与 token-overlap 并存） |
| v1.1 | 跨 workspace 知识联邦（按 visibility 策略） |
| v1.1 | review 接入：把 review item 接到 knowledge metadata 上 |
