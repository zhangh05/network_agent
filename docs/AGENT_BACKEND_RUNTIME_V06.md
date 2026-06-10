# Agent Backend Runtime v0.6 — Codex-style Rewrite

## 1. 背景

Agent Backend v0.6 将 Agent 运行时从 LangGraph 7-node pipeline 重构为 Codex-style
Thread/Session/Turn/RuntimeLoop 架构。旧 7-node pipeline 迁入 `agent/legacy/`，保留向后兼容。

## 2. 为什么废弃旧 graph/nodes

| 旧架构问题 | v0.6 解决 |
|-----------|----------|
| 7-node pipeline 扩展性差 | Thread/Session/Turn 模型天然支持多轮、多 tool call |
| composer 单独处理 LLM 输出 | invoke_llm() 统一入口，tool_calls 自动回灌 |
| llm_orchestrator 嵌入 skill_executor | RuntimeLoop 统一编排 |
| 工具执行路径分散 | ToolRouter 集中路由 |
| 上下文注入手动拼接 | RuntimeSnapshot 自动注入 |
| assistant_chat deterministic-first | assistant_chat 默认 with-tools |

## 3. 新架构总览

```
API (POST /api/agent/message)
  → AgentApp (agent/app/)
    → AgentThread.submit()
      → AgentSession.submit()
        → AgentTurn
          → RuntimeLoop.run_turn()
            → invoke_llm(safe_context, tools)
              → [if content] → final_response (turn_finished)
              → [if tool_calls] → ToolRouter.dispatch()
                → ToolRuntimeClient.invoke()
                → ToolResultMessage → LLM follow-up
          → turn_finished / turn_failed
        → AgentResult.to_dict()
```

## 4. Thread / Session / Turn

- **AgentThread**: 一次用户提交对应一个 thread
- **AgentSession**: 持久化对话上下文，管理多 thread
- **AgentTurn**: 单次 LLM 交互 + 可能的 tool call loop
- Turn 状态机: CREATED → RUNNING → COMPLETED / FAILED / TIMEOUT

## 5. RuntimeLoop

- `run_turn()` 是 turn 执行的核心循环
- 每次循环: invoke_llm() → 检查 content/tool_calls → dispatch/return
- max_steps 限制 tool call 往返次数（默认 10）
- 超过 max_steps 返回 warning + partial result

## 6. ToolRouter

- `model_visible_tools()`: 返回 LLM 可用的工具列表（过滤 disabled/forbidden）
- `model_visible_specs()`: 返回 LLM function_call 格式的 tool specs
- `dispatch()`: 路由 tool_call 到 ToolRuntimeClient.invoke()
- 安全名称映射: `runtime__health` → `runtime.health`

## 7. Skill / Module Registry

### SkillRegistry
| Skill | Status |
|-------|--------|
| assistant_chat | enabled |
| config_translation | enabled |
| knowledge_query | enabled |
| topology | planned |
| inspection | planned |
| cmdb | planned |

### ModuleRegistry
| Module | Status |
|--------|--------|
| config_translation | enabled |
| knowledge | enabled |
| topology | planned |
| inspection | planned |
| cmdb | planned |

## 8. RuntimeSnapshot

- `RuntimeSnapshot.to_prompt_text()` 注入到 LLM prompt
- 区分: 当前可用工具 / 启用技能 / 启用模块 / 规划中 (planned, NOT callable)
- "工具呢？" 问题现在基于 RuntimeSnapshot 回答，不再使用静态产品介绍

## 9. Events / Trace / Rollout

### 每个 turn 的最小事件集
- turn_started
- context_built
- model_request_started
- model_response_received
- assistant_message
- turn_finished

### 工具调用 turn 额外事件
- tool_call_started
- tool_call_finished / tool_call_failed

### TraceRecorder 记录
- model_request / model_response
- tool_call / tool_result

### RolloutRecorder
- persist_turn 基础实现

## 10. API

### POST /api/agent/message (v0.6 NEW)

