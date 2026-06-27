# 设计文档

## 设计哲学

**实用主义**：去掉未使用的脚手架，保留真正工作的功能。一致性优于向后兼容。

**单一真相源**：每个子系统有自己的权威存储，不重复派生状态。

**渐进式增强**：WS 流式优先，HTTP 自动回退。无单点故障。

## 分层架构

```
Skill (业务入口/用户意图) → Module (业务实现/编排) → Tool (工具调用) → Operation (内部动作)
```

每一层有清晰的职责边界：
- **Skill**：理解用户意图，选择合适的 Module
- **Module**：编排多个 Tool 调用，实现业务逻辑
- **Tool**：封装单一能力，有明确的输入/输出契约
- **Operation**：模块内部的具体实现步骤

## 数据流

### Agent 对话流

```
用户输入 → Flask/WS → Agent 引擎 → LLM 推理 → 工具调用 → 结果汇总 → 流式返回
```

### 工具执行流

```
LLM 工具选择 → ToolRouter.dispatch → 权限检查 (requested_by) → 沙箱执行 → 结果返回
```

### 前端渲染流

```
WS 事件 → Zustand store.updateAssistant(msgId, patch) → Virtuoso 重渲染 → DOM 更新
```

废弃了之前 Footer + React state 的双路径渲染，统一为 Zustand + Virtuoso 单路径。

## Session-Job-Run 数据模型

| 实体 | 关系 | 存储 |
|------|------|------|
| Session | 1:1 Job | `workspace/session_store.py` |
| Job | 1:N Run | `jobs/store.py` |
| Run | 独立记录 | `workspace/run_store.py` |
| Artifact | N:M Run/Session | `artifacts/store.py` |

生命周期：Session 创建 → Job 创建 → 每轮对话追加 Run → Session 关闭时 Job 标记完成。删除 Session 时级联清理 Job/Run/Artifact。

## 工具运行时

73 个工具，13 个分类，通过 `tool_runtime/manifest_registry.py` 统一注册。所有工具通过 `DEFAULT_ALLOWED_CALLERS` 常量控制访问权限。

`requested_by` 强制检查（registry.dispatch → client.invoke），缺失时阻断而非静默回退。

## 前端状态管理

Zustand store (`frontend/src/stores/workbench.ts`) 管理消息历史、会话切换、流式状态。

每个消息有 status 字段：`streaming` | `ready` | `error`。流式消息通过 `appendAssistantStreaming` 创建占位，token 到达时通过 `updateAssistant` 更新消息字段，Virtuoso 自动重渲染。
