# Config Translation Module

固定产品功能模块。后端翻译引擎完整嵌入 `modules/config_translation/`。

## 状态
- enabled
- maturity: beta_ready (switch/router)

## 目录结构

```
modules/config_translation/
├── backend/
│   ├── service.py          # translate_config 正式实现
│   ├── schemas.py          # TranslateRequest / TranslateResponse
│   └── client.py           # HTTP client for the formal module API
├── core/                    # 确定性翻译管线
│   ├── rule_translator.py   # RuleBasedTranslator.translate_bundle()
│   ├── translation_model.py
│   ├── deployable_policy.py
│   ├── translation_candidate_factory.py
│   ├── ir_parser.py
│   ├── typed_renderer.py
│   ├── typed_ir.py
│   └── parser/
│       └── config_block_parser.py
├── MODULE.md
└── module.yaml
```

## 端点
- 正式 API: `POST /api/modules/config-translation/translate`
- retired API: `/api/translate` is not exposed in the current platform.

## UI

本模块只内置后端确定性翻译能力。UI 由 `network_agent` 统一前端 (`frontend/index.html`) 提供。本模块不迁移旧 network-translator 前端。

## LLM 边界

- LLM belongs to Network Agent orchestrator layer
- config_translation module does NOT directly call LLM
- LLM must NOT modify deployable_config
- Future AI candidate translation must be produced outside deployable_config

## 依赖

- 翻译引擎: 内置 `RuleBasedTranslator.translate_bundle()`（不依赖外部 network-translator 仓库）
- 不使用 GraphAgent/LLM 翻译路径
- 不使用 sys.path / os.chdir 外部仓库

## 功能
- 跨厂商配置语法转换
- 人工复核项目输出
- 语义相近项目输出
- 审计和安全检查

## 限制
- 不调用 legacy_rule_translator
- 不调用 translate_separated
- 不把 full_output 作为 deployable_config
- 不迁入旧 network-translator 前端
- 不迁入旧 LLM / GraphAgent 翻译路径