Request:
```json
{
  "session_id": "...",
  "workspace_id": "default",
  "message": "...",
  "metadata": {}
}
```

Response (AgentResult.to_dict()):
```json
{
  "ok": true,
  "final_response": "...",
  "session_id": "...",
  "turn_id": "...",
  "trace_id": "...",
  "events": [...],
  "tool_calls": [...],
  "warnings": [...],
  "errors": [],
  "metadata": {}
}
```

### POST /api/agent/run (legacy, backward compat)

Still supported through `agent/legacy/graph.run_agent()`. Response format matches pre-v0.6 contract.

## 11. 测试与门控

- `harness/test_agent_backend_runtime_v06.py`: 15 tests (core v0.6 runtime)
- `harness/test_agent_backend_runtime_v061.py`: 25 tests (v0.6.1 stabilization)
- Focused regression: `pytest harness -q -k "agent_backend_runtime or llm or tool_runtime or approval or redaction or config_translation or knowledge"` — 656 passed
- Full regression: `pytest harness -q` — 1502 tests
- Gate: all core + focused regression must pass

## 12. v0.6.1 Stabilization (2026-06-10)

### Fixes
- Registered `/api/agent/message` route in `backend/main.py`
- Added missing `events` field to AgentResult.to_dict()
- Added `events_for_turn_dicts()` to EventRecorder
- Added `_collect_events()` helper to RuntimeLoop
- All AgentResult paths now include events

### Legacy Import Isolation Verified
- `agent/app/` — no agent.legacy imports ✅
- `agent/core/` — no agent.legacy imports ✅
- `agent/runtime/` — no agent.legacy imports ✅
- `agent/tools/` — no agent.legacy imports ✅
- `agent/skills/` — no agent.legacy imports ✅
- `agent/modules/` — no agent.legacy imports ✅
- `backend/api/agent_routes.py` — no agent.legacy imports ✅

### Events Observability Verified
Every turn: turn_started, context_built, model_request_started, model_response_received, assistant_message/turn_failed, turn_finished ✅

### No Regressions
Tool count: 55 (unchanged). No new business tools. assistant_chat with-tools default.

## 13. 迁移说明

### 从旧代码迁移

1. **不要直接 import agent.graph 或 agent.nodes.\***: 这些已废弃
2. **使用 AgentApp.submit_user_message()**: 替代旧的 run_agent()
3. **测试更新**: 旧 pipeline 测试已更新路径到 agent/legacy/，或删除/改写
4. **API 迁移**: 新客户端使用 `/api/agent/message`，旧客户端继续使用 `/api/agent/run`

### 目录变化

