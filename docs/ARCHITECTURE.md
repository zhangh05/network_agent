# Network Agent Architecture

## Agent Backend v1.0.1.1 — Knowledge Ingestion Security & Gate Fix (CURRENT)

> **HEAD**: `15565d1` (2026-06-10) · **Runtime**: Codex-style (v0.6 底座 + v0.7/v0.7.1 能力层) · **Tool count**: 57
>
> 本文档是 Network Agent 的总体架构图谱，按"Runtime 主链（v0.6）→ 能力层（v0.7 / v0.7.1）"分层描述。
> - Runtime 底座单一权威：[AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md)
> - 能力层单一权威：[CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md)
> - 版本演化：[RELEASE_HISTORY.md](RELEASE_HISTORY.md)
> - 用户入口：[README.md](../README.md)

### Overview

Agent Backend v0.6 rewrites the backend around a Codex-style Agent Runtime, replacing the old LangGraph 7-node pipeline with a modern Thread/Session/Turn/RuntimeLoop architecture. v0.6.1 / v0.6.2 / v0.6.3 围绕稳定性、tool routing 做增量；v0.7 / v0.7.1 在底座之上引入 **Capability Layer（config_translation / knowledge_query）**，**未触碰** Runtime 主链。

### New Master Chain

```
POST /api/agent/message
  → AgentApp.submit_user_message()
  → AgentThread.submit()
  → AgentSession.submit()
  → AgentTurn
  → RuntimeLoop.run_turn()
  → invoke_llm() [agent/llm/runtime.py]
  → AgentResult.to_dict()
```

Key modules:
- `agent/app/` — AgentApp, Thread, Session, Turn
- `agent/runtime/` — RuntimeLoop, ToolRouter, ToolRegistry
- `agent/context/` — RuntimeSnapshot, safe_context injection
- `agent/skills/` — SkillRegistry (assistant_chat, config_translation, knowledge_query)
- `agent/modules/` — ModuleRegistry (config_translation, knowledge)
- `agent/tools/` — ToolRouter (model_visible_tools, dispatch)
- `agent/audit/` — Event stream, TraceRecorder, RolloutRecorder
- `agent/llm/` — invoke_llm() unified entry, safe_generate, policy, settings

### assistant_chat Behavior
- **v0.6**: assistant_chat defaults to **with-tools** (LLM-tool loop)
- Tools exposed via RuntimeSnapshot injection
- Tool calls route through ToolRouter → ToolRuntimeClient.invoke()
- Results re-injected as ToolResultMessage back into LLM

### Legacy Compatibility

The old 7-node LangGraph pipeline is preserved in `agent/legacy/`:
- `POST /api/agent/run` → `agent/legacy/graph.run_agent()` (still works)
- `agent/legacy/` is NOT imported by the new master chain
- All legacy node files: intent_router, context_loader, planner, skill_executor, verifier, composer, memory_writer, llm_orchestrator

### ToolRouter / ToolRegistry
- ToolRegistry built from ToolRuntimeClient.list_tools()
- disabled / forbidden tools hidden from model
- high-risk tools exposed but execute through ToolRuntime + Approval
- Safe name mapping: `runtime__health` → `runtime.health`
- model_visible_specs separated from internal registry

### Skill / Module / Snapshot
- SkillRegistry: assistant_chat, config_translation, knowledge_query enabled; topology, inspection, cmdb planned
- ModuleRegistry: config_translation, knowledge enabled; topology, inspection, cmdb planned
- RuntimeSnapshot.to_prompt_text(): distinguishes enabled vs planned, tools available vs NOT callable
- "工具呢？" now backed by RuntimeSnapshot, not static product description

### Audit / Trace / Rollout
- Every turn has: turn_started, context_built, model_request_started, model_response_received, assistant_message, turn_finished
- Tool-call turns additionally: tool_call_started, tool_call_finished
- TraceRecorder: model_request, model_response, tool_call, tool_result
- RolloutRecorder: persist_turn (basic implementation)

