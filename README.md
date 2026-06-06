# Network Agent

统一网络智能 Agent 平台。Module / Skill / Memory 三层架构，统一入口 8010。

## 概念

| 概念 | 说明 | 目录 |
|------|------|------|
| **Module** | 固定产品功能模块 | `modules/` |
| **Skill** | Agent 调用模块的能力包 | `skills/` |
| **Memory** | Agent 原生记忆系统 | `memory/` |
| **Agent** | LangGraph 调度 + 统一 LLM 层 | `agent/` |
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
│   ├── router.py                # 意图路由
│   ├── planner.py               # 规划器
│   ├── executor.py              # 执行器 (通过 skill adapter)
│   ├── verifier.py              # 输出校验
│   ├── composer.py              # 响应合成
│   └── llm/                     # 统一 LLM 层 (skeleton)
├── modules/                     # 产品功能模块
│   ├── registry.json/yaml
│   └── config_translation/      # enabled, embedded MVP
│       ├── backend/             # service/schemas (正式实现)
│       └── core/                # translate_bundle 确定性管线
├── skills/                      # Agent 技能包
│   ├── registry.json/yaml
│   └── config_translation/      # SKILL.md + adapter.py
├── memory/                      # Agent 原生记忆 (JSONL)
├── frontend/index.html          # 统一 UI
└── harness/                     # 测试
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/health | GET | api_mode=unified |
| /api/version | GET | config_translation_source=embedded |
| /api/modules | GET | 模块注册表 |
| /api/modules/config-translation/translate | POST | 配置翻译（正式 API） |
| /api/agent/run | POST | Agent 执行 (intent=translate_config) |
| /api/skills | GET | 技能注册表 |
| /api/memory/status | GET | 记忆系统状态 |

## Module 定调

config_translation 是内置 Module，路径 `modules/config_translation/`。

- 翻译引擎: RuleBasedTranslator.translate_bundle()
- 不依赖外部 network-translator 仓库
- 不迁旧 network-translator 前端
- 不迁旧 LLM / GraphAgent 翻译路径
- UI 由 network_agent 统一前端提供

## Skill 定调

skills/config_translation/adapter.py 直接调用 module service，不通过 HTTP / LLM。

## LLM 定调

- LLM 属于 `agent/llm/`（当前 skeleton，未连接真实模型）
- config_translation 模块不私接 LLM
- LLM must not modify deployable_config

## Memory 定调

- Memory 是平台原生系统，JSONL 存储
- 不属于 config_translation 模块

## 旧结构说明

| 旧结构 | 状态 |
|--------|------|
| apps/translator_service | 已移至 legacy/ |
| apps/agent_service | 已移至 legacy/ |
| 8020 | 非正式入口，不测试 |
| backend/services/config_translation | 已删除 |
| /api/translate | 已删除，用模块 API 替代 |
