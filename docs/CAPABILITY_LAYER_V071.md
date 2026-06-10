# Capability Layer v0.7.1

> 本文档是 Agent Backend v0.7 / v0.7.1 的业务能力层（Capability Layer）单一权威说明。
> 配套：[README.md](../README.md) · [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. Overview

v0.6 把 Agent 后端重写到 Codex-style Runtime（Thread / Session / Turn / RuntimeLoop），形成稳定的运行底座。
v0.7 在底座之上引入 **Capability Layer（Phase 1）**，把两个真实业务能力（`config_translation`、`knowledge_query`）挂到 ToolRouter / ToolRuntime 上。
v0.7.1 把这两个能力的 **输出质量（artifacts / source summary / manual review）** 提升到与"真实部署"对齐的工程标准。

> **不变量**：v0.7 / v0.7.1 **不修改** Runtime 主链（`API → AgentApp → AgentThread → AgentSession → AgentTurn → RuntimeLoop → invoke_llm`），也不修改 ToolRuntime 行为；能力以**新工具**（`config_translation.translate_config`、`knowledge.query`）的形式接入 ToolRouter。

## 2. Current Enabled Capabilities

| Capability | Skill | Module | Tool | Status |
|------------|-------|--------|------|--------|
| Config Translation | `config_translation` | `config_translation` | `config_translation.translate_config` | **enabled** |
| Knowledge Query | `knowledge_query` | `knowledge` | `knowledge.query` | **enabled** |
| Topology | `topology` | `topology` | — | planned (NOT injected) |
| Inspection | `inspection` | `inspection` | — | planned (NOT injected) |
| CMDB | `cmdb` | `cmdb` | — | planned (NOT injected) |

> "planned means NOT callable"：planned 模块在 SkillRegistry / ModuleRegistry / RuntimeSnapshot 中**显式标记**，**不允许 LLM 调用**，**不允许伪造数据**。

## 3. Config Translation Flow

```
User request
  → RuntimeLoop.run_turn()
  → invoke_llm()            (LLM 决策调用 config_translation.translate_config)
  → ToolRouter.dispatch()
  → ToolRuntimeClient.invoke("config_translation.translate_config", payload)
  → agent.modules.config_translation.service.translate_config()
  → translated_config artifact (artifacts.store.save_artifact)
  → ToolResultMessage        (回到 RuntimeLoop)
  → invoke_llm() follow-up   (汇总结果)
  → AgentResult.to_dict()
```

调用入口：
- **Chat 路径**：`POST /api/agent/message`（assistant_chat 兜底）→ LLM 工具调用 → `config_translation.translate_config`
- **直连路径**：`POST /api/modules/config-translation/translate`（业务模块 API）

## 4. Config Translation Output Contract

`config_translation.translate_config` 返回字段（顶层）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | `bool` | 翻译过程无 fatal error |
| `summary` | `str` | 人类可读摘要 |
| `source_vendor` | `str` | 解析得到的源厂商（`auto` / `cisco` / `huawei` / `h3c` / `ruijie` / `unknown`） |
| `target_vendor` | `str` | 目标厂商（默认 `huawei`） |
| `line_count` | `int` | 翻译后行数 |
| `translated_config` | `str` | 翻译后配置文本（**非 deployable**） |
| `manual_review_items` | `list[dict]` | 结构化人工复核项（见 §6） |
| `manual_review_count` | `int` | 人工复核项数量 |
| `artifacts` | `list[dict]` | `translated_config` 保存为 artifact 的引用 |
| `warnings` | `list[str]` | 非致命警告（含 `artifact_save_failed`） |
| `errors` | `list[str]` | 致命错误码 |
| `metadata` | `dict` | `elapsed_ms` / `quality_summary` / `audit` / `build_commit` |

> **artifacts 必填语义**：`translated_config` 必须以 `translated_config` 类型的 artifact 落到 artifact store；保存失败只追加 `warnings=["artifact_save_failed"]`，**不阻塞**翻译本身。

## 5. Artifact Contract — `translated_config`

```yaml
artifact_type: "translated_config"
sensitivity: "sensitive"
source: "module_output"
metadata:
  authoritative: false        # 永远不可宣称权威翻译
  deployable_config: false    # 永远不可直接部署
  source_vendor: "<vendor>"
  target_vendor: "<vendor>"
  line_count: <int>
  quality_summary: {...}
  build_commit: "<git-sha>"
```

> **红线**：`authoritative=false` / `deployable_config=false` 是强制约束；任何 LLM 输出口径、artifact metadata、AgentResult 提示语都不得宣称"权威 / 可直接部署"。

## 6. Manual Review Item Schema

```json
{
  "item_id": "<uuid8>",
  "severity": "low|medium|high",
  "category": "syntax|semantic|unsupported_feature|vendor_difference|security|unknown",
  "line_no": 42,
  "source_text": "...",
  "translated_text": "...",
  "reason": "...",
  "recommendation": "...",
  "requires_human_review": true
}
```

行为约束：
- `manual_review_count > 0` ⇒ 结果**必须**在 UI / LLM 反馈 / 报告摘要中明确"需要人工复核"。
- `quality_summary.source_residue_count > 0` 或 `silent_drop_count > 0` ⇒ 同上，且不得以"可直接部署"描述。
- 任意 `severity == "high"` ⇒ 强制走人工复核通道（**`deployable_config` 永远 `false`**）。

## 7. Knowledge Query Flow

```
User request
  → RuntimeLoop.run_turn()
  → invoke_llm()            (LLM 决策调用 knowledge.query)
  → ToolRouter.dispatch()
  → ToolRuntimeClient.invoke("knowledge.query", {"query": "..."})
  → agent.modules.knowledge.service.query_knowledge()
  → hits / source_count / source_summary   (本地 RAG：knowledge/store + search)
  → ToolResultMessage
  → invoke_llm() follow-up
  → AgentResult.to_dict()
```

调用入口：
- **Chat 路径**：`POST /api/agent/message` → LLM 工具调用 → `knowledge.query`
- **直连路径**：`POST /api/modules/knowledge/query`（业务模块 API）

## 8. Knowledge Output Contract

`knowledge.query` 返回字段（顶层）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | `bool` | 查询路径无 fatal error |
| `summary` | `str` | 人类可读摘要 |
| `query` | `str` | 回显查询字符串 |
| `hits` | `list[dict]` | 命中结果（来自 knowledge/search） |
| `source_count` | `int` | `len(hits)` |
| `source_summary` | `list[dict]` | 最多 5 条，每条 `{title, source, score, snippet}`，**`snippet ≤ 200` 字符** |
| `warnings` | `list[str]` | 非致命警告 |
| `errors` | `list[str]` | 致命错误码 |
| `metadata` | `dict` | `elapsed_ms` / `index_id` / `policy` / `build_commit` |

**绝不伪造引用**（hard rules）：
- `hits == []` ⇒ `source_count == 0`，`source_summary == []`
- knowledge 不可用 ⇒ `errors == ["knowledge_unavailable"]`，`source_summary == []`
- 任何情况下**不得**编造 `title` / `source` / `score` / `citation` / `snippet`

## 9. Runtime Result Enrichment (v0.7.1)

`AgentResult.tool_calls[]` 在 v0.7.1 增强：

```json
{
  "call_id": "<uuid>",
  "tool_id": "config_translation.translate_config | knowledge.query | <other>",
  "ok": true,
  "summary": "...",
  "artifacts": [...],
  "source_count": 0,
  "manual_review_count": 3,
  "errors": [...],
  "warnings": [...],
  "metadata": {...}
}
```

`ToolResultMessage.content`：
- 上限 1000 → **2000 字符**
- 附 `artifact_count` + 前 3 个 artifact 摘要
- 附 `source_summary`（knowledge）
- 附 `manual_review_count`（config_translation）

目的：让 LLM 在下一轮可以基于 **真实 artifact / source / review 数据**继续推理，而不是基于被压缩过的字符串。

## 10. Planned Capabilities (NOT callable)

| Planned | Skill / Module | 状态 | 说明 |
|---------|---------------|------|------|
| `topology` | `topology` | planned | 拓扑发现与渲染；**未注入 SkillRegistry / ModuleRegistry / RuntimeSnapshot** |
| `inspection` | `inspection` | planned | 巡检分析；**未注入** |
| `cmdb` | `cmdb` | planned | 资产管理；**未注入** |

约束：
- planned 模块**永远不**出现在 `model_visible_tools()` / `model_visible_specs()`
- planned 模块**永远不**出现在 `RuntimeSnapshot` 的 enabled 部分
- 不允许 LLM 通过任何路径调用 planned 模块
- **不允许**伪造 planned 模块的数据 / 报告

## 11. Security Boundaries

| 红线 | 说明 |
|------|------|
| **No real device access** | 平台不直接连接任何网络设备 |
| **No SSH / Telnet / SNMP / nmap / ping sweep** | 这些 tool 名已在 ToolRuntime 永久禁止 |
| **`config.push` 永久禁止** | 不存在可调用的 `config.push` 工具 |
| **No authoritative deployable_config** | LLM / artifact / AgentResult 一律 `deployable_config=false`、`authoritative=false` |
| **Tool execution centralization** | 所有工具走 `ToolRouter → ToolRuntimeClient`，不绕过 ToolPolicy / ToolExecutor / Redaction / Audit |
| **Module / Skill 不得私接 LLM** | 业务能力必须通过 `invoke_llm()` 统一入口 |
| **Cross-workspace default deny** | artifact / memory / run / trace 跨 workspace 默认拒绝 |
| **API key local only** | `config/LLM_setting.json` 权限 600，API 仅返回 `key_preview` |

## 12. Test Coverage

| Test File | 范围 | 状态 (2026-06-10) |
|-----------|------|------------------|
| `harness/test_capability_config_translation_v07.py` | v0.7 config_translation 主流程 + skill/module/tool 注册 | **passed** |
| `harness/test_capability_knowledge_v07.py` | v0.7 knowledge_query 主流程 + RAG 路径 | **passed** |
| `harness/test_capability_artifacts_v071.py` | v0.7.1 translated_config artifact 契约（authoritative/deployable_config=false、sensitive、artifact_store） | **passed** |
| `harness/test_capability_knowledge_sources_v071.py` | v0.7.1 source_summary ≤200 字符、knowledge_unavailable、零伪造 | **passed** |

合计：**41 / 41 passed**（详见 [README.md §"Test Baseline"](../README.md)）。

## 13. Future Work (NOT in v0.7.1)

按规划（不在本轮）：
- Knowledge Index Runtime 完整化：chunk policy、增量索引、引用血缘
- Tool call 归因 / 观测性增强：tool_call 事件链、跨 module 引用追踪
- 跨工作区协作 + 多租户隔离强化
- 业务模块按规划逐步启用：`topology` → `inspection` → `cmdb`

> **2026-06-10 更新**：v0.7.1 之后已经迈入 **v0.8 — Capability Manifest Refactor**，并随后跟进 **v0.8.1 — SkillSelector + Dynamic Tool Visibility** 与 **v0.8.2 — Result Contract Standardization**。
>
> v0.8 业务能力层从"分散的 ModuleRegistry / SkillRegistry / ToolRegistry hardcode 常量"重构为统一的 **`CapabilityManifest` + `CapabilityRegistry`**；
> RuntimeSnapshot 从 CapabilityRegistry 投影；Module/Skill/Tool Registry 提供 `from_capabilities()` / `register_capability_tools()` 派生路径。
> v0.7.1 的能力（`config_translation.translate_config` + `knowledge.query`）的**业务输出合同不变**，仅被 manifest 化。
>
> v0.8.1 在每轮 turn 注入 LLM 之前增加 `SkillSelector`（rule-based 选 skill）+ `ToolRouter.apply_dynamic_visibility()`（动态 tool 白名单）：
> config 翻译场景只暴露 `config_translation.translate_config`；knowledge 场景只暴露 `knowledge.query`；topology / inspection / cmdb 永远不可见；任何 selector 异常 fallback 到 v0.8 全量 + warning。
>
> v0.8.2 统一结果链路 `ModuleResult → ToolResult → AgentResult.tool_calls`，让所有能力输出结构一致；v0.7.1 业务输出合同不变（仍为 `dict`），但 Module / Tool / Loop 三层提供 `to_module_result` / `from_module_result` / `_to_standard_tool_call` 投影。
> 详细见 [CAPABILITY_MANIFEST_V08.md](CAPABILITY_MANIFEST_V08.md) § 9 (v0.8.1) / § 10 (v0.8.2)。
