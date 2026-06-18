# Agent 系统

## RuntimeLoop

Codex-style agentic loop，每轮最多 8 个工具调用步骤：

```
用户消息 → 意图分析 → 工具规划 → LLM 决策 → 工具执行 → 结果注入 → LLM 回复
                                     ↑                         │
                                     └─────── 循环(最多8步) ────┘
```

### 执行流程

1. **build_turn_context** — 构建 TurnContext（session/history/safe_context）
2. **tool_planner** — 基线工具 + 意图专属工具 → candidate_tools
3. **message_builder** — 组装 LLM messages（system + history + context + user）
4. **LLM sampling** — 流式调用 MiniMax M3
5. **tool_dispatch** — 执行工具调用，结果注入下一轮 messages
6. **enrich_metadata** — 将 memory/knowledge hit counts 写入 AgentResult

### 安全检查链

```
RAG 注入扫描 → argument_source 追踪 → action_class 过滤 → 审批门控
```

## 工具执行

### 注册

`tool_runtime/canonical_registry.py` 定义所有 104 个工具的 handler、input_schema、权限。

### 调用

```python
ToolInvocation(
    tool_id="web.search",
    arguments={"query": "OSPF RFC"},
    workspace_id="default",
    run_id="...",
)
→ handler(inv) → {"ok": True, "results": [...]}
```

### 审批

高危工具（host.shell.exec、host.python.exec）触发前端审批弹窗，用户确认后执行。

## Session 管理

- 每个 session 独立的 message history
- SessionMessageStore 持久化到 `workspaces/{ws}/sessions/{sid}/messages/`
- 支持 checkpoint/rewind/export

## 子代理

`agent.spawn` 和 `agent.team.run` 支持多代理协作，但当前主要用单 agent 模式。
