# Network Agent — Release History

> 完整版本演化表（v0.6 → v0.7.1）。
> README 中的"Version Evolution"是本表的摘要。
> 配套：[README.md](../README.md) · [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) · [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## 主线阶段

| 阶段 | 版本区间 | 主题 |
|------|---------|------|
| Runtime 底座 | v0.6 ~ v0.6.3 | Codex-style Runtime 替换旧 LangGraph 7-node |
| Capability Layer | v0.7 ~ v0.7.1 | config_translation / knowledge_query 接入；artifact / source 质量对齐 |

## 完整版本表

| Commit | Version | Title | Key Changes | Runtime 主链 |
|--------|---------|-------|-------------|--------------|
| `f45c3053` | v0.6 | rewrite backend around codex-style runtime | 删除 `agent/graph.py` + `agent/nodes/*` 主链，迁入 `agent/legacy/`；新增 `agent/{app,core,runtime,protocol,context,tools,skills,modules,audit}/`；新增 `POST /api/agent/message`；15 tests | **重写** |
| `569982a8` | v0.6 | finalize codex-style runtime | 修复 `agent.legacy` 动态导入路径；更新 harness 路径；新增 [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) | 稳定化 |
| `e5487212` | v0.6.1 | stabilize codex-style runtime | 注册 `/api/agent/message` 路由；`AgentResult.to_dict()` 补 `events` 字段；新增 25 tests | **不变** |
| `bf555a0a` | v0.6.2 | stabilize rate limit and provider timeout | 修复 `RATE_LIMIT_DISABLED` 跨测试污染；URLError timeout 归类为 `provider_timeout`，`retryable=True`；中文友好超时；新增 16 tests | **不变** |
| `2ae76bcb` | v0.6.3 | harden runtime tool routing | `default_runtime_services` 构建真实 `ToolRouter`；`llm_name_map` 白名单（未知 tool → `tool_call_failed`）；`RuntimeSnapshot` 区分 `total_tool_count` / `visible_tool_count`；System prompt 升级为 Runtime Contract；新增 20 tests | **不变** |
| `ff6cff5d` | v0.7 | integrate config translation and knowledge capabilities | 接入 `config_translation.translate_config` 与 `knowledge.query`；Tool 数 55 → **57**；`topology` / `inspection` / `cmdb` 仍 planned；新增 21 tests | **不变** |
| `15565d18` | v0.7.1 | enrich capability artifacts and sources | `translated_config` 保存为 artifact（`authoritative=false, deployable_config=false`）；`manual_review_items` 结构化；knowledge `source_summary`（≤200 字符，无伪造）；`AgentResult.tool_calls` 增强；`ToolResultMessage.content` 1000 → 2000 字符；新增 20 tests | **不变** |
| `0d160ce` | v0.7.1 sync | docs baseline sync (README + ARCHITECTURE + CAPABILITY_LAYER_V071 + RELEASE_HISTORY) | 文档基线同步到 v0.7.1；新增 `docs/CAPABILITY_LAYER_V071.md` | **不变** |
| `1c9f89b` | v0.7.1 align | align legacy provider timeout diagnostics assertion | 修复 v0.5 `test_timeout_returns_provider_timeout` 断言（accept "timeout" / "timed out" 两种 wording，主断言 `metadata.provider_error_type == "provider_timeout"`）；新增 wording-agnostic regression test | **不变** |
| TBD (v0.8) | v0.8 | introduce capability manifest registry | 新增 `agent/capabilities/{schemas,registry,builtin}.py` + 5 个 module `capability.py`；`CapabilityRegistry` 作为能力真相源；`ModuleRegistry.from_capabilities()` / `SkillRegistry.from_capabilities()` / `ToolRegistry.register_capability_tools()`；`RuntimeServices.capability_registry` 字段；`RuntimeSnapshot.build_runtime_snapshot()` 优先从 CapabilityRegistry 投影；`planned` 三个 capability 仍 `NOT callable`；Tool count 仍 = 57；新增 20 tests | **不变** |
| TBD (v0.8.1) | v0.8.1 | add skill selector and dynamic tool visibility | 新增 `agent/skills/selector.py`（`SkillSelector` + `select_skills` rule-based API：assistant_chat always-on + intent_patterns 命中 + capability_discovery meta-skill + planned 绝不注入 + 异常 fallback）；`ToolRouter.apply_dynamic_visibility()`（fail-closed 交集 = `registry_visible ∩ allowed_tool_ids`）；`RuntimeServices.skill_selector` 字段；`ContextBuilder` 每轮调用 selector + 同步 router + 异常 fallback；`RuntimeSnapshot.selected_skills` / `selected_visible_tools` / `dynamic_tool_visibility` 新字段 + `to_prompt_text()` 新增 per-turn 段落；新增 23 tests | **不变** |
| TBD (v0.8.2) | v0.8.2 | standardize result contracts | 新增 `agent/protocol/module_result.py`（`ModuleResult` 业务输出合同 + `success`/`failure`/`to_dict`/`from_dict`）；`ToolResult` 升级为含 `data` / `artifacts` / `source_count` / `manual_review_count` 字段；`ToolResult.from_module_result` / `from_legacy_dict`（运行时合同）；`config_translation.service.to_module_result` / `knowledge.service.to_module_result`（service 适配）；`config_translation.tools` / `knowledge.tools` 改用 `to_module_result` + `from_module_result`（tool handler 适配）；`agent/runtime/loop.py::_to_standard_tool_call`（审计 / UI 合同：10 标准字段，缺失填默认）；`AgentResult.tool_calls` 严格 10 字段；v0.7.1 业务输出合同不变；新增 28 tests | **不变** |
| TBD (v0.9) | v0.9 | add artifact consumption and review flow | 新增 `agent/modules/artifact/`（`service` + `tools` + `capability`）— 4 tools: list/read/diff/export；新增 `agent/modules/review/`（`service` + `tools` + `capability`）— 2 tools: list_items/update_item；2 个 enabled skills: `artifact_management` / `review_flow`；`review.update_item` 写 sidecar JSON 存 status/user_note，**不**修改 translated_config 原文，**不**生成 deployable_config；`agent/capabilities/builtin.py` 加入 artifact + review；Tool count 57 → 62（+5：`artifact.list` 与已有 ToolRuntime catalog 去重）；`artifacts.schemas.ArtifactRecord.as_dict()` 修复 metadata 持久化（v0.9 配套小修复）；v0.7.1 capability tests 41/41 零回归；新增 29 tests | **不变** |
| TBD (v1.0) | v1.0 | add knowledge store management | 新增 `agent/modules/knowledge/store.py`（KnowledgeStore：JSONL + thread-lock + atomic write；workspace 隔离；不依赖外部 DB）；新增 5 个 knowledge tool：import_document / list_sources / read_source / disable_source / delete_source；保留 `knowledge.query`（现由 KnowledgeStore 驱动，store 无内容时 fallback 到 v0.7.1 legacy loader）；token-overlap scoring（不要求向量库）；`source_summary` snippet ≤ 200 字符，无 hits → `[]`（**不**伪造）；caller 传本地路径 → redact 为 `redacted-local-path`；v0.7.1 capability tests 41/41 零回归；Tool count 62 → 67（+5）；新增 29 tests | **不变** |
| TBD (v1.0.1) | v1.0.1 | add document ingestion and book library | 新增 `agent/modules/knowledge/parsers/` (md / txt / html / docx / text-pdf；扫描型 PDF → `unsupported_ocr`)；`chunking.py`（结构优先 + 保护块 + 父子分块；child 180-1200 chars / overlap 80；parent 1200-3000 chars）；`index.py`（纯 Python BM25 + scope boost + scope 优先级）；`ingestion.py`（file → NormalizedDocument → Source + chunks）；`schemas.py`（NormalizedDocument / KnowledgeSource / KnowledgeChunk）；新增 6 个 knowledge tool：import_file / list_chunks / search_chunks / read_chunk / read_parent / reindex_source；`knowledge.query` 改为 3 段 fallback：chunk→v1.0 store→legacy loader；Tool count 67 → 73（+6）；v0.7.1 capability tests 41/41 零回归；新增 22 tests | **不变** |
| TBD (v1.0.1.1) | v1.0.1.1 | fix knowledge ingestion boundaries and test gate | `import_file` 路径白名单 `workspace/{ws_id}/{uploads,inbox}/`；拒绝 `..` / 符号链接逃逸 / 文件不存在 / > 50MB / DOCX archive bomb（archive_too_large 错误码）；`knowledge.read_source` `callable_by_llm=False`（LLM 只能 `list_sources` / `search_chunks` / `read_chunk` / `read_parent`；backend 仍可调用，给 `reindex_source` / admin 工具用）；`tags` schema 统一为 `array[string]`（import_file / search_chunks）；文档术语统一为 **BM25 lexical retrieval + scope boost + parent expansion**（**不**再称 hybrid retrieval）；2 个 live-LLM 测试 (`test_tools_question_uses_snapshot`, `test_knowledge_query_handles_no_data`) 改为 `RUN_LIVE_TESTS=1` 才执行，默认 skip；Tool count 仍 73（**无**新增工具）；focused regression **failed=0**；新增 16 tests | **不变** |
| TBD (v1.0.2) | v1.0.2 | improve retrieval quality and evaluation | **CJK 2-gram + 3-gram 混合分词**（`agent/modules/knowledge/index._cjk_ngrams` / `_tokenize_mixed`；1-字 CJK token 跳过）；**字段加权 BM25**（`DEFAULT_FIELD_WEIGHTS = {title: 2.0, chapter: 1.5, section: 1.2, tags: 1.2, body: 1.0}`；`_tokenize_weighted` 用 `n_repeat = max(1, int(round(w)))` 实现）；`KNOWLEDGE_BM25_K1` / `KNOWLEDGE_BM25_B` 环境变量可调；**确定性查询扩展**（`QUERY_EXPANSIONS` 静态 dict ~60 项：OSPF↔开放式最短路径优先 / BGP↔边界网关协议 / DR / BDR / 邻居 / 邻接 / community / 路由策略 / LSA / 链路状态通告 / SPF / Dijkstra 等；**不**调 LLM；**全部**记入 `metadata.query_expansions`）；**兄弟 chunk 去重**（`_dedupe_sibling_chunks`；Jaccard(content) ≥ 0.85 + 同 `source_id` → 只保留最高分；跨源 / 跨章节**不**去重；`metadata.deduplicated_count`）；**H3 子章节入 metadata**（`chunking._split_into_sections` H3 → `subsection`；`KnowledgeChunk.subsection` 字段；hit dict 增加 `subsection`）；**Body filter**（原始 query token 必须 ≥ 1 个在 body；避免 title-only 噪声）；`MIN_FINAL_SCORE=0.5`（env `KNOWLEDGE_MIN_FINAL_SCORE`）；metadata 新增 `tokenizer_version=v1_cjk_ngram` / `scoring_version=v1_bm25_field_weighted` / `query_expansions` / `deduplicated_count` / `pre_dedup_count` / `min_score_threshold` / `min_filtered` / `body_filtered` / `lexical_score` / `final_score`；**新增评测体系**：`harness/fixtures/retrieval_eval_v102.json`（5 文档 / 15 查询 / 4 项阈值）+ `scripts/evaluate_retrieval_v102.py`（`--quiet` stdout JSON 报告；exit 0 iff all_pass）+ `harness/test_retrieval_quality_v102.py`（19 测试，含 1 个子进程门禁）。**当前结果**：Recall@1=0.7333 / Recall@3=0.8667（≥0.85）/ Recall@5=0.9333 / MRR=0.8167（≥0.75）/ no_hit_precision=1.0（=1.0）/ duplicate_rate=0.0（≤0.20）；Tool count 仍 73（**无**新增工具）；v1.0.1.1 / v1.0.1 / v1.0 零回归；Runtime 主链 0 改动；新增 19 tests | **不变** |
| TBD (Frontend v1.0) | Frontend v1.0 | rewrite capability-driven agent workbench | **仅**改 `frontend/`，后端 0 改动。技术栈：**React 18** + **TypeScript 5 strict** + **Vite 5** + **React Router 6** + **Zustand 4** + **Axios** + **Vitest 2** + **@testing-library/react 16** + **happy-dom 15**。**不**引入 Material-UI / Ant Design / Chakra 等大型 UI 框架；**不**硬编码 Tool count / capability 状态。**目录**：`frontend/src/{app,api,types,stores,layouts,components,pages,styles,test}/` + `frontend/legacy/index.html.legacy`（legacy 备份，**不**继续扩展；not served by Vite）。新 `frontend/index.html` = Vite root（`<div id="root">` + `/src/main.tsx`）。**三栏布局**：左 Workspace/Sessions/Runs · 中 7 个 page · 右 Turn Inspector（collapsible）。**7 page**：`/workbench` `/knowledge` `/artifacts` `/reviews` `/capabilities` `/audit` `/settings`。**9 TS 类型**（`AgentResult` / `ToolCallResult` / `RuntimeEvent` / `Artifact` / `ReviewItem` / `KnowledgeSource` / `KnowledgeChunk` / `CapabilityManifest` / `ApiError`）严格映射后端 `as_dict()`；**不**在组件中猜字段。**10 axios API 模块**（agent / sessions / workspaces / capabilities / tools / knowledge / artifacts / reviews / runtime_audit / settings），错误统一转 `ApiError`。**4 个 Zustand store**（session / UI / workbench / toast）。**planned capability 不**渲染调用按钮；Tool Catalog 移到 `/audit` 下的开发者区域。**样式**：Vanilla CSS + CSS variables（light/dark）；等宽字体用于 code / pre / config / diff；状态色：warning / error / review 统一调色板。**10 个 Vitest 测试文件**（`frontend/src/test/*.test.tsx`）覆盖 10 类断言（agentResult / toolCalls / artifactCard / sourceSummary / reviewItem / plannedCapability / apiError / emptyState / sessionSwitch / inspectorToggle）。**Gates**：`npm run typecheck` ✓ · `npm run build` ✓ · `npm test` ✓ (13/13)。**Alignment**：`harness/test_frontend_backend_alignment.py` 更新为 v1.0 + 保留 legacy 检查；37/37 passed。后端 0 改动；Tool count 仍 73（**无**新增工具）；planned (topology / inspection / cmdb) 仍 0 可见；不接真实设备；不开 SSH/Telnet/SNMP/nmap；`config.push` 永久禁止；v1.0.2 / v1.0.1.1 / v1.0.1 / v1.0 / v0.9 / v0.8.2 / v0.8.1 / v0.8 / v0.7-v0.7.1 零回归；新增 13 tests + 37 alignment = 50 tests。详见 [FRONTEND_V1.md](FRONTEND_V1.md) | **不变** |
| TBD (Frontend v1.0.1) | Frontend v1.0.1 | integrate real backend api and e2e | **仅**改 `frontend/` + 后端**仅**薄包装 `backend/api/review_routes.py`（**不**新增 Tool）。10 个 API 模块（agent / sessions / workspaces / capabilities / tools / knowledge / artifacts / reviews / runtime_audit / settings）按**真实后端合同**对齐：修正 `/agent/message`、`/knowledge/sources/from-artifact`（JSON body，**不**是 multipart）、`/knowledge/search`（返回 `results[]` 不是 `hits`）、`/knowledge/chunks`（返回 `safe_excerpt` 不是 `content`）、`/review-items`（**新增** workspace-level list + PUT with `?workspace_id=&artifact_id=` query）。错误统一转 `ApiError`（覆盖 `timeout` / `network` / `parse` / `http_4xx` / `http_5xx` / `aborted` 6 类 + 透传 `request_id` 来自 `X-Request-Id` header）。Agent failure 路径**新增 stub AgentResult**（`{ok:false, turn_id:'turn-<ts>', trace_id:<request_id>, errors:[...]}`），保证 LLM 离线时 Inspector 仍可见。Sidebar session：创建 / 切换 / 归档 全部接通。Knowledge Library：import-from-artifact 真实接通（select → JSON POST → toast）。Review modal：PUT 不改原 artifact。**部署**：`VITE_API_BASE` 环境变量（生产 build 时注入，默认同源 `/api`）+ `VITE_DEV_API_TARGET`（dev proxy，默认 `http://127.0.0.1:8010`）；生产 build 输出 `dist/`，可由 FastAPI 或独立静态服务托管。**E2E**：`@playwright/test@1.60` + `playwright.config.ts` + `e2e/global-setup.ts`（验证 backend 可达）+ `e2e/fixtures.ts`（共享 api context）+ 10 个 spec：`01-health` `02-agent-message` `03-session-lifecycle` `04-knowledge-upload` `05-knowledge-search` `06-artifact-view` `07-review-status` `08-planned-no-button` `09-timeout-error`（`page.route` 拦截 + 强制 20s 延时触发 12s client timeout）`10-refresh-restore`。**Gates**：`npm run typecheck` ✓ · `npm run build` ✓ (264 kB JS / 10 kB CSS) · `npm test` ✓ (13/13 Vitest) · `npm run e2e` ✓ (10/10 Playwright) · `pytest` focused regression ✓ (152/152 backend + 37/37 alignment)。后端**仅**薄包装 review_routes.py（GET /api/workspaces/<ws>/review-items + PUT /api/review-items/<id>），**不**新增 Tool，Tool count 仍 73；planned 仍 0 可见；不接真实设备；不开 SSH/Telnet/SNMP/nmap；`config.push` 永久禁止；v1.0 + v1.0.2 / v1.0.1.1 / v1.0.1 / v1.0 / v0.9 / v0.8.2 / v0.8.1 / v0.8 / v0.7-v0.7.1 零回归。详见 [FRONTEND_API_E2E_V101.md](FRONTEND_API_E2E_V101.md) | **不变** |

## 各版本能力对照

| 能力 | v0.6 | v0.6.1 | v0.6.2 | v0.6.3 | v0.7 | v0.7.1 |
|------|------|--------|--------|--------|------|--------|
| Codex-style Runtime | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/api/agent/message` | ✓ | ✓ 注册 | ✓ | ✓ | ✓ | ✓ |
| AgentResult.events | partial | ✓ | ✓ | ✓ | ✓ | ✓ |
| Runtime 稳定性 (rate limit / provider timeout) | — | — | ✓ | ✓ | ✓ | ✓ |
| ToolRouter 真实 catalog | — | — | — | ✓ | ✓ | ✓ |
| `llm_name_map` 白名单 | — | — | — | ✓ | ✓ | ✓ |
| System prompt = Runtime Contract | — | — | — | ✓ | ✓ | ✓ |
| `config_translation.translate_config` | — | — | — | — | ✓ | ✓ |
| `knowledge.query` | — | — | — | — | ✓ | ✓ |
| `translated_config` artifact (authoritative=false) | — | — | — | — | — | ✓ |
| `manual_review_items` 结构化 | — | — | — | — | — | ✓ |
| `source_summary` (≤200 字符) | — | — | — | — | — | ✓ |
| `AgentResult.tool_calls` 增强 | — | — | — | — | — | ✓ |
| `ToolResultMessage.content` 2000 字符 | — | — | — | — | — | ✓ |
| **Tool count** | 55 | 55 | 55 | 55 | **57** | **57** |

## 各版本安全边界

v0.6 → v0.7.1 **始终保持**：

- **No real device access**（无 SSH / Telnet / SNMP / nmap / ping sweep）
- **`config.push` 永久禁止**
- **No authoritative deployable_config**（v0.7.1 起写入 artifact metadata）
- **Tool execution centralization**（ToolRouter → ToolRuntimeClient）
- **planned modules (topology / inspection / cmdb) NOT callable**（v0.7+ 显式）

## 不变量（v0.6 → v0.7.1 一致）

1. **Runtime 主链调用路径**：`API → AgentApp → AgentThread → AgentSession → AgentTurn → RuntimeLoop → invoke_llm`
2. **工具执行唯一入口**：`ToolRouter → ToolRuntimeClient`，不绕过 ToolPolicy / ToolExecutor / Redaction / Audit
3. **Tool 名称映射**：`. ↔ __`，由 `ToolRouter.llm_name_map` 集中维护
4. **高危工具白名单 + approval_id 鉴权**
5. **planned 模块永不注入、永不允许 LLM 调用**
6. **`config.push` 永久禁止**（无对应 tool、ToolRuntime regex 拦截）

## 测试基线（2026-06-10，developer machine）

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| v1.0.1.1 ingestion security (focused) | **16** | 0 | 0 |
| v1.0.1 document ingestion (focused) | **22** | 0 | 0 |
| v1.0 knowledge store (focused) | **29** | 0 | 0 |
| v0.9 artifact / review flow (focused) | **29** | 0 | 0 |
| v0.8.2 result contract (focused) | **28** | 0 | 0 |
| v0.8.1 skill selector (focused) | **23** | 0 | 0 |
| v0.8 capability manifest (focused) | **20** | 0 | 0 |
| v0.7/v0.7.1 capability (focused) | **41** | 0 | 0 |
| v1.0.1 broader focused baseline | **744** | 7 | 0 |
| v1.0.1.1 security focused suite | **266** | 2 | 0 |
| Full harness `pytest harness -q` | — | — | Not re-run (docs + refactor) |

注 1：2 skipped = pre-existing live-LLM tests (`test_tools_question_uses_snapshot`, `test_knowledge_query_handles_no_data`) 在 v1.0.1.1 中加了 `RUN_LIVE_TESTS=1` gate。**默认环境 skipped = 0 failed**。

注 2：744 与 266 是**两次不同筛选范围**的 focused 套件，**不**是同一 baseline 的演进。直接对比二者无意义。

> 2026-06-10 update：曾记录的 v0.5 `test_llm_provider_diagnostics_v05.py::test_timeout_returns_provider_timeout` 失败已在同日的 legacy diagnostics alignment 中修复（断言改为兼容 "timeout" / "timed out" 两种文案，并主断言 `metadata.provider_error_type == "provider_timeout"`）。broader focused regression 由 613 passed / 1 failed 提升至 **615 passed / 0 failed**（+1 = 新增的 wording-agnostic regression test）。

> 完整说明见 [README.md §"Test Baseline"](../README.md)。
