# Network Agent

Network Agent 是一个网络工程本地 Agent 平台，面向网络工程师提供配置翻译、知识检索等 AI 驱动的网络运维能力。平台基于 Codex-style Agent Runtime (v0.6 底座 + v0.7.1 能力层)，以 Module / Skill / Tool 三层架构组织，统一入口端口 8010。

> **v1.0 — Knowledge Store Management**（当前基线）：把 `knowledge.query` 从"查询已有上下文 / loader"升级为**完整后端知识库能力**——新增 5 个 knowledge tool（`import_document` / `list_sources` / `read_source` / `disable_source` / `delete_source`）+ 保留 `knowledge.query`。**不**依赖外部数据库（纯 JSONL）；**不**伪造 source / score / citation；`source_summary` snippet ≤ 200 字符，无 hits 时返回 `[]`；**不**接真实设备。Tool count: **62 → 67**（+5）。详见 [docs/KNOWLEDGE_STORE_V10.md](docs/KNOWLEDGE_STORE_V10.md)。
>
> **v0.9 — Artifact Consumption & Review Flow**（前一基线）：新增 artifact + review capabilities。详见 [docs/ARTIFACT_REVIEW_FLOW_V09.md](docs/ARTIFACT_REVIEW_FLOW_V09.md)。
>
> **v0.8.2 — Result Contract Standardization**。
> **v0.8.1 — SkillSelector + Dynamic Tool Visibility**。
> 详见 [docs/CAPABILITY_MANIFEST_V08.md](docs/CAPABILITY_MANIFEST_V08.md) § 9 / § 10。

## Platform Runtime — Current Baseline

- **Agent Backend v1.0 — Knowledge Store Management**
- **HEAD**：(see git log — v1.0 feat(agent): add knowledge store management)
- **Runtime architecture**：Codex-style Agent Runtime (Thread / Session / Turn / RuntimeLoop)
- **Tool count**：**67** (v0.6.x: 55 → v0.7: 57 → v0.9: 62 → v1.0: 67，+5)
- **CapabilityRegistry (v0.8)**：5 个 capability (2 enabled + 3 planned)，是 Module/Skill/Tool Registry 和 RuntimeSnapshot 的**单一真相源**
- **v0.8.1 — SkillSelector + Dynamic Tool Visibility**：
  - 每轮 `SkillSelector.select(user_message)` 决定本轮 selected_skills
  - selected_skills → candidates (related_tools) → `ToolRouter.apply_dynamic_visibility()` fail-closed
  - config 翻译场景只暴露 `config_translation.translate_config`；knowledge 场景只暴露 `knowledge.query`；planned 永远不可见；forbidden 永远不可见；selector 异常 fallback v0.8 全量 + warning
- **v0.8.2 — Result Contract Standardization**：
  - 三层结果合同：`ModuleResult`（业务输出合同）/ `ToolResult`（Runtime/LLM 合同）/ `AgentResult.tool_calls`（审计/UI 合同）
  - `ModuleResult.success` / `failure` / `to_dict` / `from_dict`；`ToolResult.from_module_result` / `from_legacy_dict`；`loop._to_standard_tool_call` 投影
  - v0.7.1 业务输出合同**不变**；capability tests 41/41 零回归
- **v0.9 — Artifact Consumption & Review Flow**：
  - 新增 `artifact` capability（4 tools: list/read/diff/export）
  - 新增 `review` capability（2 tools: list_items/update_item）
  - 2 个新 enabled skills: `artifact_management` / `review_flow`
  - review 用 sidecar JSON 存储 status/user_note；**不**修改 translated_config 原文
  - `translated_config` 仍是 `authoritative=false / deployable_config=False`
  - v0.7.1 业务输出合同**不变**；capability tests 41/41 零回归
