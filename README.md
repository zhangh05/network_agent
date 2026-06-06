# Network Agent

网络设备配置迁移 Agent 平台。统一入口服务，Module / Skill / Memory 三层架构。

## 概念

| 概念 | 说明 |
|------|------|
| **Module** | 固定产品功能模块。有 UI / API / 后端服务 / 状态。用户可点击进入。 |
| **Skill** | Agent 可加载的能力包。包含 SKILL.md 操作手册、适配代码。描述 Agent 如何使用模块。 |
| **Memory** | Agent 原生记忆系统。JSONL/SQLite backend。保留项目/会话/用户偏好/决策记录。 |
| **Workspace** | 项目文件和运行状态。不与 Memory 混淆。 |

## 快速启动

```bash
cd network_agent
pip install -r requirements.txt

# 正式入口 — 统一端口 8010
python -m backend.main --port 8010
```

访问: http://127.0.0.1:8010/

## 目录结构

```
network_agent/
├── backend/main.py              # 统一入口 (Flask, 8010)
├── backend/api/                 # API 路由
├── backend/services/            # 服务层
├── backend/agent/               # Agent 框架（预留 LangGraph）
├── modules/                     # 产品功能模块
│   ├── registry.yaml/json       # 模块注册表
│   ├── config_translation/      # enabled
│   ├── topology/                # planned
│   ├── inspection/              # planned
│   └── knowledge_base/          # planned
├── skills/                      # Agent 技能包
│   ├── registry.yaml/json       # 技能注册表
│   ├── config_translation/      # enabled (SKILL.md + adapter.py)
│   ├── topology_draw/           # planned
│   ├── inspection_analyze/      # planned
│   └── knowledge_search/        # planned
├── memory/                      # Agent 原生记忆
│   ├── schemas.py               # MemoryRecord 定义
│   ├── store.py                 # 后端工厂
│   ├── retriever.py             # 搜索接口
│   ├── writer.py                # 写入接口
│   └── backends/
│       ├── jsonl_store.py       # JSONL 后端（默认）
│       └── sqlite_store.py      # SQLite 后端（planned）
├── frontend/index.html          # 统一 UI
├── workspaces/                  # 工作区
├── harness/                     # 测试
├── reports/                     # 报告
├── docs/ARCHITECTURE.md         # 平台架构
└── apps/                        # dev-only legacy（非正式入口）
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/health | GET | 健康检查 (api_mode=unified) |
| /api/version | GET | 版本信息 |
| /api/modules | GET | 模块注册列表 |
| /api/modules/{name}/status | GET | 模块状态 |
| /api/skills | GET | 技能注册列表 |
| /api/translate | POST | 配置翻译 |
| /api/agent/run | POST | Agent 执行 |
| /api/memory/status | GET | 记忆系统状态 |
| /api/memory/write | POST | 写入记忆 |
| /api/memory/search | POST | 搜索记忆 |
| /api/workspace/status | GET | 工作区状态 |

## 当前模块

| 模块 | 状态 |
|------|------|
| config_translation | enabled — beta_ready (embedded) |
| topology | planned |
| inspection | planned |
| knowledge_base | planned |

### config_translation 模块说明

config_translation 是 network_agent **内置模块**，不依赖本机旧仓库。

- 核心翻译引擎 `RuleBasedTranslator.translate_bundle()` 已完整迁入 `modules/config_translation/core/`
- 不使用 `sys.path` 指向外部 `network-translator` 仓库
- 不使用 `os.chdir()` 到外部路径
- 不使用 GraphAgent / LLM 翻译路径
- `/api/version` 报告 `config_translation_source: "embedded"` 和 `external_translator_dependency: false`

## 当前技能

| 技能 | 状态 | 关联模块 |
|------|------|----------|
| config_translation | enabled | config_translation |
| topology_draw | planned | topology |
| inspection_analyze | planned | inspection |
| knowledge_search | planned | knowledge_base |

## Memory

- 后端: JSONL (默认, memory/data/memory_records.jsonl)
- 不使用 Obsidian 作为核心记忆
- 记忆分类: short_term / project / long_term / decision / user_preference / device_profile / run_summary / knowledge_note

## 旧服务说明

`apps/translator_service/` 和 `apps/agent_service/` 为开发期遗留，
**非正式入口**。正式启动方式:

```bash
python -m backend.main --port 8010
```

## 测试

```bash
# 启动服务后运行
NETWORK_AGENT_PORT=8010 pytest harness/test_unified_app.py harness/test_taxonomy.py -v
```

## 后续计划

- LangGraph orchestrator
- topology_draw skill
- inspection_analyze skill
- knowledge_search skill
- SQLite memory backend