## Module / Skill / Tool 三层关系 (v0.7+)

Capability Layer 在 v0.7 起形成**显式三层**结构，业务能力接入 ToolRouter 仍走**唯一**的 `ToolRuntimeClient.invoke()` 路径。

```
┌─────────────────────────────────────────────────────────────────────┐
│ Skill  (agent/skills/)   ← LLM 看到的能力描述，绑定到 SkillRegistry │
│  ├─ assistant_chat          (enabled)                                │
│  ├─ config_translation      (enabled, v0.7)                          │
│  ├─ knowledge_query         (enabled, v0.7)                          │
│  ├─ topology                (planned, NOT injected)                  │
│  ├─ inspection              (planned, NOT injected)                  │
│  └─ cmdb                    (planned, NOT injected)                  │
├─────────────────────────────────────────────────────────────────────┤
│ Module (agent/modules/)  ← 业务能力的服务实现，绑到 ModuleRegistry  │
│  ├─ config_translation.service.translate_config  (v0.7)             │
│  ├─ knowledge.service.query_knowledge             (v0.7)             │
│  ├─ topology                                    (planned)            │
│  ├─ inspection                                  (planned)            │
│  └─ cmdb                                        (planned)            │
├─────────────────────────────────────────────────────────────────────┤
│ Tool   (model_visible_tools)  ← 真正给 LLM function_call 的工具    │
│  ├─ config_translation.translate_config          (v0.7, 1)          │
│  ├─ knowledge.query                              (v0.7, 1)          │
│  └─ ToolRuntime catalog 其它 55 个 enabled visible tools            │
│       (artifact / parser / report / command / web / session /        │
│        runtime / text / workspace / powershell / knowledge)         │
└─────────────────────────────────────────────────────────────────────┘
```

边界：
- **Skill → Module** 通过 `agent/skills/{name}/adapter.py` 适配；Skill 不直接调 LLM、不直接读模块实现。
- **Module → Tool** 通过 `agent/modules/{name}/service.py` + `ToolRouter` 注入；Module 不私接 LLM。
- **Tool execution 唯一入口**：`ToolRouter.dispatch()` → `ToolRuntimeClient.invoke()` → ToolPolicy / ToolExecutor / Redaction / Audit。
- **planned = NOT callable**：planned Skill/Module 不出现在 RuntimeSnapshot 的 enabled 部分，对应 tool 不在 `model_visible_tools()` 中；LLM 永远无法触发它们，也不允许伪造其结果。
- **v0.7.1 起**：Tool 的输出经过 `artifacts.store` 落库（capability tools）或原样返回（general tools），`AgentResult.tool_calls` 携带 `artifacts / source_count / manual_review_count` 等富化字段，反馈到 LLM 下一轮。

详细契约见 [MODULE_SKILL_TOOL_MODEL.md](MODULE_SKILL_TOOL_MODEL.md) 与 [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md)。

## Current Closure State (v1.0.1.1)

- **HEAD**: v1.0.1.1 commit（fix(knowledge): harden ingestion boundaries and test gate）
- **Test baseline (focused regression, 2026-06-10)**:
  - v1.0.1 document ingestion tests: **22 / 22 passed**（`harness/test_document_ingestion_book_library_v101.py`）
  - v1.0 knowledge store tests: **29 / 29 passed**（**未回归**）
  - v0.9 artifact / review flow tests: **29 / 29 passed**（**未回归**）
  - v0.8.2 result contract tests: **28 / 28 passed**（**未回归**）
  - v0.8.1 skill selector tests: **23 / 23 passed**（**未回归**）
  - v0.8 capability manifest tests: **20 / 20 passed**（**未回归**）
  - v0.7/v0.7.1 capability tests: **41 passed, 0 failed**（**未回归**）
  - v1.0.1 broader focused baseline: **744 passed, 7 skipped, 0 failed**（7 skipped = `RUN_LIVE_TESTS=1` live LLM tests. v0.7.1 baseline 615 + v0.8/v0.8.1/v0.8.2/v0.9/v1.0 capability layer tests + v1.0.1 ingestion 22 = 744. **0 failed**）
  - v1.0.1.1 security focused suite: **266 passed, 2 skipped, 0 failed**（2 skipped = `RUN_LIVE_TESTS=1` gated live-LLM tests. v0.7.1 baseline 41 capability + v0.8/v0.8.1/v0.8.2/v0.9/v1.0 capability layer + v1.0.1 ingestion 22 + v1.0.1.1 security 16 = 266. **0 failed**）

  > 两个数字**不**是同一 regression 的演进——它们是两次**不同筛选范围**的 focused 套件。
  - Full harness `pytest harness -q` 本轮 docs-only sync + 架构 refactor 中**未**重跑