- **v1.0 — Knowledge Store Management**：
  - 新增 5 个 knowledge tool（import_document / list_sources / read_source / disable_source / delete_source）
  - 保留 `knowledge.query`（由 KnowledgeStore 驱动）
  - KnowledgeStore: workspace 隔离 JSONL 存储，无外部 DB 依赖
  - Token-overlap scoring（不要求向量库）；metadata 显式 `retrieval_backend=local_store`
  - `source_summary` snippet ≤ 200 字符；无 hits → `[]`（不伪造）
  - caller 传本地路径 → store 内部 redact 为 `redacted-local-path`
  - v0.7.1 业务输出合同**不变**；capability tests 41/41 零回归
- **Enabled business tools**：
  - `config_translation.translate_config`
  - `knowledge.query`
- **Enabled skills**：`assistant_chat`（base skill） / `config_translation` / `knowledge_query`
- **Enabled modules**：`config_translation` / `knowledge`
- **Planned modules (NOT callable)**：`topology`, `inspection`, `cmdb`（在 `CapabilityManifest` 中以 `status="planned"` 显式标记；`visible_tool_ids()` fail-closed 不返回）

### Test Baseline (re-measured 2026-06-10 on developer machine)

| Suite | Passed | Skipped | Failed | Note |
|-------|--------|---------|--------|------|
| v1.0 knowledge store tests | **29** | 0 | 0 | `harness/test_knowledge_store_v10.py` — import_document / list_sources / read_source / disable_source / delete_source / query；source_count 真实；无 hits → []；snippet ≤ 200；不伪造；本地路径 redact；CapabilityRegistry 7 capabilities；Tool count 67；planned 仍不可见 |
| v0.9 artifact / review flow tests | **29** | 0 | 0 | `harness/test_artifact_review_flow_v09.py` — artifact.list/read/diff/export；review.list_items/update_item；translated_config 不可改；不生成 deployable_config；CapabilityRegistry 7 capabilities；Tool count 62；planned 仍不可见；skill selector 路由 |
| v0.8.2 result contract tests | **28** | 0 | 0 | `harness/test_result_contract_v082.py` — ModuleResult success/failure/to_dict/from_dict；ToolResult.from_module_result（data + artifacts + warnings + errors）；config & knowledge service.to_module_result；config & knowledge tool handler 标准化；AgentResult.tool_calls 10 字段；缺失字段默认；v0.7.1 artifact/source_summary/manual_review_count 保留；legacy dict 适配 |
| v0.8.1 skill selector tests | **23** | 0 | 0 | `harness/test_skill_selector_v081.py` — config translation / knowledge / discovery / no-match / planned 注入控制 / config & knowledge 场景 visible tools / topology 阻断 / forbidden 阻断 / selector 异常 fallback / Snapshot 字段 / default services selector / per-turn 状态 |
| v0.8 capability manifest tests | **20** | 0 | 0 | `harness/test_capability_manifest_v08.py` — 5 capabilities / planned NOT callable / visible_tool_ids / to_snapshot_dict / from_capabilities / ToolRegistry / RuntimeServices / RuntimeSnapshot / Tool count 57 |
| v0.7/v0.7.1 capability tests (focused) | **41** | 0 | 0 | `test_capability_config_translation_v07.py` + `test_capability_knowledge_v07.py` + `test_capability_artifacts_v071.py` + `test_capability_knowledge_sources_v071.py` — **未回归** |
| v0.6.x ~ v1.0 broader focused regression | **744** | 7 | 0 | 7 skipped = `RUN_LIVE_TESTS=1` live LLM tests. v0.7.1 baseline 615 + v0.8 新增 20 + v0.8.1 新增 23 + v0.8.2 新增 28 + v0.9 新增 29 + v1.0 新增 29. **0 failed**. |
| Full harness `pytest harness -q` | — | — | — | Not re-run in this round (docs + refactor). On a TRAE sandbox full-run reports env-blockers (`PermissionError` on `config/LLM_setting.json` chmod 600 and `data/*.json`) — run on a developer machine for a clean full number. |

