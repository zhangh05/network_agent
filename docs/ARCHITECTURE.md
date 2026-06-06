# Network Agent Architecture

## Concept Taxonomy

### Module（模块）
固定产品功能模块。有 API、后端服务、状态。UI 由统一前端提供。

| 模块 | 状态 | 说明 |
|------|------|------|
| config_translation | enabled (embedded_mvp) | 网络配置跨厂商翻译 |
| topology | planned | 网络拓扑提取与绘图 |
| inspection | planned | 配置巡检与合规分析 |
| knowledge_base | planned | 网络知识库与经验积累 |

### Skill（技能）
Agent 可加载的能力包。包含 SKILL.md、skill.yaml、adapter.py。通过 adapter 调用模块服务。

| Skill | 状态 | 关联模块 |
|------|------|----------|
| config_translation | enabled | config_translation |
| topology_draw | planned | topology |
| inspection_analyze | planned | inspection |
| knowledge_search | planned | knowledge_base |

### Memory（记忆）
Agent 原生记忆系统，JSONL backend。不属于任何模块，由平台统一管理。

### Agent（智能体）
LangGraph / LLM 调度主框架。`agent/` 目录包含 router、planner、executor、verifier、composer。

### LLM
统一 LLM 层预留于 `agent/llm/`。当前 skeleton，未连接真实模型。Module 不得私接 LLM。

## API

```
POST /api/modules/config-translation/translate   # 配置翻译（正式模块 API）
POST /api/agent/run                               # Agent 执行
GET  /api/health                                  # 健康检查 (api_mode=unified)
GET  /api/version                                 # 版本 + embedded 状态
GET  /api/modules                                 # 模块注册表
GET  /api/skills                                  # 技能注册表
GET  /api/memory/status                           # 记忆系统状态
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

- 后端服务: modules/config_translation/backend/service.py
- 翻译核心: modules/config_translation/core/rule_translator.py
- Skill 适配器: skills/config_translation/adapter.py → module service

## Skill Call Chain

```
POST /api/agent/run {intent: translate_config}
  → backend/api/agent.py::_run_translate()
    → skills/config_translation/adapter.py::translate()
      → modules/config_translation/backend/service.py::translate_config()
        → modules/config_translation/core/rule_translator.py::translate_bundle()
```

## LLM Boundary

- LLM belongs to Network Agent orchestrator (`agent/llm/`)
- config_translation module does NOT call LLM
- LLM must NOT modify deployable_config
- Future AI candidate translation must be produced outside deployable_config

## Legacy

- apps/ → legacy/apps/ (dev-only, not tested)
- backend/services/config_translation/ → DELETED
- 8020 → NOT a formal entry point
- /api/translate → DELETED (use module API)
