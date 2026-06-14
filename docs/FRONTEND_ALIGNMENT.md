# FRONTEND_ALIGNMENT.md — v2.1.2 Frontend/Tool Capability Mapping

## 1. 操作按钮与工具能力映射

| 按钮文字 | 触发行为 | 对应工具 | 数据流 |
|---|---|---|---|
| **查看运行详情** | 打开右侧 Inspector 抽屉 | `run.get_summary` + `run.list_recent` | 展示本轮 tool_decision, candidate_tools, blocked_by |
| **记住结论** | 触发 memory.confirm/create 流程 | `memory.confirm` / `memory.create` | POST `/api/memory/confirm` → 记忆持久化 → RAG 召回 |
| **存为知识** | 触发 knowledge.upload 流程 | `knowledge.index_artifact` / `artifact.save_result` | POST `/api/knowledge/upload` → 知识索引 → 可检索 |
| **来源 ({n})** | 打开 Inspector 查看引用 | `knowledge.search`, `memory.search`, `web.search` | 显示 K/M 引用来源 |

## 2. Inspector 工具调用面板（v2.1.2 新增）

### 工具决策 (tool_decision)

新增 "工具决策" 折叠面板，显示：

- **需要工具 / 无需工具** - 来自 `result.tool_decision.needed`
- **已选工具** - `result.tool_decision.selected_tools[]` 的 badge 列表
- **被阻止原因** - `result.tool_decision.blocked_by[]`
- **审批状态** - `result.tool_decision.approval_required` 的警告标识
- **原因** - `result.tool_decision.reason` 的说明文本

### 无工具调用原因 (no_tool_reason)

无工具调用时显示可读原因：
- `no_model_visible_tools` → "当前 turn 没有可见工具"
- `tools_not_called` → "LLM 未选择工具调用（可能需要调整 prompt）"
- `tools_not_needed` → "当前问题可直接回答，无需工具"
- `blocked_by_hook` → "Turn 被 hook 阻止"
- `token_limit_exceeded` → "上下文超限"
- `provider_error` → "LLM 服务不可用"

## 3. RunsPage 运行详情

新增 tool_decision JSON 和 no_tool_reason badge 展示。

## 4. 工具分类标签 (toolLabel)

```
config_translation. → "配置翻译"
knowledge.          → "知识检索"
artifact.           → "制品操作"
review.             → "评审流转"
runtime.            → "运行诊断"
shell.              → "Shell 命令"
powershell.         → "PowerShell"
python.             → "Python"
web.                → "Web 查询"
file.               → "文件操作"
memory.             → "记忆"
session.            → "会话"
agent.              → "子 Agent"
parser.             → "配置解析"
text.               → "文本处理"
report.             → "报告"
默认                 → "工具调用"
```

## 5. 审批弹窗 (ApprovalDialog)

- 1 秒轮询 `GET /api/agent/approvals/pending`
- 按钮: **允许** (primary, autoFocus) / **拒绝**
- 统一审批话术在 system prompt (P3) 中定义

## 6. 空状态 / 边界提示

| 状态 | 文字 |
|------|------|
| 无工具可用 | "当前 turn 没有可见工具" |
| 无工具调用 | 显示 no_tool_reason 可读文案 |
| 需审批 | ⚠ badge + blocked_by 说明 |
| LLM 离线 | "LLM 功能未启用" |
| API Key 问题 | "API 密钥未配置" |
| Provider 超时 | "模型请求超过 30 秒未返回" |

## 7. 数据流（完整链路）

```
用户输入
  → POST /api/agent/message
  → AgentResult { tool_decision, no_tool_reason, tool_calls[], ... }
  → Workbench store (appendAssistant)
  → ResultInline 渲染:
    ├── toolCallSummary()
    ├── [查看运行详情] → Inspector:
    │   ├── 工具决策 (tool_decision)
    │   ├── 工具调用 (ToolCallCard)
    │   └── no_tool_reason
    ├── [记住结论] → memoryApi.confirm()
    └── [存为知识] → knowledgeApi.upload()
```