Retired surfaces record: [docs/RETIRED_SURFACES.md](docs/RETIRED_SURFACES.md)

## Version Evolution (v0.6 → v1.0)

| Commit | Version | Title | Key Changes |
|--------|---------|-------|-------------|
| `f45c3053` | v0.6 | rewrite backend around codex-style runtime | 删除 `agent/graph.py` + `agent/nodes/*` 主链，移入 `agent/legacy/`；新增 `agent/{app,core,runtime,protocol,context,tools,skills,modules,audit}/`；新增 `POST /api/agent/message`；15 tests |
| `569982a8` | v0.6 | finalize codex-style runtime | 修复 `agent.legacy` 动态导入路径；更新 harness 路径；新增 [docs/AGENT_BACKEND_RUNTIME_V06.md](docs/AGENT_BACKEND_RUNTIME_V06.md) |
| `e5487212` | v0.6.1 | stabilize codex-style runtime | 注册 `/api/agent/message`；`AgentResult.to_dict()` 增加 events；新增 25 tests |
| `bf555a0a` | v0.6.2 | stabilize rate limit and provider timeout | 修复 `RATE_LIMIT_DISABLED` 跨测试污染；URLError timeout 归类为 `provider_timeout`；`retryable=True`；中文友好超时；新增 16 tests |
| `2ae76bcb` | v0.6.3 | harden runtime tool routing | `default_runtime_services` 构建真实 `ToolRouter`；`llm_name_map` 白名单；unknown tool → `tool_call_failed`；`RuntimeSnapshot` 区分 total/visible tool count；System prompt 升级为 Runtime Contract；新增 20 tests |
| `ff6cff5d` | v0.7 | integrate config translation and knowledge capabilities | 接入 `config_translation.translate_config` 与 `knowledge.query`；Tool 数 55 → 57；topology/inspection/cmdb 保持 planned；新增 21 tests |
| `15565d18` | v0.7.1 | enrich capability artifacts and sources | `translated_config` 保存为 artifact（`authoritative=false, deployable_config=false`）；`manual_review_items` 结构化；knowledge `source_summary`（≤200 字符，无伪造）；`AgentResult.tool_calls` 增强；`ToolResultMessage.content` 1000 → 2000 字符；新增 20 tests |
| `0d160ce` | v0.7.1 sync | docs baseline sync | README / ARCHITECTURE / CAPABILITY_LAYER_V071 / RELEASE_HISTORY 同步到 v0.7.1 |
| `1c9f89b` | v0.7.1 align | align legacy provider timeout diagnostics assertion | 修复 v0.5 `test_timeout_returns_provider_timeout` 断言（accept "timeout" / "timed out" 两种 wording）；新增 wording-agnostic regression test |
| TBD | v0.8 | introduce capability manifest registry | 新增 `agent/capabilities/{schemas,registry,builtin}.py` + 5 个 module `capability.py`；`CapabilityRegistry` 作为能力真相源；`Module/Skill/ToolRegistry.from_capabilities()` / `register_capability_tools()`；`RuntimeServices.capability_registry`；`RuntimeSnapshot.build_runtime_snapshot()` 优先从 CapabilityRegistry 投影；planned 三个 capability 仍 `NOT callable`；Tool count 仍 = 57；新增 20 tests |
| TBD | v0.8.1 | add skill selector and dynamic tool visibility | 新增 `agent/skills/selector.py`（`SkillSelector` rule-based API：assistant_chat always-on + intent_patterns 命中 + capability_discovery meta-skill + planned 绝不注入 + 异常 fallback）；`ToolRouter.apply_dynamic_visibility()`（fail-closed 交集 = `registry_visible ∩ allowed_tool_ids`）；`RuntimeServices.skill_selector`；`ContextBuilder` 每轮调用 selector + 同步 router + 异常 fallback；`RuntimeSnapshot.selected_skills` / `selected_visible_tools` / `dynamic_tool_visibility` 新字段 + `to_prompt_text()` per-turn 段落；新增 23 tests |
| TBD | v0.8.2 | standardize result contracts | 新增 `agent/protocol/module_result.py`（`ModuleResult` + `success`/`failure`/`to_dict`/`from_dict`）；`ToolResult` 升级含 `data` / `artifacts` / `source_count` / `manual_review_count`；`ToolResult.from_module_result` / `from_legacy_dict`；`config_translation.service.to_module_result` / `knowledge.service.to_module_result`（service 适配）；`config_translation.tools` / `knowledge.tools` 改用 `to_module_result` + `from_module_result`（tool handler 适配）；`agent/runtime/loop.py::_to_standard_tool_call` 投影 10 标准字段；`AgentResult.tool_calls` 严格 10 字段；v0.7.1 业务输出合同不变；新增 28 tests |
| TBD | v0.9 | add artifact consumption and review flow | 新增 `agent/modules/artifact/`（`service` + `tools` + `capability`）— 4 tools: list/read/diff/export；新增 `agent/modules/review/`（`service` + `tools` + `capability`）— 2 tools: list_items/update_item；2 个 enabled skills: `artifact_management` / `review_flow`；`review.update_item` 写 sidecar JSON 存 status/user_note，**不**修改 translated_config 原文，**不**生成 deployable_config；`agent/capabilities/builtin.py` 加入 artifact + review；Tool count 57 → 62（+5：`artifact.list` 与已有 ToolRuntime catalog 去重）；v0.7.1 capability tests 41/41 零回归；新增 29 tests |
| TBD | v1.0 | add knowledge store management | 新增 `agent/modules/knowledge/store.py`（KnowledgeStore：JSONL + thread-lock + atomic write）；新增 5 个 knowledge tool：import_document / list_sources / read_source / disable_source / delete_source；保留 `knowledge.query`（现由 KnowledgeStore 驱动，store 无内容时 fallback 到 v0.7.1 legacy loader）；token-overlap scoring（不要求向量库）；`source_summary` snippet ≤ 200 字符，无 hits → `[]`（**不**伪造）；caller 传本地路径 → redact 为 `redacted-local-path`；v0.7.1 capability tests 41/41 零回归；Tool count 62 → 67（+5）；新增 29 tests |

