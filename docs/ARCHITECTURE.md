# Architecture

## 系统结构

```text
Browser
  -> React / Vite
  -> Flask /api
  -> AgentApp
  -> RuntimeLoop
     -> ToolCategoryRouter
     -> ToolPlanner
     -> MessageBuilder + SafeContext
     -> LLM
     -> ToolRouter
     -> ToolRuntime
  -> workspace storage
```

## Agent Runtime

| 路径 | 职责 |
|------|------|
| `agent/runtime/loop.py` | 驱动 LLM、工具调用和最终回复 |
| `agent/runtime/tool_category_router.py` | 根据意图信号选择工具类别与候选工具 |
| `agent/runtime/tool_planner.py` | 生成并校验工具计划 |
| `agent/runtime/context_builder.py` | 组装知识、记忆和安全上下文 |
| `agent/runtime/prompts.py` | 构建系统提示词 |
| `agent/llm/` | Provider 配置、调用、重试和输出清洗 |

## Tool Runtime

| 路径 | 职责 |
|------|------|
| `tool_runtime/canonical_registry.py` | 当前工具定义与 handler 绑定 |
| `tool_runtime/tool_namespace_data.py` | 模型可理解的工具名称空间 |
| `tool_runtime/capability_actions.py` | 能力与工具动作映射 |
| `tool_runtime/action_class.py` | read/write/mutate/execute/external 分类 |
| `tool_runtime/path_security.py` | 工作区路径和符号链接检查 |
| `tool_runtime/general_tools/` | 通用工具 handler |

```text
ToolInvocation
  -> schema validation
  -> permission and approval policy
  -> path validation
  -> handler
  -> audit and redaction
  -> ToolResult
```

## 能力模块

能力模块位于 `agent/modules/`。知识能力只由 `agent/modules/knowledge/` 提供，覆盖文档导入、分块、索引、来源管理和检索。

## 存储

```text
workspaces/{workspace_id}/
├── files/
│   ├── upload/            上传文件
│   └── agent/             Agent 输出
├── sys/
│   ├── knowledge/         sources、chunks 和索引
│   ├── audits/            审计记录
│   ├── archives/          归档
│   ├── reviews/           评审 sidecar
│   ├── tmp/               受控执行临时目录
│   └── usage/             Token 用量
├── sessions/              会话和消息
└── runs/                  运行记录与 trace
```

所有运行数据均为本地状态，不属于源码发布内容。

## 前端

`frontend/src/app/App.tsx` 定义页面路由，`frontend/src/api/index.ts` 定义 API 调用，Zustand stores 管理会话、工作台和界面状态。

报文分析的页面恢复链路为：

```text
FileManager pcap record
  -> metadata.session_id
  -> /packet?sid={session_id}
  -> GET /api/pcap/session/{session_id}
  -> filter and align
```
