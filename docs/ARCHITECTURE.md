# Network Agent Architecture

## Current Closure State

- Baseline commit: `8cf0a1b` (2026-06-09)
- Baseline test evidence: `pytest harness -q` = `1351 passed, 7 skipped, 0 failed`
- Current enabled business module: `config_translation`
- Current enabled base capability: `knowledge_base` (knowledge_search MVP)
- Knowledge Index Runtime (Safe Local RAG Foundation v0.1): indexing + search, no auto RAG
- Agent base capability: `assistant_chat` (not a business module)
- LLM Orchestrator: agentic loop for chat/knowledge with disabled fallback
- SSE Streaming: `POST /api/agent/run` supports `stream=true`
- Rate Limit: IP-based middleware for all API endpoints
- Planned only: Topology, Inspection, CMDB
- Tool Runtime has Foundation + Client + Integration + supervised Agent Tool Bridge, but no real device execution.
- Run history is backend workspace state, not browser-local history.
- `quality_summary` is carried through API, Agent result, run history, UI, trace metadata, and report summaries.
- Backend routes: main.py + sub-route files (agent, artifact, context, job, knowledge, llm, memory, modules, runtime, session, skills, sse, version, workspace)

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

```
POST /api/agent/run → graph (stream=true → SSE)
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
Composer → safe_generate
  → prompts.loader (registry.yaml 加载模板)
  → renderer       (Jinja2 渲染)
  → policy input   (安全策略门控)
  → provider       (MiniMax / OpenAI Compatible / Ollama / Mock)
  → policy output  (安全策略门控)
```

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