完整版本表见 [docs/RELEASE_HISTORY.md](docs/RELEASE_HISTORY.md)。

## Current Master Chain

```
API (POST /api/agent/message)
  → AgentApp            (agent/app/facade.py)
  → AgentThread         (agent/core/thread.py)
  → AgentSession        (agent/core/session.py)
  → AgentTurn           (agent/core/turn.py)
  → RuntimeLoop         (agent/runtime/loop.py)
  → ToolRouter / RuntimeServices
  → invoke_llm() / ToolResultMessage
  → AgentResult.to_dict()
```

Legacy 入口 `POST /api/agent/run`（`agent/legacy/graph.run_agent()`）仍向后兼容，支持 `stream=true` SSE。

## Runtime Capabilities

### Enabled Skills
- `assistant_chat`（Agent 基础能力，非业务模块）
- `config_translation`
- `knowledge_query`

### Enabled Modules
- `config_translation`
- `knowledge`

### Enabled Tools (model-visible)
- 业务能力工具：
  - `config_translation.translate_config`
  - `knowledge.query`
- 通用工具：ToolRuntime v0.2 catalog 中的 55 个 enabled visible 工具（artifact / parser / report / command / web / session / runtime / text / workspace / powershell 等分类）

### Planned (NOT callable)
- `topology`
- `inspection`
- `cmdb`

> **planned means NOT callable**：planned 模块在 SkillRegistry / ModuleRegistry / RuntimeSnapshot 中显式标记为 planned，**不允许 LLM 调用**，**不允许伪造数据**。