- **Runtime architecture**: Codex-style Agent Runtime（Thread / Session / Turn / RuntimeLoop）— v0.6 引入，**v0.6.1 ~ v1.0.1 主链未变**
- **CapabilityRegistry (v1.0.1)**: 7 个 capability（4 enabled + 3 planned），**单一真相源**
- **v1.0 NEW — Knowledge Store Management** (carried forward)
- **v1.0.1 NEW — Document Ingestion & Book Library**:
  - 新增 `agent.modules.knowledge.parsers/` (md / txt / html / docx / text-pdf；扫描型 PDF → `unsupported_ocr`)
  - 新增 `agent.modules.knowledge.chunking.py`：结构优先 + 保护块 + 父子分块（child 180-1200 chars / overlap 80；parent 1200-3000 chars）
  - 新增 `agent.modules.knowledge.index.py`：纯 Python BM25 + scope boost + scope 优先级
  - 新增 `agent.modules.knowledge.ingestion.py`：file → NormalizedDocument → Source + chunks
  - 新增 `agent.modules.knowledge.schemas.py`：NormalizedDocument / KnowledgeSource / KnowledgeChunk
  - 新增 6 个 knowledge tool：import_file / list_chunks / search_chunks / read_chunk / read_parent / reindex_source
  - `knowledge.query` 改为 3 段 fallback：chunk→v1.0 store→legacy loader
  - Tool count: 67 → **73**（+6）
- **v1.0.1.1 NEW — Knowledge Ingestion Security & Gate Fix**:
  - `import_file` 路径白名单：`workspace/{ws_id}/{uploads,inbox}/`；拒绝 `..` / 符号链接逃逸 / 文件不存在 / > 50MB / DOCX archive bomb
  - `knowledge.read_source` `callable_by_llm=False`（LLM 只能 `list_sources` / `search_chunks` / `read_chunk` / `read_parent`）
  - `tags` schema 统一为 `array[string]`（import_file / search_chunks）
  - 文档术语统一：**BM25 lexical retrieval + scope boost + parent expansion**（**不**再称 hybrid retrieval）
  - 2 个 live-LLM 测试改为 `RUN_LIVE_TESTS=1` 才执行
  - Tool count 仍为 **73**（**无**新增工具）
- **Enabled business tools** (v0.7+):
  - `config_translation.translate_config`（capability service: `agent.modules.config_translation.service.translate_config`）
  - `knowledge.query`（capability service: `agent.modules.knowledge.service.query_knowledge`）
- **Enabled Skills**: `assistant_chat`（基础能力，非业务模块） / `config_translation` / `knowledge_query`
- **Enabled Modules**: `config_translation` / `knowledge`
- **Planned (NOT callable)**: `topology` / `inspection` / `cmdb`（在 CapabilityManifest 中以 `status="planned"` 显式标记，所有 planned tool `callable_by_llm=False`；`CapabilityRegistry.visible_tool_ids()` fail-closed 不返回）
- **Tool count**: 55 (v0.6.x) → **57** (v0.7+)，新增 `config_translation.translate_config` + `knowledge.query`；**v0.8 不变**
- **Tool execution 唯一入口**: `ToolRouter → ToolRuntimeClient`（v0.6.3 起由 `default_runtime_services` 构建真实 ToolRouter；v0.6.3 引入 `llm_name_map` 白名单；v0.8 通过 `ToolRegistry.register_capability_tools(capability_registry)` 把 capability tools 注入）
- **Capability output contract (v0.7.1)**:
  - `translated_config` 以 `translated_config` 类型 artifact 持久化（`authoritative=false, deployable_config=false, sensitivity=sensitive`）
  - `manual_review_items` 结构化（item_id / severity / category / line_no / reason / requires_human_review …）
  - `knowledge.source_summary`（≤ 5 条，snippet ≤ 200 字符，**绝不伪造**）
  - `AgentResult.tool_calls` 增强（call_id / artifacts / source_count / manual_review_count / errors / warnings / metadata）
  - `ToolResultMessage.content` 1000 → 2000 字符
