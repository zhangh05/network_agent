# Network Agent

Network Agent 是一个网络工程本地 Agent 平台，面向网络工程师提供配置翻译、拓扑发现、巡检分析、知识管理等 AI 驱动的网络运维能力。平台基于 LangGraph 运行时调度，以 Module / Skill / Memory 三层架构组织，统一入口端口 8010。

## Platform Runtime Closure — Current Baseline

Current commit: `8cf0a1b`

Current test baseline: `pytest harness -q = 1351 passed, 7 skipped, 0 failed`.
Skipped: 7 tests require `RUN_LIVE_TESTS=1` (live LLM API tests).

Retired surfaces record: [docs/RETIRED_SURFACES.md](docs/RETIRED_SURFACES.md)

Network Agent is a new local network-engineering Agent platform, not a legacy framework migration. The current runtime chain is:

```
router → context → planner → executor (orchestrator for chat/knowledge) → verifier → composer → memory
```

Current enabled business module: **config_translation** only. `assistant_chat` is an Agent base capability, not a business module. Topology, Inspection, CMDB, and Knowledge remain planned/coming_soon and must not fabricate runtime data.

### Enabled Modules
- config_translation
- knowledge_base (knowledge_search enabled / embedded_mvp)

Run history is backend/workspace-backed. Browser `localStorage` is for UI preferences only, not run history, configs, prompts, keys, jobs, reports, or artifacts.

LLM settings saved from the frontend are persisted by the backend through `POST /api/agent/llm/config` into gitignored `config/LLM_setting.json`. The browser does not persist the API key. When the key field is left empty on re-save, the existing stored key is preserved (not overwritten). The settings panel shows "(已配置)" indicator when a key is already stored. LLM configuration is global — one file for all workspaces.

## Tool Runtime v0.3

Current tool count: **55** (7 v0.1 builtins + 48 v0.2 general tools).

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
| **Total** | **55** | |

### Safety
- `GET /api/tools/catalog` — read-only tool metadata.
- `POST /api/tools/invoke` — executes enabled tools only through ToolPolicy, ToolExecutor, redaction, and audit history.
- Tool Invoke UI is available for low/medium tools; high-risk tools require an `approval_id` with approved status that matches the same tool and workspace.
- Agent Tool Bridge can answer tool catalog questions and invoke explicit low-risk tools from chat; medium tools are dry-run only when explicitly requested, and high-risk tools require approval.
- High-risk tools (`command.approved_exec`, `powershell.approved_script`) default disabled, require matching approved status, and still only support allowlisted read-only actions.
- `shell.exec`, `powershell.exec`, `command.exec`, `ssh.exec`, `telnet.exec`, `snmp.walk`, `nmap.scan`, `ping.sweep`, `config.push`, `file.read_any`, `file.write_any` — **all forbidden**.
- No real device access. No config push.

### Latest Verification
- 2026-06-09: full harness after frontend/backend safety fixes + SSE streaming/rate limit/LLM orchestrator hardening — `1351 passed, 7 skipped`.
- Browser reload check on `127.0.0.1:8010` verified top status and Agent status stay `已连接` with no console errors.

Tool Runtime has Foundation + Client + Integration contracts and writes safe ToolResult metadata into observability traces when invoked with trace context. It still does **not** support SSH/Telnet/SNMP/nmap/ping sweep/arbitrary shell/config push or real device execution.

`quality_summary` is part of the platform summary chain for config translation. If `source_residue_count > 0` or `silent_drop_count > 0`, the result requires warnings/manual review and must not be described as ready for device execution.

## Recent Additions (v0.4)

### SSE Streaming
`POST /api/agent/run` supports `stream=true` parameter. When enabled, server pushes Agent execution progress as Server-Sent Events (SSE) including node transitions, chunked LLM output, tool executions, and status updates. See `backend/api/sse.py`.

### Rate Limiting
IP-based request rate limiting via `backend/core/rate_limit.py` as Flask middleware. Configurable bucket capacity and refill rate per endpoint.

### LLM Orchestrator
`agent/nodes/llm_orchestrator.py` provides agentic loop execution for `assistant_chat` and `knowledge_query` intents. LLM uses function calling to decide tool invocations autonomously. When LLM is disabled, falls back to deterministic tool queries by keyword matching. Supports up to 10 orchestration steps with safe generate gating at each step.

### Context Compressor v0.2
Dynamic budget allocation per model (MiniMax 64k, Qwen 128k, etc.), semantic deduplication, and regex-based sensitive key matching. See `context/compressor.py`.

