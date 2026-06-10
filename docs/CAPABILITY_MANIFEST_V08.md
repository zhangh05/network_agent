# Capability Manifest v0.8

> Single source of truth for capabilities. v0.8 refactor.
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) · [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. Why CapabilityManifest

v0.7 / v0.7.1 把 config_translation 和 knowledge 接到了 ToolRouter / ToolRuntime 上，但每层（Module / Skill / Tool）的元数据是**分散**在三个 registry 的 hardcode 常量里：

| 层 | 旧实现 | 散落位置 |
|----|-------|---------|
| Module | `agent/modules/registry.py` 里的 5 个 `ModuleSpec` 常量 | `agent/modules/registry.py` |
| Skill | `agent/skills/schemas.py` 里的 6 个 `SkillSpec` 常量 | `agent/skills/schemas.py` |
| Tool | `agent/modules/{config_translation,knowledge}/tools.py` 里的 2 个 `ToolSpec` 常量 | 模块目录内 |
| Snapshot | `agent/runtime/context_builder.py` 里手工拼装 | `agent/runtime/context_builder.py` |
| Runtime | `agent/runtime/services.py` 手工注册 | `agent/runtime/services.py` |

→ 5 个地方要同时改、3 个 dataclass 字段要对齐、ToolRouter 跟 Snapshot 容易漂移。

v0.8 引入 **`CapabilityManifest` / `CapabilityRegistry`**，把"一个业务能力"的所有元数据收口到**一个 manifest 文件**，再让 ModuleRegistry / SkillRegistry / ToolRegistry / RuntimeSnapshot **全部从 CapabilityRegistry 派生**。CapabilityRegistry 是真相源；其他 registry 是它的投影。

## 2. Core Concepts

| 概念 | 定义 | 责任 | 不知道什么 |
|------|------|------|-----------|
| **Module** | 业务能力的实现层 | 输入结构化参数 → 输出结构化结果 → 可保存 artifact | 不知道 LLM / Skill / ToolRouter |
| **Tool** | LLM 可调用入口 | tool_id / schema / risk / approval / callable_by_llm；轻量参数校验；dispatch 到 Module；包 ToolResult | 不知道业务逻辑细节 |
| **Skill** | 给 LLM 的能力指南 | intent_patterns / preconditions / postconditions / safety_rules | **不执行代码** |
| **Capability** | Module + Tool(s) + Skill(s) + Output Contract + Safety Contract 的完整业务包 | 表达"我能做什么、什么时候用、风险是什么、产出什么" | — |
| **CapabilityRegistry** | 5 个 capability manifest 的容器 | 真相源；提供 `list_enabled / list_planned / visible_tool_ids / to_snapshot_dict` 等视图 | — |

## 3. Dependency Direction

```
RuntimeLoop
    → ToolRouter
        → ToolRegistry  (← consumes capability_registry.enabled_tools())
        → Tool handler
            → Module service

ContextBuilder
    → services.capability_registry  (truth-source)
        → ModuleRegistry.from_capabilities(capability_registry)
        → SkillRegistry.from_capabilities(capability_registry)
        → RuntimeSnapshot.build_runtime_snapshot(capability_registry=...)
```

**禁止方向**：

- Module 不得 import / 反向依赖 RuntimeLoop / ToolRouter / SkillRegistry
- Skill 不得持有 callable；不得 import ToolRegistry
- Tool handler 不得承载复杂业务逻辑（只做参数校验 + 包装 ToolResult）
- RuntimeSnapshot 不得手工拼装 enabled/planned 列表；只能从 CapabilityRegistry 投影

## 4. CapabilityManifest Schema

`agent/capabilities/schemas.py` 定义 6 个 dataclass：

| 类型 | 关键字段 |
|------|---------|
| `CapabilityManifest` | `capability_id, name, status, description, module, skills, tools, outputs, safety, dependencies, metadata` |
| `CapabilityModuleSpec` | `module_id, status, service_path, operations, description` |
| `CapabilitySkillSpec` | `skill_id, status, related_tools, intent_patterns, required_inputs, prompt_summary, preconditions, postconditions, safety_rules` |
| `CapabilityToolRef` | `tool_id, status, callable_by_llm, risk_level, requires_approval, forbidden, handler_ref, input_schema, description` |
| `CapabilityOutputSpec` | `output_id, output_type, description, artifact_type, visible_to_user, sensitivity, authoritative, metadata` |
| `CapabilitySafetySpec` | `real_device_access, allows_config_push, produces_deployable_config, may_fabricate_sources, requires_human_review, notes` |

Status 取值：`enabled | planned | disabled`（tool / module / capability 共用一套）。

约束（在 `__post_init__` 中强制）：
- `status="enabled"` 的 capability **必须**有 `module.module_id` **和**至少 1 个 tool
- `status="planned"` 的 capability **不得**有 `status="enabled"` 的 tool
- `status="planned"` 的 capability 的 tool **必须** `callable_by_llm=False`
- `forbidden=True` 的 tool **必须** `callable_by_llm=False`
- `status="enabled"` 的 tool **必须**有 `handler_ref`（dotted path）

## 5. Current Capabilities (v0.8)

| capability_id | status | module | skills | tools (LLM-callable) |
|---------------|--------|--------|--------|----------------------|
| `config_translation` | enabled | `config_translation` | `config_translation` | `config_translation.translate_config` |
| `knowledge` | enabled | `knowledge` | `knowledge_query` | `knowledge.query` |
| `topology` | planned | `topology` | `topology` | — (planned, NOT callable) |
| `inspection` | planned | `inspection` | `inspection` | — (planned, NOT callable) |
| `cmdb` | planned | `cmdb` | `cmdb` | — (planned, NOT callable) |

**`assistant_chat`** 是 system / base skill，**不**通过 capability manifest 表达；它由 `SkillRegistry._register_defaults()` 注入，RuntimeSnapshot 在合并 `base_enabled_skills` 时保留它。

## 6. Registry Relationship

```
                    ┌──────────────────────────────┐
                    │ CapabilityRegistry (truth)   │
                    │   get_default_capability_…() │
                    └──────────────────────────────┘
                                  │
        ┌─────────────────┬───────┴─────────┬──────────────────────┐
        ▼                 ▼                 ▼                      ▼
ModuleRegistry     SkillRegistry       ToolRegistry       RuntimeSnapshot
.from_capabilities .from_capabilities  .register_…(reg)   .build_runtime_snapshot(
                                                                capability_registry=…
                                                          )
```

| 消费者 | 派生方式 | 行为变化 |
|--------|---------|---------|
| `ModuleRegistry.from_capabilities()` | 把每个 cap 的 `module` 投影到 `ModuleSpec` | 保留 `_register_defaults()` 作为 fallback；capability 是 preferred |
| `SkillRegistry.from_capabilities()` | 把每个 cap 的 `skills` 投影到 `SkillSpec`，叠加 `base_skill_registry` 保留 `assistant_chat` | 同上 |
| `ToolRegistry.register_capability_tools()` | 遍历 `capability_registry.enabled_tools()`，按 `CapabilityToolRef` 建 `ToolSpec` | **planned 工具完全不进入**；`enabled_tools()` 自身就只返回 enabled |
| `RuntimeSnapshot.build_runtime_snapshot()` | `to_snapshot_dict() + visible_tool_ids() + safety_summary()` | 旧 fallback 路径保留（用 `metadata.capability_registry_fallback=True` 标记） |

## 7. Safety Rules

| 强制 | 说明 |
|------|------|
| **planned NOT callable** | `CapabilityToolRef(status="planned")` **必须** `callable_by_llm=False`；`visible_tool_ids()` 进一步 fail-closed |
| **forbidden tools never visible** | `forbidden=True` 永远不出现在 `visible_tool_ids()`；`ToolRuntime` 也有独立 regex 拦截 `config.push` / `ssh.exec` / `nmap.scan` / `ping.sweep` 等 |
| **No real device access** | 所有 capability 的 `CapabilitySafetySpec.real_device_access=False`（默认） |
| **No config.push** | `config.push` 永久禁止；`CapabilityToolRef` 不允许注册此 tool_id |
| **No fabricated sources** | `CapabilitySafetySpec.may_fabricate_sources` 默认 False；knowledge capability 显式禁止 |
| **translated_config != deployable_config** | `CapabilityOutputSpec(authoritative=False)` + `safety.produces_deployable_config=False`；`translated_config` artifact metadata 同样写 `deployable_config=False` |

## 8. RuntimeSnapshot 新格式

`build_runtime_snapshot(capability_registry=…)` 走 CapabilityRegistry 路径时，`to_prompt_text()` 输出：

```text
[RUNTIME SNAPSHOT]
Workspace: …
Model: …

Current Capability Baseline:
- Enabled capabilities:
  - config_translation
  - knowledge
- Planned capabilities:
  - topology
  - inspection
  - cmdb
  Note: planned capabilities are NOT callable.

Enabled skills:
  - assistant_chat
  - config_translation
  - knowledge_query

Visible business tools:
  - config_translation.translate_config
  - knowledge.query

Tool count:
  total: 57
  visible: 55

Safety:
  - No real device access
  - config.push forbidden
  - translated_config is not deployable_config
  - knowledge sources must not be fabricated
```

> `total = 55 general + 2 capability = 57`；`visible = 53 enabled general + 2 capability = 55`（55 general 里有 2 个 disabled 隐藏：`command.approved_exec` / `powershell.approved_script`）。

未挂 `capability_registry` 时走 fallback 路径（保留旧 `Enabled Skills:` / `Planned Modules:` 段落），并把 `metadata.capability_registry_fallback=True` 写到 snapshot 里，作为可见警告。

## 9. Future Work

| 版本 | 主题 |
|------|------|
| v0.8.1 | SkillSelector（按 intent 选择 Skill）+ Dynamic Tool Visibility（按会话态控制 visibility） |
| v0.8.2 | Result Contract 标准化（ModuleResult / ToolResult / AgentResult 三层 schema 统一） |
| v0.9 | Artifact Consumption Flow（基于 Capability Output Contract 跨能力级联：config_translation → knowledge → report） |