- Knowledge Index Runtime (Safe Local RAG Foundation v0.1): indexing + search, no auto RAG
- Agent base capability: `assistant_chat` (not a business module)
- LLM Orchestrator: agentic loop for chat/knowledge with disabled fallback
- SSE Streaming: `POST /api/agent/run` supports `stream=true`
- Rate Limit: IP-based middleware for all API endpoints
- Tool Runtime has Foundation + Client + Integration + supervised Agent Tool Bridge, but **no real device execution**
- Run history is backend workspace state, not browser-local history
- `quality_summary` is carried through API, Agent result, run history, UI, trace metadata, and report summaries
- Backend routes: main.py + sub-route files (agent, artifact, context, job, knowledge, llm, memory, modules, runtime, session, skills, sse, version, workspace)

> 详细能力契约、Artifact 契约、Manual Review Schema、Knowledge Source 规则、Runtime Result Enrichment 见 [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md)。

## 总体架构

```
Frontend → API (8010) → Agent (LangGraph)
                           ├── Intent Router (keyword-based)
                           ├── Context (fragments v0.1, compressor v0.2, compaction, builder)
                           ├── Registry / Capability / Skill / Module
                           ├── LLM Orchestrator (agentic loop / disabled fallback)
                           ├── Hook System (8 events, disjunctive folding)
                           ├── Skill Executor
                           ├── Verifier
                           ├── Composer (LLM)
                           └── Memory (writer, redaction, policy, cleanup_expired)

Horizontal base:
Workspace / Memory / Artifact / Report / Job / Trace /
Session / LLM Settings / Prompt / Harness
Tool Runtime / SSE Streaming / Rate Limiting
Lifecycle Utilities (lifecycle_base)
```

## v0.4.1 Architecture Hardening

### Orchestrator Single Entry
Orchestrator removed from graph nodes — runs inside `skill_executor.execute()`. Pipeline is now 7-node trace chain: router→context→planner→executor→verifier→composer→memory. Module_call events produced via `_record_module_event()` in `llm_orchestrator.py`.

### Rate Limit per-IP + Endpoint
`backend/core/rate_limit.py` refactored: sliding window uses request timestamp list (accurate). Per-IP + endpoint key: `{client_ip}:{endpoint}:{max_req}:{window}`. Respects `TRUSTED_PROXY` env var.

### ToolRuntimeContext Propagation
`llm_orchestrator.py`::_execute_tool() now passes `ToolRuntimeContext(workspace_id, run_id, trace_id, requested_by)` to `ToolRuntimeClient.invoke()`. Enables workspace isolation + audit for orchestrator-triggered tool executions.

### Approval Admin Boundary
`backend/api/runtime_routes.py` now checks admin via `_require_admin()`: `X-Admin-Token` header matching `NETWORK_AGENT_ADMIN_TOKEN`, or localhost fallback. High-risk tool approvals require admin privileges.

## Session 会话层

v3.1 新增会话（Session）抽象，将独立的 Agent Run 组织为可恢复的对话线程。

```
Session Store ──→ workspaces/<ws>/sessions/<sid>.json
   ├── create / list / get / update / archive / soft-delete / permanent-delete
   ├── add_run_to_session ── 自动关联 run 到 session
   ├── get_session_messages ── 将 runs 转为 Chat UI 消息列表
   └── auto_title_from_input ── 首条消息自动生成会话标题
```