### Lifecycle Utilities
`runtime/lifecycle_base.py` extracts shared utilities (`is_safe_path`, `get_active_refs`, `scan_directory`, `write_audit`) previously duplicated across `runtime/archive.py` and `runtime/retention.py`.

### CI Pipeline
`.github/workflows/ci.yml` runs tests on Python 3.10/3.11/3.12 + ruff lint on every push to main/develop and every PR.

## v0.4.1 Changes (Architecture Hardening)

### Orchestrator Single Entry Refactoring
`orchestrator` removed from `_CANONICAL_NODES` — no longer a separate graph node. All intents route through `skill_executor.execute()` → `orchestrate()`. This eliminates duplicate execution and makes the pipeline a true 7-node trace chain (router→context→planner→executor→verifier→composer→memory). Module_call events are still produced via `_record_module_event()` in `llm_orchestrator.py::_execute_module_direct()`.

### Rate Limit per-IP + Endpoint
`backend/core/rate_limit.py` refactored: `_WindowCounter` now uses request timestamp list for accurate sliding window. `_get_limiter()` accepts `client_ip` and includes it in the key (`{client_ip}:{endpoint}:{max_req}:{window}`). `_get_client_ip()` respects `TRUSTED_PROXY` env var. Tests: 7 tests in `harness/test_rate_limit_per_ip.py` (all passed after fix).

### ToolRuntimeContext Propagation
`agent/nodes/llm_orchestrator.py`::_execute_tool() now accepts `state: NetworkAgentState` and passes `ToolRuntimeContext(workspace_id, run_id, trace_id, requested_by)` to `ToolRuntimeClient.invoke()`. This enables workspace isolation and audit tracing for tool executions triggered by the orchestrator. Tests: 7 tests in `harness/test_tool_runtime_context.py`.

### Approval API Admin Boundary
`backend/api/runtime_routes.py` now checks admin privileges via `_require_admin()` before approving/rejecting high-risk tool requests. Admin auth: `X-Admin-Token` header matching `NETWORK_AGENT_ADMIN_TOKEN` env var, or localhost fallback (`127.0.0.1` / `::1`). Tests: 10 tests in `harness/test_approval_guard.py`.

### Test Coverage for v0.4.1 Fixes
| Test File | Count | Coverage |
|-----------|-------|----------|
| `test_rate_limit_per_ip.py` | 7 | Per-IP rate limiting, X-Forwarded-For trust |
| `test_approval_guard.py` | 10 | Admin token auth, localhost fallback, approval status flow |
| `test_tool_runtime_context.py` | 7 | ToolRuntimeContext propagation, policy integration |
| `test_langgraph_trace_node_timing.py` | 21 | Module_call events, node timing |

## Architecture v0.5 (Codex-inspired)

### Context Fragment System
`context/fragments/` — composable context sources with independent token budgets, error isolation, and priority ordering. 5 standard fragments: WorkspaceState, MemoryHits, ModuleRegistry, SkillRegistry, ContextBundle. New fragments can be registered without modifying loader code.

### Task/Turn Model
`agent/task.py`, `agent/turn.py` — explicit state machine for execution lifecycle. Task: CREATED→RUNNING→COMPLETED/FAILED/CANCELLED. Turn: per-LLM-cycle tracking with tool call recording and elapsed timing. Integrated into the orchestrator for agentic loop observability.

### Hook System
`agent/hooks.py` — composable pre/post processing pipeline with 8 event types (PreToolUse, PostToolUse, PreTurn, PostTurn, SessionStart, Stop, PreCompact, PostCompact). Disjunctive result folding (any Deny wins, block overrides stop). Regex matcher support for tool/intent targeting. Integrated at SessionStart, tool execution, and turn completion.

### Context Compaction
`context/compaction.py` — dual-limit token budget (auto-compact at 80%, full window limit). Per-model budgets (MiniMax 64k, GPT-4o 128k). Pre-turn trigger in orchestrator. Session history summarization for old turns.

## Foundation Baseline (historical)

| # | 组件 | 状态 |
|---|------|------|
| 1 | LangGraph Runtime (8 trace nodes) | completed |
| 2 | Registry / Capability / Skill / Module Contract | completed |
| 3 | LLM Settings (MiniMax-M3 default) | completed |
| 3.1 | LLM Runtime v0.5 (invoke_llm unified entry) | completed |
| 3.2 | LLM Runtime v0.5.1 (diagnostics consistency) | completed |
| 4 | Workspace Runtime | completed |
| 5 | Memory Runtime (cleanup_expired + compact) | completed |
| 6 | Run History | completed |
| 7 | Observability / Trace / Timeline | completed |
| 8 | Artifact / File Pipeline | completed |
| 9 | Report / Export Pipeline | completed |
| 10 | Job / Task Runtime | completed |
| 11 | Context Runtime (v0.2 dynamic budget + dedup) | completed |
| 12 | Prompt Runtime | completed |
| 13 | LLM Orchestrator (agentic loop, disabled fallback) | completed |
| 14 | SSE Streaming | completed |
| 15 | Rate Limit Middleware | completed |
| 16 | Context Fragment System (composable, budgeted) | completed |
| 17 | Task/Turn Model (lifecycle tracking) | completed |
| 18 | Hook System (8 events, disjunctive folding) | completed |
| 19 | Context Compaction (dual-limit budget) | completed |
| 20 | Harness Runtime | completed |

