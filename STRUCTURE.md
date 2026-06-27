# 目录结构

```
network_agent/
├── start.sh                    # 启动脚本
├── stop.sh                     # 停止脚本
├── requirements.txt            # Python 依赖
├── package.json                # Node 依赖（workspace root）
├── pytest.ini                  # 测试配置
│
├── agent/                      # Agent 引擎
│   ├── app/service.py         # Agent Service 入口
│   ├── runtime/               # 运行时：turn_runner, graph_runner, pipeline
│   ├── capabilities/          # 能力注册
│   ├── skills/                # Skill 实现
│   ├── tools/                 # 工具路由 (registry, router)
│   ├── llm/                   # LLM 接口 (runtime, adapter)
│   ├── core/                  # 核心类型与常
│   ├── context/               # 上下文装配
│   ├── audit/                 # 审计日志
│   ├── modules/               # 业务模块
│   └── protocol/              # 协议定义 (tool_result 等)
│
├── backend/                    # Flask 服务
│   ├── main.py                # 唯一入口
│   ├── api/                   # REST 路由
│   │   ├── agent_routes.py    # POST /api/agent/message
│   │   ├── session_routes.py  # Session CRUD
│   │   ├── job_routes.py      # Job CRUD
│   │   ├── artifact_routes.py # Artifact CRUD
│   │   ├── runtime_routes.py  # 运行时 API
│   │   ├── workspace_routes.py
│   │   ├── approval_routes.py
│   │   ├── context_routes.py
│   │   └── cmdb_routes.py
│   ├── ws/
│   │   └── agent_ws.py        # WebSocket /ws/agent
│   └── core/                  # 安全、限流、错误处理
│
├── frontend/                   # React/TS 前端 (Vite)
│   ├── src/
│   │   ├── pages/             # 页面组件
│   │   │   ├── AgentWorkbench/  # 主工作台 (对话 + 工具)
│   │   │   ├── JobsPage/       # Job 管理
│   │   │   ├── RunsPage/       # Run 追踪
│   │   │   └── ...             # PacketAnalysis, CMDB, Settings 等
│   │   ├── api/               # API 客户端 (agent, sessions, jobs, ...)
│   │   ├── stores/            # Zustand stores (workbench, session, ...)
│   │   ├── utils/             # 工具函数 (agentStream, displayText, ...)
│   │   ├── styles/            # 全局 CSS (global.css ~3600 行)
│   │   └── types/             # TypeScript 类型定义
│   └── e2e/                   # E2E 测试
│
├── tool_runtime/               # 工具注册与执行
│   ├── manifest_registry.py   # 73 工具 CapabilityManifest
│   ├── manifest.py            # 清单数据类 + DEFAULT_ALLOWED_CALLERS
│   ├── client.py              # ToolRuntimeClient
│   ├── context.py             # ToolRuntimeContext
│   ├── python_exec.py         # Python 沙箱 (exec.python)
│   ├── general_tools/         # 通用工具实现
│   └── integration.py         # 与 Agent 引擎集成
│
├── jobs/                       # Job 系统
│   ├── schemas.py             # JobRecord, JobEvent
│   ├── manager.py             # 状态机 (create_job, mark_running, ...)
│   ├── runner.py              # 按类型执行 Job
│   ├── worker.py              # 本地轮询 Worker (fcntl 文件锁)
│   ├── store.py               # JSON 持久化
│   └── lifecycle.py           # 统一生命周期 (HTTP + WS)
│
├── workspace/                  # Session/Run 管理
│   ├── session_store.py       # create/get/delete session
│   ├── run_store.py           # create/get/list run
│   ├── ids.py                 # workspace_id 校验
│   └── redaction.py           # 密钥脱敏
│
├── context/                    # 上下文构建
│   └── fragments/             # 上下文片段
│
├── storage/                    # FileStore
├── artifacts/                  # Artifact 持久化
├── observability/             # Trace/Event 存储
├── modules/                   # 业务模块
│   ├── config_translation/    # 配置翻译
│   ├── inspection/            # 巡检
│   ├── knowledge_base/        # 知识库
│   └── topology/              # 拓扑
├── skills/                    # Skill 层
│   └── builtin/               # 内置 Skills
├── prompts/                   # Prompt 模板
├── harness/                   # pytest 测试
└──  docs/                     # 文档
```
