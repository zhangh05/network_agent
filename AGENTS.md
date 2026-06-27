# AGENTS.md — AI 编码助手指南

本文件为 AI 编码助手（Claude、CodeBuddy 等）提供项目约定和工作流。

## 项目约束

### 必须遵守

1. **Backend 为 API 契约唯一来源**。前端类型从后端响应派生，不自行定义。
2. **workspace_id 全局统一**。所有 API 需要 workspace_id，不提供默认值，非法/空返回 400。
3. **增量 PR + Merge Commit**。不要 squash，不要 rebase。
4. **pytest 全绿后再合并**。`harness/` 目录下 `pytest` 全部通过。
5. **禁止 `git add -A` 把运行时数据入库**。memory/*.json、logs/* 等不可提交。

### 代码风格

- Python 代码使用英文编写（变量名、注释、文档字符串）
- 对话/文档使用简体中文
- 严禁裸 `except:`，必须写 `except Exception:`
- 不要使用 Tailwind CSS（项目中未安装），使用项目内 CSS 类名或内联 style

### 安全规则

- 密钥必须通过 `workspace/redaction.py` 脱敏后再写入日志/存储
- Python 沙箱禁止 `open()`、`eval()`、`exec()`、`__import__`
- 工具调用强制 `requested_by` 检查

## 工作流

```
1. 了解任务 → 检查 HEAD, CI, 工作区洁净度
2. 修改代码 → 小步提交 (fix → commit → verify)
3. 运行 pytest → 全绿
4. 提交推送 → git push origin main
5. 重启服务 → bash stop.sh && bash start.sh
```

## 关键文件索引

| 关注点 | 文件 |
|--------|------|
| Agent 引擎入口 | `agent/app/service.py` |
| Flask 入口 | `backend/main.py` |
| WebSocket | `backend/ws/agent_ws.py` |
| 工具注册 | `tool_runtime/manifest_registry.py` |
| Job 状态机 | `jobs/manager.py` |
| Session 存储 | `workspace/session_store.py` |
| 前端状态 | `frontend/src/stores/workbench.ts` |
| 前端主页 | `frontend/src/pages/AgentWorkbench/AgentWorkbench.tsx` |
| API 路由 | `backend/api/*.py` |
| 测试 | `harness/test_*.py` |
