# Config Translation Module

固定产品功能模块。有 UI 和 API。

## 状态
- enabled
- maturity: beta_ready (switch/router)

## 端点
- API: POST /api/translate
- UI: /modules/translate

## 依赖
- 底层翻译引擎: network-translator 的 `translate_bundle()`
- 不使用 GraphAgent/LLM 翻译路径

## 功能
- 跨厂商配置语法转换
- 人工复核项目输出
- 语义相近项目输出
- 审计和安全检查

## 限制
- 不修改原 network-translator 仓库
- 不调用 legacy_rule_translator
- 不调用 translate_separated
- 不把 full_output 作为 deployable_config