前端通过 `/api/sessions/<id>?include_messages=1` 加载完整对话历史，
`localStorage` 仅保存 `na_current_session_id` 指针，不保存消息内容。
详见：[SESSION_MANAGEMENT.md](./SESSION_MANAGEMENT.md)

## Agent 调用链

### v0.6 Master Chain (NEW)
```
POST /api/agent/message → AgentApp.submit_user_message()
  → AgentThread → AgentSession → AgentTurn
  → RuntimeLoop.run_turn()
  → invoke_llm() (unified entry, with-tools)
  → ToolRouter.dispatch() (if tool_calls)
  → ToolRuntimeClient.invoke()
  → ToolResultMessage → LLM follow-up
  → AgentResult.to_dict()
```

### Legacy Chain (DEPRECATED, preserved for backward compat)
```
POST /api/agent/run → graph.run_agent() (agent/legacy/)
  → intent_router    (intent inference via keyword matching)
  → context_loader   (上下文加载、压缩 v0.2 dynamic budget + dedup)
  → planner          (execution plan setup)
  → skill_executor   (→ orchestrator for chat/knowledge, adapter → module for translate)
  → verifier         (结果校验 + quality gate)
  → composer         (LLM 响应合成, 4 intent-specific paths)
  → memory_writer    (记忆写入、Workspace 更新、Run 落盘、cleanup_expired)
```

Orchestrator (embedded in executor for chat/knowledge):
```
llm_orchestrator  → LLM enabled?  → agentic loop (up to 10 steps)
                  → LLM disabled? → deterministic tool queries → execution
                  → blocked?      → graceful degradation
```

## Agent Tool Bridge

```
assistant_chat / knowledge_query 明确工具请求
  → agent/nodes/llm_orchestrator.py (agentic loop)
  → ToolRuntimeClient
  → ToolPolicy / ToolExecutor / Redaction / Audit
```

边界：
- LLM enabled: LLM function calling → tool selection → safe execution → verification loop
- LLM disabled: keyword-based tool matching → deterministic execution
- low 风险且 enabled 的工具可由 Agent 自动调用
- medium 风险只允许明确 dry-run/预演
- high 或 requires_approval 工具只返回审批提示，不自动执行

Note: `agent/nodes/tool_planner.py` is legacy — its logic has been superseded by `llm_orchestrator.py::_handle_llm_disabled()`.

## config_translation 调用链

```
Agent → capability: config.translate
      → skill: config_translation (adapter)
      → module: config_translation (service)
      → translate_bundle (核心管线)
```

## Job 调用链

```
POST /api/jobs → JobManager → Worker → JobRunner
  → run_agent() → Agent Runtime (同上 Agent 调用链)
Job 状态机: queued → running → succeeded / failed / cancelled
Job 默认归属当前 workspace。
```

## LLM / Prompt 链

```
Composer / Orchestrator → invoke_llm (统一入口)
  → prompts.loader (registry.yaml 加载模板)
  → renderer       (Jinja2 渲染)
  → policy input   (安全策略门控, NON-BLOCKING)
  → provider       (MiniMax / OpenAI Compatible / Ollama / Mock)
  → policy output  (安全策略门控, NON-BLOCKING)
  → safe_generate  (公共 API 包装, 返回 SafeLLMOutput)
```

`invoke_llm()` 是所有 LLM 调用的**唯一入口点**，直接调用 `provider.generate()`。
`safe_generate()` 是其公共包装，添加 policy 检查和 SafeLLMOutput 返回格式。
Policy 检查是**非阻塞**的：失败仅记录到 metadata/warnings，不阻断 provider 调用。

### v0.5.1 — Diagnostics Consistency (2026-06-10)