### Tool Count
| Version | Total | Delta | 备注 |
|---------|-------|-------|------|
| v0.6.x | 55 | — | ToolRuntime v0.3 = 7 builtins + 48 general tools |
| v0.7+ | **57** | +2 | +`config_translation.translate_config`，+`knowledge.query` |

## Tool Runtime v0.3

Current tool count: **57** (7 v0.1 builtins + 48 v0.2 general + 2 v0.7 capability tools).

See [docs/TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md](docs/TOOL_RUNTIME_GENERAL_TOOLS_v0.2.md) for full catalog.

| Category | Count | Risk |
|----------|-------|------|
| artifact | 7 | low/medium |
| parser | 3 | low |
| report | 6 | low/medium |
| command | 2 | low/high |
| knowledge | 6 | low/medium |
| web | 5 | low/medium |
| session | 7 | low/medium |
| runtime | 5 | low |
| text | 8 | low |
| workspace | 5 | low/medium |
| powershell | 1 | high |
| **Capability (v0.7)** | **2** | low/medium |
| **Total** | **57** | |

### Safety
- `GET /api/tools/catalog` — read-only tool metadata.
- `POST /api/tools/invoke` — executes enabled tools only through ToolPolicy, ToolExecutor, redaction, and audit history.
- Tool Invoke UI is available for low/medium tools; high-risk tools require an `approval_id` with approved status that matches the same tool and workspace.
- Agent Tool Bridge can answer tool catalog questions and invoke explicit low-risk tools from chat; medium tools are dry-run only when explicitly requested, and high-risk tools require approval.
- High-risk tools (`command.approved_exec`, `powershell.approved_script`) default disabled, require matching approved status, and still only support allowlisted read-only actions.
- `shell.exec`, `powershell.exec`, `command.exec`, `ssh.exec`, `telnet.exec`, `snmp.walk`, `nmap.scan`, `ping.sweep`, `config.push`, `file.read_any`, `file.write_any` — **all forbidden**.
- **No real device access. No config push.**

## Capability Output Contract (v0.7.1)

### Config Translation
- 输入：`source_config`（必填）、`source_vendor`（默认 `auto`）、`target_vendor`（默认 `huawei`）、`options`（可选）
- 输出字段：
  - `ok`, `summary`
  - `source_vendor`, `target_vendor`
  - `line_count`, `translated_config`
  - `manual_review_items`（**结构化**，见下）
  - `manual_review_count`
  - `artifacts`（**translated_config 保存为 artifact**）
  - `warnings`, `errors`
  - `metadata`（含 `elapsed_ms`, `quality_summary`, `audit`, `build_commit`）
- **Artifact 契约**：
  - `artifact_type = "translated_config"`
  - `sensitivity = "sensitive"`
  - `source = "module_output"`
  - `metadata.authoritative = false`（**不可宣称权威**）
  - `metadata.deployable_config = false`（**不可直接部署**）
- **artifact 保存失败只警告，不阻塞翻译**（`warnings` 追加 `artifact_save_failed`）
- `quality_summary.source_residue_count > 0` 或 `silent_drop_count > 0` 时，结果要求人工复核，不可描述为"可直接部署"

### Knowledge Query
- 输入：`query`（必填）
- 输出字段：
  - `ok`, `summary`
  - `query`, `hits`, `source_count`
  - `source_summary`（**最多 5 条**，每条 `title/source/score/snippet`，`snippet ≤ 200` 字符）
  - `warnings`, `errors`
  - `metadata`
- **绝不伪造引用**：
  - 无 hits → `hits=[]`，`source_count=0`，`source_summary=[]`
  - knowledge 不可用 → `errors=["knowledge_unavailable"]`，`source_summary=[]`
  - 任何情况下都不会编造 title / source / score / citation

