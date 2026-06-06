# Network Agent Architecture

## Concept Taxonomy

### Module（模块）
固定产品功能模块。有 API、后端服务、状态。UI 由统一前端提供。

| 模块 | 状态 | 说明 |
|------|------|------|
| config_translation | enabled | 网络配置跨厂商翻译 |
| topology | planned | 网络拓扑提取与绘图 |
| inspection | planned | 配置巡检与合规分析 |
| knowledge_base | planned | 网络知识库与经验积累 |

### Skill（技能）
Agent 可加载的能力包。通过 adapter 调用模块服务。

| Skill | 状态 | 关联模块 |
|------|------|----------|
| config_translation | enabled | config_translation |
| topology_draw | planned | topology |
| inspection_analyze | planned | inspection |
| knowledge_search | planned | knowledge_base |

### Memory（记忆）
Agent 原生记忆系统，JSONL backend (`memory/data/memories.jsonl`)。走 redaction + policy 门控。

### Workspace（工作区）
运行历史、状态摘要、产物管理。状态不保存完整配置，运行记录不保存 key/secrets。

### Agent（智能体）
LangGraph / LLM 调度主框架。7 节点流水线。
```
router → context → planner → executor → verifier → composer → memory
```

### LLM
**已实现**，非 skeleton。

- 配置主路径: `config/LLM_setting.json` (UI Settings)
- 优先级: UI Settings > env/file fallback > default
- 默认模型: MiniMax-M3
- Provider: MiniMax (OpenAI 兼容), DeepSeek, Ollama, Mock
- LLM 仅属于 Agent 层，Module/Skill 不私接 LLM
- LLM 只用于 Composer 和 Context QA，不改 deployable_config

## API

```
POST /api/modules/config-translation/translate   # 配置翻译（正式模块 API）
POST /api/agent/run                               # Agent 执行
GET  /api/agent/status                            # Agent 状态
GET  /api/agent/llm/config                        # LLM 配置（不含 key）
POST /api/agent/llm/config                        # 保存 LLM 配置
DELETE /api/agent/llm/config                      # 删除 LLM 配置
GET  /api/agent/llm/status                        # LLM 状态
POST /api/agent/llm/test                          # LLM 测试
GET  /api/health                                  # 健康检查
GET  /api/version                                 # 版本
GET  /api/modules                                 # 模块注册表
GET  /api/skills                                  # 技能注册表
GET  /api/memory/status                           # 记忆系统状态
GET  /api/memory/list                             # 记忆列表
POST /api/memory/search                           # 记忆搜索
POST /api/memory/write                            # 写入记忆
POST /api/memory/confirm                          # 用户确认写入
DELETE /api/memory/{id}                           # 删除记忆
GET  /api/workspaces                              # 工作区列表
GET  /api/workspaces/{id}/state                   # 工作区状态
GET  /api/workspaces/{id}/runs                    # 运行历史
GET  /api/workspaces/{id}/runs/{run_id}           # 单次运行
GET  /api/workspaces/{id}/artifacts               # 产物列表
GET  /api/workspaces/{id}/artifacts/{id}          # 产物详情
```

## Module Placement

config_translation 模块完整位于 `modules/config_translation/`:

```
modules/config_translation/
├── backend/         # service/schemas — canonical implementation
├── core/            # translate_bundle 确定性翻译管线
├── MODULE.md
└── module.yaml
```

## 已删除
- `/api/translate` — 已删除
- `backend/services/config_translation` — 已删除
- `GraphAgent` — 不恢复
- 外部 network-translator 依赖 — 不引入
- `os.chdir`/`sys.path` 外挂 — 不存在

## Core Invariants
- `translate_bundle()` 主链不改
- Gate 不放宽
- Module/Skill 不私接 LLM
- LLM 不改 deployable_config