| 旧路径 | 新路径 | 状态 |
|--------|--------|------|
| agent/graph.py | agent/legacy/graph.py | 废弃 |
| agent/nodes/*.py | agent/legacy/*.py | 废弃 |
| agent/nodes/tool_planner.py | agent/nodes/tool_planner.py | 废弃（不再调用） |
| - | agent/app/ | 新增 (v0.6) |
| - | agent/runtime/ | 新增 (v0.6) |
| - | agent/tools/ | 新增 (v0.6) |
| - | agent/audit/ | 新增 (v0.6) |
| - | backend/api/agent_routes.py | 新增 (v0.6 API) |

## 14. Post-v0.6 Runtime Consumers (v0.6.1 ~ v0.7.1)

> 本节说明 v0.6 之后的下游消费者。Runtime 底座本身在 v0.6.1 / v0.6.2 / v0.6.3 / v0.7 / v0.7.1 各版本中**未发生主链破坏性变更**，仅围绕稳定性、tool routing 和 capability 接入做增量。

### 14.1 v0.6.1 Stabilization (2026-06-10)
- 路由注册：`/api/agent/message` 在 `backend/main.py` 中正式注册
- `AgentResult.to_dict()` 补 `events` 字段
- `EventRecorder.events_for_turn_dicts()` / `RuntimeLoop._collect_events()` 辅助
- 25 stabilization tests
- **Runtime 主链未变**

### 14.2 v0.6.2 Stabilization (2026-06-10)
- rate_limit 测试隔离：`RATE_LIMIT_DISABLED` 跨测试污染修复
- 新增 `clear_rate_limit_state_for_tests()` + monkeypatch fixtures
- provider timeout 诊断：URLError → `provider_timeout`，`retryable=True`
- RuntimeLoop 中文友好超时消息
- **Runtime 主链未变**

### 14.3 v0.6.3 Hardening (2026-06-10)
- `default_runtime_services` 从 ToolRuntime catalog 构建真实 ToolRouter
- `ToolRouter.build_tool_call` 强制 `llm_name_map` 白名单（未知 tool → `UnknownToolCallError`）
- `RuntimeSnapshot` 区分 `total_tool_count` / `visible_tool_count`
- System prompt 升级为 Runtime Contract（`agent/runtime/prompts.py`）
- max_steps AgentResult 新增 `metadata.terminal_reason / partial / steps`
- 20 hardening tests
- **Runtime 主链未变**

### 14.4 v0.7 Capability Layer Phase 1 (2026-06-10)
- 在 RuntimeLoop 之下挂入 Capability Layer
- `agent.modules.config_translation.service.translate_config()` 注册为 tool `config_translation.translate_config`
- `agent.modules.knowledge.service.query_knowledge()` 注册为 tool `knowledge.query`
- Tool count: 55 → **57**
- topology / inspection / cmdb 仍 planned（**未注入、未暴露**）
- 21 capability tests
- **Runtime 主链未变；ToolRouter / ToolRuntime 调用路径不变**

### 14.5 v0.7.1 Capability Quality & Artifacts (2026-06-10)
- `translated_config` 保存为 artifact（`authoritative=false, deployable_config=false`）
- `manual_review_items` 结构化（item_id / severity / category / line_no / reason / requires_human_review …）
- knowledge `source_summary`（最多 5 条，snippet ≤ 200 字符）
- `RuntimeLoop.run_turn()` 增强 `all_tool_results`（`call_id`, `artifacts`, `source_count`, `manual_review_count`, `errors`, `warnings`, `metadata`）
- `ToolResultMessage.content` 1000 → 2000 字符，附 `artifact_count` + 前 3 个 artifact 摘要 + `source_summary` + `manual_review_count`
- 20 capability artifact / source tests
- 累计 v0.7/v0.7.1 capability tests: **41/41 passed**
- **Runtime 主链未变；ToolRouter / ToolRuntime 调用路径不变**

### 14.6 消费者清单（v0.6 底座 + 增量）

| Consumer | 接入点 | 引入版本 | 文档 |
|----------|--------|---------|------|
| `config_translation.translate_config` | ToolRouter → ToolRuntimeClient | v0.7 | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §3-§6 |
| `knowledge.query` | ToolRouter → ToolRuntimeClient | v0.7 | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §7-§9 |
| `translated_config` artifact | `artifacts.store.save_artifact` | v0.7.1 | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §5 |
| knowledge `source_summary` | RuntimeLoop 反馈 | v0.7.1 | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §8-§9 |
| `manual_review_count` | RuntimeLoop 反馈 | v0.7.1 | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §6, §9 |
| planned modules (`topology` / `inspection` / `cmdb`) | — | planned (NOT injected) | [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) §10 |

### 14.7 不变量（v0.6 → v0.7.1 一直保持）

- 主链调用路径：`API → AgentApp → AgentThread → AgentSession → AgentTurn → RuntimeLoop → invoke_llm`
- 工具执行唯一入口：`ToolRouter → ToolRuntimeClient`
- 模型名称映射：`. ↔ __`，由 `ToolRouter.llm_name_map` 集中维护
- 高危工具白名单 + approval_id 鉴权
- `config.push` / 真实设备执行 永久禁止
- planned 模块永不注入，永不允许 LLM 调用
