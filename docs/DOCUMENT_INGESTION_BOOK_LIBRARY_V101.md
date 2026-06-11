# Document Ingestion & Book Library v1.0.1

> 把 `knowledge` capability 升级为**完整后端知识库能力**：原始文件 → 标准化 Markdown → Source → Parent/Child Chunks → 混合检索 → 父级上下文扩展 → 真实来源返回。
> 本轮只做后端，不做前端。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CAPABILITY_MANIFEST_V08.md](CAPABILITY_MANIFEST_V08.md) · [KNOWLEDGE_STORE_V10.md](KNOWLEDGE_STORE_V10.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md) · [ARTIFACT_REVIEW_FLOW_V09.md](ARTIFACT_REVIEW_FLOW_V09.md)

## 1. 设计原则

| 原则 | 实现 |
|---|---|
| 分层作用域 | `global` / `workspace` / `session`；默认检索优先级 `session > workspace > global` |
| 目录/摘要先行 | `KnowledgeSource` 提供 title/author/edition/source_type/scope/format/language；目录/摘要先行，正文按需加载 |
| 正文按需加载 | `search_chunks` 返回 snippet；`read_chunk` / `read_parent` 按需展开 |
| 检索与读取分离 | `search_chunks` 只返回 child 命中；`read_chunk` / `read_parent` 按需展开 |
| 不伪造来源 | 章节/页码/分数都来自解析器/算法本身，**不**凭空构造 |

## 2. 流水线

```
原始文件 (md / txt / html / docx / text-pdf)
  ↓
parsers/  →  NormalizedDocument
  ↓
chunking.py  →  parents (1200-3000 chars) + children (180-1200 chars, overlap 80)
  ↓
ingestion.py
  ↓
  ├─→ KnowledgeStore (sources.jsonl)        ← v1.0 兼容
  └─→ chunk store (chunks.jsonl + index.meta.json)
  ↓
index.py
  ↓
BM25 检索 (scope filter → lexical → scope boost)
  ↓
search_chunks → read_parent → 父级上下文
  ↓
knowledge.query (高层封装)
```

## 3. 支持的格式

| 格式 | 解析器 | 依赖 | 备注 |
|---|---|---|---|
| `md` / `markdown` | `parsers/md.py` | 无 | 标题保留，CRLF → LF 归一化 |
| `txt` | `parsers/txt.py` | 无 | 段落分块，无章节推断（**不**伪造标题） |
| `html` / `htm` | `parsers/html.py` | `beautifulsoup4` | h1-h6 → `#`/`##`/`###`；表格、列表、code 块 |
| `docx` | `parsers/docx.py` | `python-docx` | Heading 1/2/3 样式 → `#`/`##`/`###` |
| `pdf` | `parsers/pdf.py` | `pdfplumber` | 文本型 PDF；扫描型 PDF 返回 `unsupported_ocr`，**不**做假解析 |

`md` / `txt` 的字节没有 magic bytes 标识；`import_file` 在调用方未传 `fmt` 时默认按 `md` 处理。

## 4. 标准化 Markdown (NormalizedDocument)

每种格式统一为：

```python
@dataclass
class NormalizedDocument:
    source_id: str
    title: str
    author: str
    edition: str
    source_type: str         # book / manual / rfc / project_doc / attachment
    scope: str               # global / workspace / session
    language: str
    format: str              # md / txt / html / docx / pdf
    normalized_markdown: str # 标准化后的 Markdown 正文
    metadata: dict
    warnings: list[str]
```

- 标题层级 (`#`/`##`/`###`) 是后续 `chunking` 的**结构边界**
- `author` / `edition` 仅在格式本身声明时填入，**不**从网络/外部库伪造

## 5. Source / Chunk 模型

```python
@dataclass
class KnowledgeSource:
    source_id, title, author, edition,
    source_type, scope, format, language,
    tags, enabled, created_at, metadata

@dataclass
class KnowledgeChunk:
    chunk_id, source_id,
    parent_chunk_id, chunk_type (parent | child),
    chapter, section, subsection,
    page_start, page_end, chunk_index,
    content,                # 原始正文（不混入人工前缀）
    index_text,             # title | chapter | section | tags | body
    token_count, metadata
```

`index_text` 用 `title | chapter | section | tags | body` 拼装，**body 保持原文**，不混入人工检索前缀。

## 6. 分块参数

| 参数 | 值 | 说明 |
|---|---|---|
| `CHILD_TARGET` | 600 | 目标中间值（400-800 chars 范围内） |
| `CHILD_MIN` | 180 | 最小长度 |
| `CHILD_MAX` | 1200 | 最大长度 |
| `CHILD_OVERLAP` | 80 | 子块间重叠 |
| `PARENT_MIN` | 1200 | 父块最小长度 |
| `PARENT_MAX` | 3000 | 父块最大长度 |

### 6.1 边界优先级

1. Markdown 标题 (`#`/`##`/...)
2. DOCX Heading 样式
3. HTML h1-h6
4. PDF 页码 (`<!-- page N -->`)
5. 段落、列表、定义、案例

### 6.2 保护块（**绝不**拆分）