## Business Module

当前仅启用一个业务模块：**config_translation**，核心管线为 `translate_bundle`。

| Module | Status | Entry API |
|--------|--------|-----------|
| config_translation | enabled | `POST /api/modules/config-translation/translate` |

## 快速启动

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
| `POST /api/agent/run` | Agent 执行入口（支持 `stream=true` SSE 流式响应） |
| `POST /api/modules/config-translation/translate` | 配置翻译 |
| `POST /api/jobs` | 任务提交 |
| `GET /api/sessions` | 会话列表（按 workspace） |
| `POST /api/sessions` | 创建新会话 |
| `PUT /api/sessions/{id}` | 更新会话（重命名等） |
| `GET /api/sessions/{id}` | 会话详情 + 消息 |
| `POST /api/sessions/{id}/archive` | 归档会话 |
| `POST /api/sessions/{id}/soft-delete` | 软删除会话 |
| `GET /api/runs/recent` | 后端工作区运行历史摘要 |
| `GET /api/runs/{run_id}` | 默认/指定工作区运行详情 |
| `GET /api/workspaces/{id}/history` | 指定工作区运行历史 |
| `DELETE /api/workspaces/{id}` | 删除工作区 |
| `POST /api/workspaces/{id}/rename` | 重命名工作区 |
| `GET /api/agent/status` | Agent 状态 |
| `POST /api/agent/llm/config` | 保存 LLM 配置 |
| `GET /api/agent/llm/config` | 读取 LLM 配置（不返回完整 key） |
| `GET /api/workspaces/{id}/state` | 工作区状态 |
| `GET /api/memory/list` | 记忆列表 |
| `GET /api/runtime/health` | 系统健康诊断 |

## 测试

```bash
pytest harness -q
# 1351 passed, 7 skipped, 0 failed
```

## 目录结构

```
network_agent/
├── agent/                    # Agent 主框架 (LangGraph + LLM)
│   ├── nodes/                # 8 节点: router, context, planner, executor(orchestrator), verifier, composer, memory, tool_planner
│   └── llm/                  # invoke_llm (统一入口), safe_generate (公共 API), provider, policy (NON-BLOCKING), settings, tool_adapter
├── modules/                  # 业务模块
│   └── config_translation/   # translate_bundle 管线
├── skills/                   # Agent 技能包 (adapter → module)
├── memory/                   # JSONL 记忆系统 (redaction + policy + cleanup_expired + compact)
├── workspace/                # 工作区运行时 (state, runs, artifacts)
├── harness/                  # pytest 测试 (1351 tests)
├── frontend/                 # 统一前端
├── backend/                  # Flask API (SSE streaming, rate limit)
│   ├── api/                  # sse.py, rate_limit.py, 路由
│   └── core/                 # limits, paths, rate_limit middleware
├── runtime/                  # 运行时工具 (lifecycle_base, archive, retention)
├── config/                   # LLM 配置 (LLM_setting.json gitignored)
├── context/                  # 上下文压缩器 v0.2 (dynamic budget, dedup)
├── tool_runtime/             # 工具运行时 (regex forbidden patterns)
├── .github/workflows/        # CI pipeline (py3.10-3.12, ruff lint)
├── scripts/                  # 审计/清理工具
└── reports/                  # 审计报告
```

## 下一步

1. Tool / Command Runtime
2. Knowledge / Index Runtime
3. Platform Hardening
4. Business Modules: topology, inspection, knowledge, CMDB

## 安全基线

- LLM 不改 deployable_config，不产生可直接部署的输出
- 不宣称"可直接部署"，不以 AI 能力绕过人工复核
- API key 仅本地存储，API 返回 `key_preview` 不返回完整 key
- 所有 Memory/Workspace/Run/Trace 写入走 redaction + policy 门控
- `config/LLM_setting.json` 权限 600，不进 Git
- Module / Skill 不得私接 LLM
- 跨工作区访问默认拒绝
