# Network Agent

Network Agent 是一个面向网络运维场景的本地 AI Agent 工作台。当前架构只保留一套运行时、一套工具边界和一套业务能力目录：前端通过 Flask API 与 WebSocket/SSE 驱动对话，后端由 `AgentApp -> SSOTRuntimeEngine -> ToolRuntimeClient` 统一执行，工具统一收敛为 22 个 canonical tool。

> **运行环境**：Python 3.12+ / Node.js 18+ / macOS 或 Linux。

## 快速启动

```bash
bash start.sh
```

默认地址：

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8010`

停止服务：

```bash
bash stop.sh
```

## 当前架构

```mermaid
flowchart LR
  UI["React Workbench"] --> API["Flask API / WS / SSE"]
  API --> App["AgentApp"]
  App --> SSOT Runtime["SSOTRuntimeEngine"]
  SSOT Runtime --> Planner["Planner LLM"]
  SSOT Runtime --> DAG["Execution DAG"]
  DAG --> Client["ToolRuntimeClient"]
  SSOT Runtime --> Finalizer["Finalizer LLM"]
  Client --> Policy["Manifest + Policy Gate"]
  Policy --> Exec["ToolExecutor"]
  Exec --> Store["Workspace / Artifact / Memory / Trace Stores"]
```

核心链路只有一条：`AgentApp -> SSOTRuntimeEngine -> ToolRuntimeClient -> ToolExecutor`。SSOT Runtime 负责单次规划、DAG 并行调度和最终答复；任何工具调用都必须携带 `requested_by`，必须命中 `CapabilityManifest`，并且必须通过 caller gate、风险策略、脱敏和审计。

## 核心模块

| 模块 | 当前职责 |
| --- | --- |
| `backend/` | Flask 入口、REST API、WebSocket、SSE |
| `frontend/` | React/Vite 工作台、会话、时间线、设置、资产、诊断 |
| `agent/app/` | AgentApp 门面、SessionManager、AgentThread |
| `agent/runtime/` | SSOT Runtime 适配、AgentResult 投影、持久化、hook |
| `tool_runtime/` | 22 个 canonical tool、manifest、policy、executor、redaction |
| `agent/capabilities/` | 12 个业务能力目录，只描述能力，不注册工具 |
| `workspace/` | session/run/message/memory/workspace 数据边界 |
| `artifacts/` | 制品生命周期与内容存储 |
| `observability/` | trace/event 记录 |
| `harness/` | 后端架构和契约测试 |

## 22 个 Canonical Tools

`agent.manage`, `browser.manage`, `code.search`, `config.manage`, `data.manage`, `device.manage`, `exec.run`, `git.manage`, `knowledge.manage`, `memory.manage`, `pcap.manage`, `report.manage`, `skill.manage`, `system.manage`, `text.analyze`, `web.manage`, `workspace.artifact`, `workspace.document.pdf.extract_text`, `workspace.file`, `workspace.filestore`, `workspace.metadata.get`

工具名、manifest 和 registry 必须三方一致。不要添加别名，不要恢复旧工具名，不要让 handler 绕过 `ToolRuntimeClient`。

## Workspace 与数据

- `workspace_id` 是所有运行时数据的隔离边界。
- API 入参缺失或非法 `workspace_id` 必须返回 400。
- `workspaces/default/` 是本地默认工作区数据。
- `workspaces/_runtime/` 保存 durable task、checkpoint、trajectory 等运行时状态。
- `config/providers/` 与 `config/llm.local.yaml` 保存本机 LLM 配置，不入库。

## 验证命令

```bash
python3 -m pytest harness/test_business_capability_catalog.py harness/test_v394_no_legacy_tool_ids.py -q
python3 -m pytest harness/test_functional_contract_fixes.py -q
npm --prefix frontend run typecheck
```

只在需要全量回归时运行完整 harness；日常修复以契约测试和受影响路径测试为准。
