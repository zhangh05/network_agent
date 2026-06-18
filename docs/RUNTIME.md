# Runtime

`POST /api/agent/message` 创建一次 Agent turn。Runtime 负责理解意图、准备上下文、规划工具、执行工具并生成最终回复。

## Turn 流程

```text
user message
  -> session and workspace context
  -> category routing
  -> validated tool plan
  -> LLM invocation
  -> governed tool execution
  -> tool result compaction
  -> final response
  -> message, run and trace persistence
```

## 工具治理

- Agent must not directly call arbitrary tools. Module orchestrates `ToolInvocation` requests through `ToolRouter` and `ToolRuntime`.
- Skill must not bypass Module policy or invoke handlers directly.
- The public Tool HTTP API is policy and approval gated.
- 模型只能调用 canonical registry 中标记为可见的工具。
- 参数必须通过工具 schema。
- write、mutate、execute、external 和高风险动作进入审批策略。
- 文件路径必须位于允许的工作区目录。
- 工具输入输出写入审计记录，并在回到模型前脱敏和压缩。
- `exec` 工具保留，但执行仍受审批、命令策略、超时和工作目录限制。
- `ssh`、`telnet`、`snmp` 和 `nmap` 远端操作默认禁止；只有未来经过注册、权限、审批和审计治理的专用能力才能开放。

## 上下文

`agent/runtime/context_builder.py` 组合会话历史、工作区状态、知识检索和记忆检索。知识结果和工具结果在进入提示词前执行注入扫描和安全摘录。

## 持久化

- 会话与消息：`workspaces/{workspace_id}/sessions/`
- 运行与 trace：`workspaces/{workspace_id}/runs/`
- 文件：`workspaces/{workspace_id}/files/`
- 内部状态：`workspaces/{workspace_id}/sys/`

这些目录是运行时数据，不提交到 Git。

## 诊断

```text
GET /api/runtime/health
GET /api/runtime/selfcheck
GET /api/runtime/summary
GET /api/workspaces/{workspace_id}/selfcheck
```

归档和保留操作均先提供 preview，再执行 apply，并保存审计记录。
