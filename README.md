# Network Agent

统一网络智能 Agent 平台。Module / Skill / Memory 三层架构，统一入口 8010。

## 概念

| 概念 | 说明 | 目录 |
|------|------|------|
| **Module** | 固定产品功能模块 | `modules/` |
| **Skill** | Agent 调用模块的能力包 | `skills/` |
| **Agent** | LangGraph 调度 + 统一 LLM 层 | `agent/` |
| **Memory** | Agent 原生记忆系统 (JSONL) | `memory/` |
| **Workspace** | 运行历史、状态、产物管理 | `workspace/` |
| **UI** | 统一前端 | `frontend/index.html` |

## 快速启动

```bash
cd network_agent
pip install -r requirements.txt
python backend/main.py --port 8010
```

访问: http://127.0.0.1:8010

## 目录结构

```
network_agent/
├── backend/                     # 平台 API 挂载
│   ├── main.py                  # 统一入口 (8010)
│   ├── api/                     # API 路由
│   └── core/                    # 设置/路径
├── agent/                       # Agent 主框架
│   ├── state.py                 # NetworkAgentState
│   ├── graph.py                 # LangGraph orchestrator
│   ├── nodes/                   # LangGraph 节点
│   │   ├── intent_router.py     # 意图路由
│   │   ├── context_loader.py    # 上下文加载
│   │   ├── planner.py           # 规划器
│   │   ├── skill_executor.py    # 执行器
│   │   ├── verifier.py          # 校验器
│   │   ├── composer.py          # 响应合成
│   │   └── memory_writer.py     # 记忆/状态写入
│   └── llm/                     # 统一 LLM 层 (已实现)
│       ├── runtime.py           # safe_generate 主链
│       ├── provider.py          # 多 provider 支持
│       ├── settings.py          # UI settings (config/LLM_setting.json)
│       ├── config.py            # 统一配置解析
│       ├── context_builder.py   # 安全上下文构建
│       ├── policy.py            # 安全策略门控
│       ├── client.py            # LLMClient 外部接口
│       └── tasks/prompts.py     # 任务提示词
├── modules/                     # 产品功能模块
│   ├── registry.json/yaml
│   └── config_translation/      # enabled, embedded
│       ├── backend/             # service/schemas
│       └── core/                # translate_bundle 管线
├── skills/                      # Agent 技能包
│   ├── registry.json/yaml
│   └── config_translation/      # SKILL.md + adapter.py
├── memory/                      # Agent 原生记忆 (JSONL)
│   ├── schemas.py               # MemoryRecord/RunRecord/WorkspaceState/Artifact
│   ├── writer.py                # 记忆写入 (redaction+policy)
│   ├── redaction.py             # 秘密脱敏
│   ├── policy.py                # 写入策略
│   ├── store.py                 # 存储工厂
│   ├── retriever.py             # 搜索/列表接口
│   └── backends/jsonl_store.py  # JSONL 后端
├── workspace/                   # 工作区运行时
│   ├── manager.py               # CRUD, 状态管理
│   ├── run_store.py             # 运行记录
│   └── artifact_store.py        # 产物存储
├── frontend/index.html          # 统一 UI
├── config/
│   ├── LLM_setting.example.json # LLM 配置模板 (tracked)
│   ├── LLM_setting.json         # LLM UI 配置 (gitignored)
│   ├── llm.yaml                 # 兜底配置
│   └── llm.example.yaml
├── harness/                     # 测试 (146+ tests)
├── reports/                     # 审计报告
└── scripts/                     # 审计/清理工具
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/version` | GET | 版本信息 |
| `/api/agent/run` | POST | Agent 执行 |
| `/api/agent/status` | GET | Agent 运行时状态 |
| `/api/agent/llm/config` | GET/POST/DELETE | LLM 配置 CRUD |
| `/api/agent/llm/status` | GET | LLM 连接状态 |
| `/api/agent/llm/test` | POST | LLM 连通性测试 |
| `/api/modules` | GET | 模块注册表 |
| `/api/modules/config-translation/translate` | POST | 配置翻译（正式模块 API） |
| `/api/skills` | GET | 技能注册表 |
| `/api/workspaces` | GET | 工作区列表 |
| `/api/workspaces/{id}/state` | GET | 工作区状态 |
| `/api/workspaces/{id}/runs` | GET | 运行历史 |
| `/api/workspaces/{id}/runs/{run_id}` | GET | 单次运行 |
| `/api/workspaces/{id}/artifacts` | GET | 产物列表 |
| `/api/memory/status` | GET | 记忆系统状态 |
| `/api/memory/list` | GET | 记忆列表 |
| `/api/memory/search` | POST | 记忆搜索 |
| `/api/memory/write` | POST | 写入记忆 |
| `/api/memory/confirm` | POST | 用户确认写入 |
| `/api/memory/{id}` | DELETE | 删除记忆 |

## LLM Runtime

LLM Runtime 已完整实现，非 skeleton。

**配置优先级**: UI Settings (`config/LLM_setting.json`) > 环境变量/桌面文件 > 默认禁用。

- 用户通过 System Settings UI 配置 provider/model/API key
- API key 仅本地存储，不进 Git，API 不返回完整 key
- 默认模型: **MiniMax-M3**
- LLM 仅属于 Agent 层，Module/Skill 不得私接 LLM
- LLM 只用于 Composer 响应合成和 Context QA，不改 deployable_config

**Provider 支持**: MiniMax (默认), OpenAI 兼容, DeepSeek, Ollama, Mock

## Workspace / Memory

| 概念 | 存储 | 内容 |
|------|------|------|
| **Memory** | `memory/data/memories.jsonl` | Agent 记忆记录 |
| **Workspace State** | `workspaces/{id}/state.json` | 最近运行摘要 (无完整配置) |
| **Run History** | `workspaces/{id}/runs/*.json` | 运行记录 (无完整配置/key) |
| **Artifact** | `workspaces/{id}/artifacts/` | 产物文件 (sensitive 标记) |

所有写入走 redaction + policy 门控，确保无 secrets 泄露、无完整配置存储。

## Agent Workflow

```
router → context → planner → executor → verifier → composer → memory
```

LangGraph runtime 已激活，7 节点流水线，deterministic fallback 保底。

## 验证

```bash
# 运行测试
pytest harness -q                    # 146+ passed, 0 failed

# 安全审计
python scripts/audit_llm_security.py
python scripts/audit_workspace_memory_security.py

# 数据清理
python scripts/cleanup_test_data.py
```

## 核心约束

- `translate_bundle()` 主链不改
- `/api/translate` 已删除
- `backend/services/config_translation` 已删除
- 不引入外部 network-translator
- Gate 不放宽
- Module/Skill 不私接 LLM
- LLM 不改 deployable_config
