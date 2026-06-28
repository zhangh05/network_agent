# 架构概览

## 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend (React)                     │
│  Zustand Store → Virtuoso → renderMsg → AgentWorkbench   │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / WebSocket
┌───────────────────────▼─────────────────────────────────┐
│                   Backend (Flask)                         │
│  main.py → api_routes → agent_routes / session_routes     │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                   Agent 引擎                              │
│  AgentService → TurnRunner → LLM → ToolRouter            │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                   Tool Runtime                            │
│  ToolRuntimeClient → 沙箱执行 → 返回结果                  │
│  73 tools, 13 categories                                 │
└─────────────────────────────────────────────────────────┘
```

## 层间通信

| 方向 | 协议 | 格式 |
|------|------|------|
| Frontend → Backend | HTTP REST | JSON |
| Frontend ↔ Backend | WebSocket | JSON 流 |
| Backend → Agent | Python 直接调用 | AgentResult |
| Agent → Tool Runtime | Python 直接调用 | ToolInvocation → ToolResult |

## Agent 引擎内部

```
AgentService.evaluate()
  → TurnRunner.run_turn()
    → ContextBuilder 构建上下文
    → LLM 推理 (MiniMax M3)
    → 解析 function_call
    → ToolRouter.dispatch() → 沙箱执行
    → 结果注入 Context → 下一轮推理
    → 循环直到 no function_call
  → 组装 AgentResult
```

## 工具运行时内部

```
ToolRuntimeClient.invoke()
  → requested_by 校验
  → Manifest.allowed_callers 检查
  → Manifest.audit_level 分级审计
  → 根据 tool_id 分发到对应 Handler
  → exec.run(action=python|shell) / HTTPS handlers / module adapters
  → 结果脱敏 (redaction)
  → 返回 ToolResult
```

## 存储抽象

```
Application Layer (Flask, Agent)
  │
  ├─ FileStore (storage/store.py)    → 文件级抽象 (read/write/delete)
  ├─ ArtifactStore (artifacts/)       → 制品生命周期
  ├─ JobStore (jobs/store.py)        → Job 持久化
  ├─ SessionStore (workspace/)       → Session 元数据
  ├─ RunStore (workspace/run_store.py) → Run 记录
  └─ ContextStore (context/)         → JSONL 知识存储
```
