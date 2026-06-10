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
