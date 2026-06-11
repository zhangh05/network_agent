# Retrieval Quality & Evaluation v1.0.2

> v1.0.2 在 v1.0.1 之上做**中文检索质量**与**评测体系**的硬升级。**不**新增业务能力，**不**新增 Tool，Tool count 仍为 **73**。
> Runtime 主链 0 改动；planned modules（topology / inspection / cmdb）仍 0 启用；无真实设备访问；不接 SSH / Telnet / SNMP / nmap；`config.push` 永久禁止。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DOCUMENT_INGESTION_BOOK_LIBRARY_V101.md](DOCUMENT_INGESTION_BOOK_LIBRARY_V101.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| 中文书籍/手册检索质量 | CJK 2-gram + 3-gram 混合分词 + 字段加权 BM25 |
| 中英文混合查询 | word tokens + CJK n-grams 同时生成 |
| 字段结构化权重 | title / chapter / section / tags > body |
| BM25 参数可调 | `KNOWLEDGE_BM25_K1` / `KNOWLEDGE_BM25_B` 环境变量 |
| 确定性查询扩展 | 静态网络缩写 ↔ 中英别名（**不**调 LLM） |
| 兄弟 chunk 去重 | 同源 + 高 Jaccard → 只保留最高分 |
| 可复现评测 | `scripts/evaluate_retrieval_v102.py` + `harness/fixtures/retrieval_eval_v102.json` |
| 强制门禁 | 4 项阈值（Recall@3 / MRR / no-hit precision / duplicate rate） |

## 2. 不变量（v1.0.2 强约束）

- **不**改 Runtime 主链（`agent/runtime/loop.py` 等 0 行变更）
- **不**新增 Tool；CapabilityRegistry 工具清单**不**变；Tool count = 73
- **不**启用 planned modules（topology / inspection / cmdb）
- **不**接真实设备；**不**开 SSH / Telnet / SNMP / nmap
- **不**启用 `config.push`
- **不**伪造命中、分数、章节、页码
- **不**隐藏查询扩展词（必须出现在 `metadata.query_expansions`）
- v1.0.1.1 ingestion 安全门控（路径白名单、archive bomb、read_source `callable_by_llm=False`）**不**回归

## 3. 中文检索优化

### 3.1 混合分词（mixed-mode tokenization）

```python
# agent/modules/knowledge/index.py

_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", re.UNICODE)
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+", re.UNICODE)


def _tokenize_words(s):
    """Word tokens: ASCII words only. 1-char CJK skipped (handled by n-grams)."""
    out = []
    for t in _WORD_RE.findall(str(s or "")):
        if _is_cjk_char(t):
            continue
        out.append(t.lower())
    return out


def _cjk_ngrams(s, ns=(2, 3)):
    """CJK n-grams: 2-gram + 3-gram sliding window over CJK runs."""
    out = []
    for run in _CJK_RUN_RE.findall(str(s or "")):
        for n in ns:
            if len(run) < n:
                continue
            for i in range(0, len(run) - n + 1):
                out.append(run[i:i + n])
    return out


def _tokenize_mixed(s, ns=(2, 3)):
    """Mixed mode: word tokens + CJK n-grams."""
    return _tokenize_words(s) + _cjk_ngrams(s, ns)
```

**v1.0.2 关键决定**：
- **不**导 1-字 CJK token（`的`、`不` 等高频单字会带来大量噪声）
- CJK 2-gram + 3-gram 让"开放式最短路径优先" → `["开放", "放式", "式最", "最短", "路径", ...]` + `["开放式", "放式最", "式最短", "最短路", ...]`，**无字典**也能匹配中文词界
- ASCII 单词（`OSPF`, `BGP`）保留为单 token

### 3.2 字段加权 BM25

```python
DEFAULT_FIELD_WEIGHTS = {
    "title": 2.0,
    "chapter": 1.5,
    "section": 1.2,
    "tags": 1.2,
    "body": 1.0,
}
```

| 字段 | 权重 | 说明 |
|---|---|---|
| `title` | 2.0 | 文档名 / 标题 |
| `chapter` | 1.5 | H1（章节） |
| `section` | 1.2 | H2（小节） |
| `tags` | 1.2 | 标签 |
| `body` | 1.0 | 正文（基线） |

实现方式：把每个字段的 token 按权重 `repeat`（`n_repeat = max(1, int(round(w)))`）。这样 `title` 里的 OSPF 2 倍权重，BM25 长度归一化属性不破坏（所有字段贡献累加到同一个 doc length）。

**v1.0.2 调参过程**：原版用 `{4.0, 3.0, 2.0, 2.0, 1.0}`，但发现 title 权重过高导致 OSPF 书（标题"OSPF 完全手册"）的"完全"2-gram 让所有 OSPF query 都偏向这本书。**降**到 `{2.0, 1.5, 1.2, 1.2, 1.0}` 平衡了 title 优势与正文匹配。

### 3.3 可配置 BM25

```python
def _get_bm25_k1():
    return float(os.environ.get("KNOWLEDGE_BM25_K1", "1.2"))

def _get_bm25_b():
    return float(os.environ.get("KNOWLEDGE_BM25_B", "0.75"))
```

| 参数 | 默认值 | 环境变量 | 含义 |
|---|---|---|---|
| `k1` | 1.2 | `KNOWLEDGE_BM25_K1` | term frequency saturation |
| `b` | 0.75 | `KNOWLEDGE_BM25_B` | document length normalization |

### 3.4 Score metadata

每次 `search_chunks` 返回的 `metadata` 包含：

```python
{
  "retrieval_backend": "local_bm25",
  "scoring": "bm25_v1_field_weighted",
  "scoring_version": "v1_bm25_field_weighted",
  "tokenizer_version": "v1_cjk_ngram",
  "lexical_score_present": True,
  "semantic_score_present": False,
  "semantic_status": "not_enabled",
  "scope_priority": ["session", "workspace", "global"],
  "workspace_id": "<ws>",
  "query_expansions": [{"term": "OSPF", "added": ["开放式最短路径优先", ...]}],
  "deduplicated_count": <int>,
  "pre_dedup_count": <int>,
  "min_score_threshold": 0.5,
  "min_filtered": <int>,
  "body_filtered": <int>,
}
```

每个 hit 携带：
```python
{
  "lexical_score": <float>,   # 原始 BM25
  "semantic_score": None,     # 预留位（v1.0.1.1 起明确：未启用 semantic retrieval）
  "final_score": <float>,     # lexical * scope_boost
  "scope": "workspace",
}
```

## 4. 确定性查询扩展

**不**调用 LLM。**不**改写用户查询。**只**在 BM25 评分时**额外**增加扩展词的 token。

```python
QUERY_EXPANSIONS: dict = {
    "ospf": ["开放式最短路径优先", "open shortest path first"],
    "开放式最短路径优先": ["ospf"],
    "bgp": ["边界网关协议", "border gateway protocol"],
    "边界网关协议": ["bgp"],
    "dr": ["designated router", "指定路由器"],
    "bdr": ["backup designated router", "备份指定路由器"],
    "邻居": ["neighbor", "neighbour", "邻接"],
    "邻接": ["neighbor", "neighbour", "邻居"],
    "neighbor": ["邻居", "邻接"],
    "lsa": ["link state advertisement", "链路状态通告"],
    # ... ~60 项
}
```

**示例**：用户 query `"OSPF 邻居"` 扩展为 `"OSPF 邻居 designated router 指定路由器 neighbor neighbour 邻接 link state advertisement 链路状态通告 ..."`。扩展词在 BM25 评分时加权，但不作为命中的**直接证据**（仅作匹配增强）。

**强制约束**：
- **所有**扩展词必须出现在 `metadata.query_expansions`（`{"term": "OSPF", "added": [...]}` 形式）
- 扩展词**不**伪造章节 / 页码 / 分数
- 英文 key 用 word-boundary match；CJK key 用 substring match

## 5. 结果去重（兄弟 chunk）

```python
def _dedupe_sibling_chunks(hits, jaccard_threshold=0.85):
    """Drop near-duplicate siblings from the same source.
    
    Cross-source / cross-chapter hits are NEVER deduped (independent evidence).
    Returns (deduped_hits, deduplicated_count).
    """
```

规则：
- 同一 `source_id` 才考虑去重
- Jaccard(content) ≥ 0.85 → 视为兄弟（重复）
- 同一 `parent_chunk_id` 的 child，Jaccard ≥ 0.95 → 视为兄弟
- 只保留**最高分**那条
- `metadata.deduplicated_count` 记录被丢弃的条数

**跨章节 / 跨源**永远不去重（独立证据）。

## 6. 检索流水线（v1.0.2 完整版）

```
search_chunks(workspace_id, query, top_k, scope, source_id, ...)
  │
  ├─ 1. _expand_query(query) → (expanded_query, expansions_meta)
  │
  ├─ 2. filters:
  │     - enabled-only (KnowledgeStore 排除 disabled / deleted)
  │     - scope (session / workspace / global)
  │     - source_id, source_type, chapter, tags
  │
  ├─ 3. BM25Index.fit(children)
  │     - field-weighted tokenization (title / chapter / section / tags / body)
  │     - mixed-mode: word tokens + CJK 2-gram + 3-gram
  │
  ├─ 4. BM25Index.score(expanded_query)
  │     - scope boost: session 1.30, workspace 1.10, global 1.00
  │     - pull top (top_k * 3) for dedup headroom
  │
  ├─ 5. _dedupe_sibling_chunks(raw_hits)  # Jaccard dedup
  │
  ├─ 6. min_score filter  (MIN_FINAL_SCORE=0.5, env overridable)
  │
  ├─ 7. body filter  # 原始 query token 必须命中 body 至少 1 个
  │
  └─ 8. slice [:top_k]  → final hits
```

`body filter` 设计意图：避免仅依赖 title 字段权重导致"OSPF 完全手册"对**任何**包含"完全"的 query 都返回。原始 query token（不是扩展 token）必须至少 1 个出现在 body。

## 7. H3 子章节支持（chunking.py）

v1.0.1 chunker 把 `### H3` 当成 body 文本，导致 "1.1 OSPF 简介" 这种三级标题**不**会出现在 chunk metadata。

v1.0.2 更新 `_split_into_sections()`：
- H1 → chapter
- H2 → section
- H3 → subsection

`_make_parents` / `_make_children` 把 `subsection` 写进 chunk metadata。`KnowledgeChunk.subsection` 字段在 hit dict 中作为 `subsection` key 暴露。

## 8. 评测体系

### 8.1 Fixtures

`harness/fixtures/retrieval_eval_v102.json` — 5 个文档 + 15 个查询：

| 文档 | scope | 用途 |
|---|---|---|
| `ospf_book_zh` (《OSPF 完全手册》) | workspace | 中文 + 英文混合 OSPF 内容 |
| `bgp_book_zh` (《BGP 协议详解》) | workspace | BGP + community + 路由策略 |
| `switching_book_zh` (《园区交换网络基础》) | workspace | VLAN + STP |
| `nat_ppt_zh` (《NAT 技术概览》) | session | NAT（session scope 隔离测试）|
| `rfc2328_en` (RFC 2328 节选) | global | 英文 RFC（global scope 隔离测试）|

15 个查询覆盖：
- 中文精确查询（"OSPF 协议"、"VLAN 是什么"、"生成树"、"网络地址转换"）
- 英文缩写查询（"OSPF"、"BGP"）
- 中文扩展查询（"开放式最短路径优先"、"BGP 团体属性"）
- 中英文混合查询（"OSPF 邻居"、"OSPF link state"）
- 章节标题命中（"DR 与 BDR"）
- 正文同义词命中（"链路状态通告" → LSA）
- 无命中（"完全不相关的查询 xyzqqq"）
- scope 隔离（global RFC 2328 英文）
- source_id 过滤（`filter_source_id="ospf_book_zh"`，eval 解析为真 source_id）
- 重复 chunk 去重（"OSPF 链路状态"）

### 8.2 评测脚本

`scripts/evaluate_retrieval_v102.py`：
1. 创建临时 workspace（`WS_ROOT=<tmpdir>`）
2. 依次 `import_file` 5 个 fixture 文档
3. 对每个 query 调用 `search_chunks`
4. 判定 hit 是否匹配：`source_id` 一致 **AND** 至少 1 个 `expected_chapter_substrings` 出现在 `chapter` / `section` / `subsection` / `title`
5. 计算指标
6. `--quiet` 时 stdout 输出 JSON 报告（parseable）
7. **退出码 0** = all_pass；**退出码 1** = 任一阈值未达

### 8.3 指标

| 指标 | 定义 | 阈值 |
|---|---|---|
| **Recall@1** | top-1 hit 是预期文档+章节的比例 | ≥ 0.70 |
| **Recall@3** | top-3 hits 中任一匹配的比例 | **≥ 0.85** |
| **Recall@5** | top-5 hits 中任一匹配的比例 | ≥ 0.92 |
| **MRR** | 倒数排名的平均 | **≥ 0.75** |
| **no_hit precision** | `expected_doc_id=null` 的 query 中 0 命中的比例 | **= 1.0** |
| **duplicate rate** | `deduplicated_count / pre_dedup_count` 的均值 | **≤ 0.20** |

### 8.4 当前结果（v1.0.2 封版）

```
n_queries = 15
n_documents = 5
metrics:
  recall_at_1    = 0.7333
  recall_at_3    = 0.8667   ✓ ≥ 0.85
  recall_at_5    = 0.9333
  mrr            = 0.8167   ✓ ≥ 0.75
  no_hit_precision = 1.0    ✓ = 1.0
  duplicate_rate = 0.0      ✓ ≤ 0.20

passes:
  recall_at_3        = true
  mrr                = true
  no_hit_precision   = true
  duplicate_rate_max = true
all_pass = true
```

## 9. 测试

`harness/test_retrieval_quality_v102.py` — 19 个测试：

| # | 测试 | 覆盖 |
|---|---|---|
| 1-3 | `TestTokenization` | CJK 2/3-gram + 英文 word + 混合模式 |
| 4-5 | `TestFieldWeights` | 默认权重 + title > body |
| 6-7 | `TestBM25Configurability` | `KNOWLEDGE_BM25_K1` / `B` env 覆盖 |
| 8 | `TestQueryExpansion` | OSPF / BGP / 邻居 / 不相关 |
| 10-11 | `TestMetadataSurfacing` | `tokenizer_version` / `scoring_version` / `query_expansions` |
| 12-13 | `TestSiblingDedup` | 同源去重 + 跨源不破坏 |
| 14 | `TestNoHitPrecision` | 随机 query 不伪造 |
| 15 | `TestToolCountV102` | Tool count = 73 |
| 16 | `TestPlannedStillNotVisibleV102` | topology / inspection / cmdb 仍 0 可见 |
| 19 | `TestEvalGate` | **运行 `evaluate_retrieval_v102.py` 并断言 4 项阈值通过** |

`TestEvalGate` 是**门禁测试**：以子进程跑 `scripts/evaluate_retrieval_v102.py --quiet`，解析 JSON，断言所有阈值 pass，否则 pytest 失败。

## 10. 强制约束再确认

| 约束 | 状态 |
|---|---|
| Runtime 主链 0 改动 | ✓ `agent/runtime/loop.py` 等无修改 |
| Tool count = 73 | ✓ CapabilityRegistry 工具清单无变化 |
| 0 新增 Tool | ✓ v1.0.1.1 = 73 → v1.0.2 = 73 |
| planned 仍 0 可见 | ✓ `TestPlannedStillNotVisibleV102` |
| 不接真实设备 | ✓ knowledge capability `real_device_access=False` |
| 不开 SSH / Telnet / SNMP / nmap | ✓ 0 启用 |
| `config.push` 永久禁止 | ✓ 0 触碰 |
| 不伪造命中 / 分数 / 章节 / 页码 | ✓ 章节来自 parser；分数来自 BM25；无 hits → `source_summary=[]` |
| 不隐藏查询扩展 | ✓ 全部写在 `metadata.query_expansions` |
| v1.0.1 ingestion 22 tests | ✓ 零回归 |
| v1.0.1.1 security 16 tests | ✓ 零回归 |
| v1.0 knowledge store 29 tests | ✓ 零回归 |

## 11. 后续 (v1.0.x / v1.1)

| 版本 | 主题 |
|---|---|
| v1.0.x | embedding-based scoring（与 BM25 并存 / 互补；`semantic_score` 从 null 变 float） |
| v1.0.x | 扩展 fixture 语料（≥ 20 文档、≥ 50 query），引入 cross-source 排序难度 |
| v1.0.x | 前端 API 对齐（FastAPI 路由 / SSE 推送 chunk 命中） |
| v1.1 | 跨 workspace 知识联邦（按 visibility 策略） |
| v1.1 | 多模态：图片型 PDF（OCR via tesseract） |
