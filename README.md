# Network Agent

面向网络工程场景的本地 LLM Agent。项目由 Flask API、React/TypeScript 前端、Agent Runtime 和受策略约束的工具运行时组成。

## 核心能力

- 对话工作台：理解用户意图，规划并调用合适的工具。
- 文件管理：统一管理报文、分析结果、知识、记忆、制品和通用文件。
- 报文分析：解析 `pcap`、按连接筛选并执行 TCP 序列对齐。
- 知识检索：导入文档、分块索引、BM25 检索和来源追踪。
- 网络任务：配置解析、配置翻译、接口与路由提取。
- 运行治理：审批、审计、作业、诊断、归档和保留策略。

## 快速开始

要求 Python 3.12+ 和 Node.js 18+。

```bash
python3 -m pip install -r requirements.txt
python3 backend/main.py --host 0.0.0.0 --port 8010

cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

浏览器访问 `http://localhost:5173`。Vite 将 `/api` 请求代理到 `http://127.0.0.1:8010`。

## 运行链路

```text
React/Vite
  -> POST /api/agent/message
  -> AgentApp / RuntimeLoop
  -> ToolCategoryRouter / ToolPlanner
  -> LLM
  -> ToolRouter / ToolRuntime
  -> workspace persistence
```

模型只能看到当前注册表允许暴露的工具。工具参数在执行前经过 schema、权限、路径和审批校验，执行结果经过审计与脱敏后返回对话。

## 项目结构

```text
backend/                    Flask 入口和 API 路由
agent/                      Agent、LLM、规划器和能力模块
agent/modules/knowledge/    当前知识库实现
tool_runtime/               工具注册、策略、执行和审计
workspace/                  工作区、会话和运行记录
artifacts/                  制品模型与存储
memory/                     记忆检索与写入
runtime/                    诊断、归档和保留策略
frontend/                   React/TypeScript 前端
harness/                    后端和契约测试
docs/                       架构、API、运行时和前端文档
```

## 数据布局

```text
workspaces/{workspace_id}/
├── files/
│   ├── upload/             用户上传文件
│   └── agent/              Agent 生成文件
├── sys/                    知识索引、审计、临时数据和内部状态
├── sessions/               会话元数据与消息
└── runs/                   Agent 运行记录
```

运行数据、本地 LLM 配置、API Key、缓存和构建产物由 `.gitignore` 排除。

## LLM 配置

在系统设置页配置并激活 Provider。当前支持 MiniMax-M3 等 OpenAI-compatible 模型。每个 Provider 的本地配置保存在 `config/providers/`，该目录不会提交到 Git。

## 验证

```bash
python3 -m pytest harness -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

更多说明：

- [架构](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [能力与工具](docs/CAPABILITIES_AND_TOOLS.md)
- [运行时](docs/RUNTIME.md)
- [前端](docs/FRONTEND.md)
- [开发交接](AGENTS.md)