### Manual Review Item Schema (v0.7.1)
```json
{
  "item_id": "<uuid8>",
  "severity": "low|medium|high",
  "category": "syntax|semantic|unsupported_feature|vendor_difference|security|unknown",
  "line_no": 42,
  "source_text": "...",
  "translated_text": "...",
  "reason": "...",
  "recommendation": "...",
  "requires_human_review": true
}
```

### Runtime Result Enrichment (v0.7.1)
`AgentResult.tool_calls[]` 在 v0.7.1 增强：
```json
{
  "call_id": "<uuid>",
  "tool_id": "config_translation.translate_config",
  "ok": true,
  "summary": "...",
  "artifacts": [...],
  "source_count": 0,
  "manual_review_count": 3,
  "errors": [...],
  "warnings": [...],
  "metadata": {...}
}
```
`ToolResultMessage.content` 由 1000 字符扩到 2000 字符，并附 `artifact_count` + 前 3 个 artifact 摘要 + `source_summary` + `manual_review_count`，使 LLM 在下一轮能基于真实结果继续。

详细设计见 [docs/CAPABILITY_LAYER_V071.md](docs/CAPABILITY_LAYER_V071.md)。

## Quick Start

```bash
cd network_agent
pip install -r requirements.txt
python backend/main.py --port 8010
# 本机访问 http://127.0.0.1:8010
# 局域网访问 http://<这台机器的网口IP>:8010
```

## 入口 API

| 端点 | 说明 |
|------|------|
| `POST /api/agent/message` | Agent 执行入口 v0.6+（Codex-style Runtime，preferred） |
| `POST /api/agent/run` | Agent 执行入口 legacy（向后兼容，支持 `stream=true` SSE） |
| `POST /api/modules/config-translation/translate` | 配置翻译（业务模块直连入口） |
| `POST /api/tools/invoke` | 工具调用（ToolRuntimeClient） |
| `GET  /api/tools/catalog` | 工具目录（只读元数据） |
| `POST /api/jobs` | 任务提交 |
| `GET  /api/sessions` | 会话列表（按 workspace） |
| `POST /api/sessions` | 创建新会话 |
| `PUT  /api/sessions/{id}` | 更新会话（重命名等） |
| `GET  /api/sessions/{id}` | 会话详情 + 消息 |
| `POST /api/sessions/{id}/archive` | 归档会话 |
| `POST /api/sessions/{id}/soft-delete` | 软删除会话 |
| `GET  /api/runs/recent` | 后端工作区运行历史摘要 |
| `GET  /api/runs/{run_id}` | 默认/指定工作区运行详情 |
| `GET  /api/workspaces/{id}/history` | 指定工作区运行历史 |
| `DELETE /api/workspaces/{id}` | 删除工作区 |
| `POST /api/workspaces/{id}/rename` | 重命名工作区 |
| `GET  /api/agent/status` | Agent 状态 |
| `POST /api/agent/llm/config` | 保存 LLM 配置 |
| `GET  /api/agent/llm/config` | 读取 LLM 配置（不返回完整 key） |
| `GET  /api/workspaces/{id}/state` | 工作区状态 |
| `GET  /api/memory/list` | 记忆列表 |
| `GET  /api/runtime/health` | 系统健康诊断 |

## 测试

```bash
# Capability Layer (v0.7/v0.7.1) — clean focused baseline
pytest harness/test_capability_config_translation_v07.py \
        harness/test_capability_knowledge_v07.py \
        harness/test_capability_artifacts_v071.py \
        harness/test_capability_knowledge_sources_v071.py -q
# 41 passed, 0 failed

# Focused regression (v0.6.x → v0.7.1)
pytest harness -q -k "capability_artifacts or capability_knowledge_sources or \
                       capability_config_translation or capability_knowledge or \
                       runtime_hardening or agent_backend_runtime or provider_timeout or \
                       rate_limit or approval or redaction or tool_runtime or llm"
# 615 passed, 7 skipped (live LLM), 0 failed (v0.5 timeout-message test resolved in this round)

# Full harness
pytest harness -q
# 真实数字：本地沙箱外运行（沙箱限制 config/LLM_setting.json 写）
```