- `safe_generate()` 错误分支透传 provider metadata（`provider_error_type`, `http_status`, `provider_error_message`）
- `invoke_llm()` disabled 分支返回 `error_type=disabled_by_user`
- `check_request()` 接收 `safe_context` + `tools`（非阻断）
- `key_source` 准确区分：`ui_settings` / `env_fallback` / `env`
- `ui_settings` disabled=true 不被 env key 覆盖
- `auto_default` disabled + env key → `enabled=true`, `config_source="env"`, `key_source="env"`
- orchestrator 清理 3 处 unused `req = LLMRequest(...)` 残留

## Context 链

```
context_ref → resolver → loader → selector
  → compressor (v0.2: dynamic budget per model, semantic dedup, regex-sensitive keys)
  → builder
  → ContextBundle { execution_context, safe_llm_context }
```

ContextBundle 的 `safe_llm_context` 经过脱敏和截断后方可进入 LLM prompt。
Dynamic budget 按模型分配 (MiniMax 64k, Qwen 128k 等)。

## Artifact 统一文件基座

所有文件 I/O 通过 `ArtifactStore`：
- artifact_scopes: `workspace`, `run`, `shared`, `temp`
- artifact_types: `input`, `output`, `report`, `intermediate`
- sensitive artifacts 标记并限制访问
- 产物引用在 Memory / Run / Trace 中仅存 `artifact_id` + `summary`

## Report / Export 管线

```
ReportComposer → render (Jinja2) → export (HTML/Markdown/JSON)
  → ArtifactStore (report artifact)
  → Memory (report summary + artifact_ref)
```

## 架构模型

Module / Skill / Capability / Tool 四层边界定义：[MODULE_SKILL_TOOL_MODEL.md](./MODULE_SKILL_TOOL_MODEL.md)

Tool Runtime Foundation v0.1：[TOOL_RUNTIME.md](./TOOL_RUNTIME.md) — 轻量原子工具执行底座（无真实设备执行）
Tool Runtime Integration Contract：[TOOL_RUNTIME_INTEGRATION.md](./TOOL_RUNTIME_INTEGRATION.md) — Module/Trace/Job 集成契约

## Hook System v0.1

`agent/hooks.py` — composable pre/post processing pipeline (Codex-inspired):

```
Hook Registry → Event Dispatch → Priority-ordered Execution → Result Folding
```

8 event types: PreToolUse, PostToolUse, PreTurn, PostTurn, SessionStart, Stop, PreCompact, PostCompact.

Disjunctive folding semantics:
- PreToolUse: any Deny wins immediately; last Allow's updated_input wins
- PostToolUse: any stop=true wins; feedback concatenated
- Stop: block overrides stop (force continue)
- SessionStart: any stop=true wins; contexts merged

Integrated at: SessionStart (graph.py), tool calls (orchestrator), turn completion (orchestrator).

## Context Compaction

`context/compaction.py` — dual-limit token budget management:
- Auto-compact trigger at 80% of model budget
- Per-model budgets: MiniMax 64k, GPT-4o 128k, Qwen 128k
- Pre-turn check in orchestrator
- compact_session_history(): old turn summarization
- compact_llm_context(): field-level truncation

## 安全边界

- **LLM 红线**: 不生成 deployable_config，不声称可直接部署，不隐藏 manual_review 标记
- **Key 保护**: API key 仅本地存储，API 返回 key_preview，不进 log/trace/memory/state
- **Redaction 层**: Memory 写入、Trace 写入、State 写入、Run 写入均经 redaction
- **Artifact 隔离**: sensitive artifact 标记，跨 workspace 访问默认拒绝
- **Module 隔离**: Module / Skill 不得私接 LLM
- **Rate Limit**: IP-based middleware 保护所有 API 端点
- **Lifecycle**: `runtime/lifecycle_base.py` 消除 archive/retention 重复

## SSE Streaming

`POST /api/agent/run` with `stream=true` enables Server-Sent Events streaming:
```
SSE event types: node_start, node_progress, tool_call, tool_result, text_chunk, node_end, error, done
```
Implemented in `backend/api/sse.py`. Frontend uses `EventSource` or fetch with `ReadableStream`.
