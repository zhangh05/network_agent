# Network Agent — Release History

> 完整版本演化表（v0.6 → v0.7.1）。
> README 中的"Version Evolution"是本表的摘要。
> 配套：[README.md](../README.md) · [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) · [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## 主线阶段

| 阶段 | 版本区间 | 主题 |
|------|---------|------|
| Runtime 底座 | v0.6 ~ v0.6.3 | Codex-style Runtime 替换旧 LangGraph 7-node |
| Capability Layer | v0.7 ~ v0.7.1 | config_translation / knowledge_query 接入；artifact / source 质量对齐 |

## 完整版本表

| Commit | Version | Title | Key Changes | Runtime 主链 |
|--------|---------|-------|-------------|--------------|
| `f45c3053` | v0.6 | rewrite backend around codex-style runtime | 删除 `agent/graph.py` + `agent/nodes/*` 主链，迁入 `agent/legacy/`；新增 `agent/{app,core,runtime,protocol,context,tools,skills,modules,audit}/`；新增 `POST /api/agent/message`；15 tests | **重写** |
| `569982a8` | v0.6 | finalize codex-style runtime | 修复 `agent.legacy` 动态导入路径；更新 harness 路径；新增 [AGENT_BACKEND_RUNTIME_V06.md](AGENT_BACKEND_RUNTIME_V06.md) | 稳定化 |
| `e5487212` | v0.6.1 | stabilize codex-style runtime | 注册 `/api/agent/message` 路由；`AgentResult.to_dict()` 补 `events` 字段；新增 25 tests | **不变** |
| `bf555a0a` | v0.6.2 | stabilize rate limit and provider timeout | 修复 `RATE_LIMIT_DISABLED` 跨测试污染；URLError timeout 归类为 `provider_timeout`，`retryable=True`；中文友好超时；新增 16 tests | **不变** |
| `2ae76bcb` | v0.6.3 | harden runtime tool routing | `default_runtime_services` 构建真实 `ToolRouter`；`llm_name_map` 白名单（未知 tool → `tool_call_failed`）；`RuntimeSnapshot` 区分 `total_tool_count` / `visible_tool_count`；System prompt 升级为 Runtime Contract；新增 20 tests | **不变** |
| `ff6cff5d` | v0.7 | integrate config translation and knowledge capabilities | 接入 `config_translation.translate_config` 与 `knowledge.query`；Tool 数 55 → **57**；`topology` / `inspection` / `cmdb` 仍 planned；新增 21 tests | **不变** |
| `15565d18` | v0.7.1 | enrich capability artifacts and sources | `translated_config` 保存为 artifact（`authoritative=false, deployable_config=false`）；`manual_review_items` 结构化；knowledge `source_summary`（≤200 字符，无伪造）；`AgentResult.tool_calls` 增强；`ToolResultMessage.content` 1000 → 2000 字符；新增 20 tests | **不变** |
| `0d160ce` | v0.7.1 sync | docs baseline sync (README + ARCHITECTURE + CAPABILITY_LAYER_V071 + RELEASE_HISTORY) | 文档基线同步到 v0.7.1；新增 `docs/CAPABILITY_LAYER_V071.md` | **不变** |
| `1c9f89b` | v0.7.1 align | align legacy provider timeout diagnostics assertion | 修复 v0.5 `test_timeout_returns_provider_timeout` 断言（accept "timeout" / "timed out" 两种 wording，主断言 `metadata.provider_error_type == "provider_timeout"`）；新增 wording-agnostic regression test | **不变** |
| TBD (v0.8) | v0.8 | introduce capability manifest registry | 新增 `agent/capabilities/{schemas,registry,builtin}.py` + 5 个 module `capability.py`；`CapabilityRegistry` 作为能力真相源；`ModuleRegistry.from_capabilities()` / `SkillRegistry.from_capabilities()` / `ToolRegistry.register_capability_tools()`；`RuntimeServices.capability_registry` 字段；`RuntimeSnapshot.build_runtime_snapshot()` 优先从 CapabilityRegistry 投影；`planned` 三个 capability 仍 `NOT callable`；Tool count 仍 = 57；新增 20 tests | **不变** |
| TBD (v0.8.1) | v0.8.1 | add skill selector and dynamic tool visibility | 新增 `agent/skills/selector.py`（`SkillSelector` + `select_skills` rule-based API：assistant_chat always-on + intent_patterns 命中 + capability_discovery meta-skill + planned 绝不注入 + 异常 fallback）；`ToolRouter.apply_dynamic_visibility()`（fail-closed 交集 = `registry_visible ∩ allowed_tool_ids`）；`RuntimeServices.skill_selector` 字段；`ContextBuilder` 每轮调用 selector + 同步 router + 异常 fallback；`RuntimeSnapshot.selected_skills` / `selected_visible_tools` / `dynamic_tool_visibility` 新字段 + `to_prompt_text()` 新增 per-turn 段落；新增 23 tests | **不变** |

## 各版本能力对照

| 能力 | v0.6 | v0.6.1 | v0.6.2 | v0.6.3 | v0.7 | v0.7.1 |
|------|------|--------|--------|--------|------|--------|
| Codex-style Runtime | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/api/agent/message` | ✓ | ✓ 注册 | ✓ | ✓ | ✓ | ✓ |
| AgentResult.events | partial | ✓ | ✓ | ✓ | ✓ | ✓ |
| Runtime 稳定性 (rate limit / provider timeout) | — | — | ✓ | ✓ | ✓ | ✓ |
| ToolRouter 真实 catalog | — | — | — | ✓ | ✓ | ✓ |
| `llm_name_map` 白名单 | — | — | — | ✓ | ✓ | ✓ |
| System prompt = Runtime Contract | — | — | — | ✓ | ✓ | ✓ |
| `config_translation.translate_config` | — | — | — | — | ✓ | ✓ |
| `knowledge.query` | — | — | — | — | ✓ | ✓ |
| `translated_config` artifact (authoritative=false) | — | — | — | — | — | ✓ |
| `manual_review_items` 结构化 | — | — | — | — | — | ✓ |
| `source_summary` (≤200 字符) | — | — | — | — | — | ✓ |
| `AgentResult.tool_calls` 增强 | — | — | — | — | — | ✓ |
| `ToolResultMessage.content` 2000 字符 | — | — | — | — | — | ✓ |
| **Tool count** | 55 | 55 | 55 | 55 | **57** | **57** |

## 各版本安全边界

v0.6 → v0.7.1 **始终保持**：

- **No real device access**（无 SSH / Telnet / SNMP / nmap / ping sweep）
- **`config.push` 永久禁止**
- **No authoritative deployable_config**（v0.7.1 起写入 artifact metadata）
- **Tool execution centralization**（ToolRouter → ToolRuntimeClient）
- **planned modules (topology / inspection / cmdb) NOT callable**（v0.7+ 显式）

## 不变量（v0.6 → v0.7.1 一致）

1. **Runtime 主链调用路径**：`API → AgentApp → AgentThread → AgentSession → AgentTurn → RuntimeLoop → invoke_llm`
2. **工具执行唯一入口**：`ToolRouter → ToolRuntimeClient`，不绕过 ToolPolicy / ToolExecutor / Redaction / Audit
3. **Tool 名称映射**：`. ↔ __`，由 `ToolRouter.llm_name_map` 集中维护
4. **高危工具白名单 + approval_id 鉴权**
5. **planned 模块永不注入、永不允许 LLM 调用**
6. **`config.push` 永久禁止**（无对应 tool、ToolRuntime regex 拦截）

## 测试基线（2026-06-10，developer machine）

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| v0.8.1 skill selector (focused) | **23** | 0 | 0 |
| v0.8 capability manifest (focused) | **20** | 0 | 0 |
| v0.7/v0.7.1 capability (focused) | **41** | 0 | 0 |
| v0.6.x ~ v0.8.1 broader focused regression | **658** | 7 | 0 |
| Full harness `pytest harness -q` | — | — | Not re-run (docs-only sync) |

> 2026-06-10 update：曾记录的 v0.5 `test_llm_provider_diagnostics_v05.py::test_timeout_returns_provider_timeout` 失败已在同日的 legacy diagnostics alignment 中修复（断言改为兼容 "timeout" / "timed out" 两种文案，并主断言 `metadata.provider_error_type == "provider_timeout"`）。broader focused regression 由 613 passed / 1 failed 提升至 **615 passed / 0 failed**（+1 = 新增的 wording-agnostic regression test）。

> 完整说明见 [README.md §"Test Baseline"](../README.md)。