## 目录结构

```
network_agent/
├── agent/                    # Agent 主框架 (Codex-style Runtime)
│   ├── app/                  # AgentApp, Thread, Session, Turn
│   ├── core/                 # Agent 核心接口
│   ├── runtime/              # RuntimeLoop, ToolRouter, ToolRegistry, prompts
│   ├── protocol/             # Agent protocol 消息定义
│   ├── context/              # RuntimeSnapshot, safe_context
│   ├── tools/                # ToolRouter / ToolRegistry
│   ├── skills/               # SkillRegistry (assistant_chat, config_translation, knowledge_query)
│   ├── modules/              # ModuleRegistry + Capability services
│   │   ├── config_translation/  # v0.7 capability service
│   │   └── knowledge/            # v0.7 capability service
│   ├── audit/                # Event, TraceRecorder, RolloutRecorder
│   ├── llm/                  # invoke_llm (统一入口), safe_generate, provider, policy, settings
│   ├── legacy/               # 旧 LangGraph 7-node pipeline (deprecated, 仅向后兼容)
│   └── nodes/                # (已废弃，迁入 legacy/)
├── modules/                  # 业务模块 (modules-level)
├── skills/                   # Agent 技能包 (adapter → module)
├── memory/                   # JSONL 记忆系统 (redaction + policy + cleanup_expired + compact)
├── workspace/                # 工作区运行时 (state, runs, artifacts)
├── harness/                  # pytest 测试 (含 v0.7.1 capability 测试)
├── frontend/                 # 统一前端
├── backend/                  # Flask API (SSE streaming, rate limit)
│   ├── api/                  # sse.py, rate_limit.py, agent_routes.py (v0.6+), agent.py (legacy)
│   └── core/                 # limits, paths, rate_limit middleware
├── runtime/                  # 运行时工具 (lifecycle_base, archive, retention)
├── config/                   # LLM 配置 (LLM_setting.json gitignored, 600)
├── context/                  # 上下文压缩器 v0.2 (dynamic budget, dedup)
├── tool_runtime/             # 工具运行时 (regex forbidden patterns)
├── .github/workflows/        # CI pipeline (py3.10-3.12, ruff lint)
├── scripts/                  # 审计/清理工具
├── reports/                  # 审计报告
└── docs/
    ├── AGENT_BACKEND_RUNTIME_V06.md   # v0.6 Runtime 底座
    ├── CAPABILITY_LAYER_V071.md       # v0.7.1 Capability Layer
    ├── RELEASE_HISTORY.md             # 完整版本演化
    ├── ARCHITECTURE.md                # 总体架构
    └── ...                            # 各子系统设计文档
```

## 安全基线

- LLM 不改 `deployable_config`，不产生可直接部署的输出
- 不宣称"可直接部署"，不以 AI 能力绕过人工复核
- API key 仅本地存储，API 返回 `key_preview` 不返回完整 key
- 所有 Memory/Workspace/Run/Trace 写入走 redaction + policy 门控
- `config/LLM_setting.json` 权限 600，不进 Git
- Module / Skill 不得私接 LLM
- 跨工作区访问默认拒绝
- **No real SSH / Telnet / SNMP / nmap execution**
- **`config.push` 永久禁止**
- **topology / inspection / cmdb 仍为 planned，不允许伪造数据**

## 下一步

1. Knowledge Index Runtime 完整化（chunk policy、增量索引、引用血缘）
2. 工具调用归因与可观测性增强（tool_call 事件链）
3. 跨工作区协作与多租户隔离强化
4. Business Modules: `topology`, `inspection`, `knowledge`, `cmdb`（按规划逐步启用）
