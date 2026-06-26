# Network Agent 项目目录结构 (v3.9)

```
network_agent/
│
├── agent/                  ← Agent 核心引擎
│   ├── capabilities/       ← 能力注册
│   ├── context/            ← 运行时上下文
│   ├── llm/                ← LLM 客户端
│   ├── modules/            ← 业务模块 (13 categories)
│   ├── protocol/           ← 协议定义
│   ├── runtime/            ← Turn Pipeline 执行引擎
│   │   ├── capability_routing/ ← 能力路由 (semantic + keyword)
│   │   ├── context_pipeline/   ← 上下文管道
│   │   ├── memory_write/       ← 记忆候选提取/去重
│   │   ├── tool_execution/     ← 工具执行管道 + 重试
│   │   └── ...
│   └── tools/              ← 工具系统
│
├── backend/                ← Flask API (:8010)
│   ├── api/                ← REST 路由
│   └── main.py             ← 入口
│
├── frontend/               ← React/TS 前端
│   └── src/
│       ├── pages/          ← 页面 (Workbench/Runs/Knowledge/...)
│       ├── components/     ← 组件
│       ├── api/            ← API 客户端
│       ├── layouts/        ← 布局 (Sidebar/Inspector/AppLayout)
│       └── stores/         ← Zustand 状态管理
│
├── tool_runtime/           ← 工具系统核心
│   ├── canonical_registry.py   ← 规范注册表 (73 tools)
│   ├── tool_namespace_data.py  ← 工具 namespace 元数据
│   ├── tool_governance.py      ← 工具治理
│   ├── capability_actions.py   ← 能力动作映射
│   └── schemas.py              ← 数据契约
│
├── context/                ← 统一上下文存储
├── memory/                 ← Memory 适配层
├── storage/                ← FileStore
├── observability/          ← Trace/EventStore
├── workspace/              ← 工作空间管理
├── jobs/                   ← 异步任务
├── reports_engine/         ← 报告生成
├── prompts/                ← LLM Prompt 模板
├── harness/                ← 测试
├── docs/                   ← 文档
├── scripts/                ← 运维脚本
│
├── AGENTS.md               ← Agent 行为配置
├── DESIGN.md               ← 架构设计
├── README.md               ← 项目说明
└── STRUCTURE.md            ← 本文件
```

## 分层架构

```
┌─────────────────────────────────────────────┐
│  frontend (React) + backend (Flask API)     │  ← 交互层
├─────────────────────────────────────────────┤
│  agent/ (Turn Pipeline) + tool_runtime/     │  ← 核心引擎
├─────────────────────────────────────────────┤
│  agent/modules/ (13 categories)             │  ← 能力模块
├─────────────────────────────────────────────┤
│  context/ + memory/ + storage/              │  ← 存储 & 观测层
├─────────────────────────────────────────────┤
│  prompts/ + config/ + registry/             │  ← 声明 & 配置层
└─────────────────────────────────────────────┘
```

## 核心概念

| 概念 | 定义处 | 示例 |
|------|--------|------|
| **Tool** | `tool_runtime/canonical_registry.py` | exec.run, git.status, code.search |
| **Capability** | `agent/capabilities/` | device, exec, coding, pcap_analysis |
| **Category** | `tool_runtime/tool_namespace_data.py` | exec → run/python/slash, git → status/diff/log |
| **Inspector** | `frontend/src/layouts/Inspector.tsx` | 右侧面板，显示 turn 执行细节 |