- 代码块（` ``` ` 围栏）
- 表格
- 列表序列

### 6.3 父子块关系

- 每个 child 必须带 `source/title/chapter/section/page` metadata
- `parent_chunk_id` 指向父块
- 父块不带 `parent_chunk_id`（自身就是顶层）
- `read_parent(child_chunk_id)` 一次 API 调用即可拿到上下文

## 7. 作用域

| Scope | 用途 | 默认检索优先级 |
|---|---|---|
| `global` | 跨 workspace 共享 | 3（最低） |
| `workspace` | 当前 workspace 私有 | 2 |
| `session` | 一次性资料 | 1（最高） |

- 检索过滤顺序：`session > workspace > global`
- Scope boost（BM25 score × scope_boost）：`session=1.30, workspace=1.10, global=1.00`

## 8. 索引与评分

### 8.1 BM25 评分（v1.0.1 lexical backend）

```python
# 纯 Python BM25 over `index_text`
# 默认参数: k1=1.2, b=0.75
# scope_boost: session=1.30, workspace=1.10, global=1.00
final_score = lexical_score * scope_boost
```

### 8.2 score metadata（**不**可伪造）

```python
{
  "retrieval_backend": "local_bm25",
  "scoring": "bm25_v1",
  "scoring_version": "v1",
  "lexical_score_present": True,
  "semantic_score_present": False,
  "semantic_status": "not_enabled",
  "scope_priority": ["session", "workspace", "global"]
}
```

每个 hit 都带：
```python
{
  "lexical_score": float,    # 原始 BM25
  "semantic_score": None,    # 预留位
  "final_score": float,      # lexical * scope_boost
  "scope": str
}
```

**禁止 LLM 修改或补造 score**。`semantic_score=None` 显式标记当前未启用语义检索（v1.0.1 预留位）。

### 8.3 检索顺序

1. **scope/filter**（`scope` / `source_id` / `source_type` / `tags` / `chapter`）
2. **enabled-only**（disabled / deleted source 的 chunks 全部排除）
3. **lexical search**（BM25 over `index_text`）
4. **rerank**（scope boost）
5. **parent expansion**（`read_parent`）

## 9. 新增 Tools (v1.0.1)

| tool_id | 用途 | 风险 |
|---|---|---|
| `knowledge.import_file` | 导入文件 (md/txt/html/docx/text-pdf) | low |
| `knowledge.list_chunks` | 列出 chunks（filter by source_id / chunk_type） | low |
| `knowledge.search_chunks` | BM25 over child chunks | low |
| `knowledge.read_chunk` | 读单条 chunk content + metadata | low |
| `knowledge.read_parent` | 读父块（chapter/section 上下文） | low |
| `knowledge.reindex_source` | 从已有 source 重建 chunks | low |

保留 v1.0: `query` / `import_document` / `list_sources` / `read_source` / `disable_source` / `delete_source`（6 个）。

## 10. knowledge.query 高层封装

```
query_knowledge(query, workspace_id, top_k, filters)
  ↓
  Path 1: chunk store 有 enabled children
    → search_chunks(query, top_k)
    → 对每个 hit 调用 read_parent
    → 在每个 hit 上附 `parent_snippet`（父块前 200 字符）
    → 返回 {hits, source_count, source_summary, metadata}
  ↓
  Path 2: v1.0 store 有 enabled source（兼容 v1.0 路径）
    → store.query() 直接 token-overlap 搜索
  ↓
  Path 3: legacy loader (v0.7.1 fallback)
    → context.knowledge_loader.load_knowledge_context
```

这保证 v1.0 capability tests (41/41) **零回归**。

## 11. Tool count 变化

| 维度 | v1.0 | v1.0.1 |
|---|---|---|
| Capability layer enabled tools | 13 | **19**（+6） |
| 实际 catalog 总数 | 67 | **73**（+6） |
| 差异原因 | — | 6 个新 tool_ids 全部新增，**无**去重 |

**spec 预测 73**；**实际 73** ✓

## 12. 不变量

| 强制 | 说明 |
|---|---|
| **不伪造章节、页码、来源、分数** | 章节/页码来自 parser；分数来自 BM25 |
| **不把整本书直接塞进 LLM** | `search_chunks` 只返回 snippet；`read_chunk` / `read_parent` 按需展开 |
| **不删除 v1.0 兼容能力** | 6 个 v1.0 tool 全部保留；`query_knowledge` 三段 fallback |
| **scanned PDF 不做假解析** | 扫描型 PDF 返回 `unsupported_ocr` + `ok=False` |
| **不接真实设备** | 6 个 knowledge tool 全部 `real_device_access=False` |
| **不开 SSH/Telnet/SNMP/nmap** | 0 启用 |
| **config.push 永久禁止** | 0 触碰 |
| **planned 永不暴露** | topology / inspection / cmdb 仍是 `callable_by_llm=False` |
| **v0.7.1 capability tests 零回归** | 41/41 passed |
| **v0.7.1 capability tests 零回归** | 41/41 passed |
| **Runtime 主链** | 0 改动 |

## 13. 模块接入现状

| Module | service 函数 | 新增 v1.0.1 |
|---|---|---|
| `config_translation` | `translate_config()` | — |
| **`knowledge` (UPGRADED v1.0.1)** | v1.0 的 6 个 + 6 个新函数 | ✓ |
| `artifact` | list/read/diff/export | — |
| `review` | list_items/update_item | — |
| `topology` (planned) | — | — |
| `inspection` (planned) | — | — |
| `cmdb` (planned) | — | — |

## 14. 后续 (v1.0.x / v1.1)

| 版本 | 主题 |
|---|---|
| v1.0.x | embedding-based scoring（与 BM25 并存 / 互补） |
| v1.0.x | 前端 API 对齐（FastAPI 路由 / SSE 推送 chunk 命中） |
| v1.1 | 跨 workspace 知识联邦（按 visibility 策略） |
| v1.1 | 多模态：图片型 PDF（OCR via tesseract） |
