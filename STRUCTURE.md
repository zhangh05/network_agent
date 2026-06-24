# Network Agent 项目目录结构

```
network_agent/
│
├── agent/                  ← Agent 核心引擎 (538 files)
│   ├── capabilities/       ← 能力注册表 (10 cap: 8 enabled + 2 planned)
│   ├── context/            ← 运行时上下文对象 (snapshot/history/memory/compaction)
│   ├── llm/                ← LLM 客户端 & 调用层
│   ├── modules/            ← 13 业务模块 (artifact/browser/cmdb/code/git/knowledge/...)
│   ├── protocol/           ← 协议定义 (ToolInvocation/message schemas)
│   ├── runtime/            ← Turn Pipeline 执行引擎 (13 stages)
│   │   ├── actions/        ← 操作执行器 (RiskPolicy/ApprovalGate/ActionExecutor)
│   │   ├── cognition/      ← 认知层 (SceneDecision/EvidenceBundle)
│   │   ├── context_pipeline/ ← 上下文管道 (13 stages: init → model → history → tool...)
│   │   ├── memory/         ← 记忆读写策略
│   │   ├── memory_write/   ← 记忆候选提取/去重/规划
│   │   ├── observability/  ← 观测事件收集/导出 TurnTrace
│   │   ├── output/         ← 产出收集/规划/写入/摘要
│   │   ├── response/       ← 回复策略/组合/渲染
│   │   ├── stability/      ← 稳定性门禁
│   │   ├── state/          ← RuntimeState/TaskState/WorkflowState
│   │   ├── tasking/        ← 任务检测/规划/执行
│   │   ├── tool_execution/ ← 工具执行管道 + 重试策略
│   │   ├── tool_planning/  ← ToolPlannerV2 确定性工具规划
│   │   └── truth/          ← 唯一真源 (版本/配置/能力)
│   ├── skills/             ← Skill 系统 (SKILL.md 标准, 复用工作流)
│   └── tools/              ← 工具注册表 & 路由
│
├── backend/                ← Flask API 服务 (:8010)
│   ├── api/                ← REST 路由 (tools/modules/capabilities/health)
│   ├── middleware/          ← CORS/日志中间件
│   └── main.py             ← 入口
│
├── frontend/               ← React/TS 前端 (:5173)
│   └── src/
│       ├── pages/          ← 页面 (CMDB/终端/配置分析)
│       ├── components/     ← 组件 (RemoteTerminal/...)
│       ├── api/            ← API 客户端
│       └── stores/         ← Zustand 状态管理
│
├── tool_runtime/           ← 工具系统核心
│   ├── canonical_registry.py ← 规范工具注册表 (102 tools, handler + schema)
│   ├── client.py           ← 安全执行管道 (policy + executor)
│   ├── schemas.py          ← ToolSpec/ToolInvocation 数据契约
│   └── tool_namespace_data.py ← 工具分类 & namespace 元数据
│
├── registry/               ← 模块/技能/能力注册发现 (声明层)
│   ├── loader.py           ← 加载 module.yaml / skill.yaml → registry
│   └── schemas.py          ← ModuleSpec/SkillSpec/CapabilitySpec
│
├── modules/                ← 模块声明 (module.yaml 元数据, 非实现)
├── skills/                 ← Skill 声明 (SKILL.md 文件)
├── prompts/                ← LLM Prompt 模板 & 渲染引擎
├── config/                 ← LLM Provider 配置 (minimax/anthropic/...)
├── scripts/                ← 运维脚本 (构建/审计/发布)
├── harness/                ← 测试 harness
├── docs/                   ← 文档 & 开发者模板
│
├── context/                ← 统一上下文存储 (JSONL 后端)
│   ├── context_store.py    ← ContextStore 持久化
│   └── unified_retriever.py ← BM25 + CJK 检索
│
├── memory/                 ← Memory 适配层 (包装 ContextStore)
├── storage/                ← 文件级存储 (FileStore, 索引, GC)
├── observability/          ← 可观测性 (Trace/Timeline/EventStore)
├── runtime/                ← 运维工具 (自检/诊断/保留/归档/脱敏)
├── jobs/                   ← 异步长任务管理
├── reports_engine/         ← 报告生成引擎
│
├── workspace/              ← 工作空间管理代码 (manager/session/run/message store)
│
├── data/                   ← 运行时工具数据 (审批/历史, gitignored)
├── logs/                   ← 日志 (gitignored)
├── artifacts/              ← 产出制品 (gitignored)
├── workspaces/             ← 工作空间数据 (sessions/runs/context, gitignored)
│
├── AGENTS.md               ← Agent 行为配置
├── DESIGN.md               ← 架构设计文档
├── README.md               ← 项目说明
├── STRUCTURE.md            ← 本文件 — 目录结构说明
├── requirements.txt        ← Python 依赖
├── start.sh / stop.sh      ← 启停脚本
└── .gitignore
```

## 分层架构

```
┌────────────────────────────────────────────────┐
│  frontend (React UI)  +  backend (Flask API)   │  ← 交互层
├────────────────────────────────────────────────┤
│  agent/ (Turn Pipeline)  +  tool_runtime/      │  ← 核心引擎
├────────────────────────────────────────────────┤
│  agent/modules/ (13 modules)                   │  ← 业务模块
├────────────────────────────────────────────────┤
│  context/ + memory/ + storage/ + observability │  ← 存储 & 观测层
├────────────────────────────────────────────────┤
│  registry/ + modules/ + skills/ + prompts/     │  ← 声明 & 配置层
└────────────────────────────────────────────────┘
```

## 核心概念

| 概念 | 定义处 | 示例 |
|------|--------|------|
| **Tool** | `tool_runtime/canonical_registry.py` | network.ssh, git.status, code.search |
| **Capability** | `agent/capabilities/builtin.py` | cmdb, network_device, coding, pcap_analysis |
| **Module** | `agent/modules/*/` | agent/modules/cmdb/, agent/modules/git/ |
| **Skill (Workflow)** | `skills/builtin/*/SKILL.md` | git_commit_push, code_review |
| **Namespace** | `tool_runtime/tool_namespace_data.py` | git → status/diff/log/commit/push |
