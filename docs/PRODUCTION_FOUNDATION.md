# Network Agent v2.0 — Production Foundation

本文档定义 Network Agent v2.0 生产级架构的核心概念、组件边界和运行时合约。

---

## 1. 核心概念

### 1.1 Capability（业务能力）

Capability 是业务领域的分组单元，将相关的 Module、Skill 和 Tool 捆绑在一起，
形成可治理的业务能力单元。每个 Capability 有明确的状态：

| 状态 | 含义 |
|------|------|
| `enabled` | 已激活，其声明的 tools/skills/modules 可通过 ToolRouter 暴露给 LLM |
| `planned` | 已注册但未激活，仅供 roadmap 可见，**不可调用、不可注入** |
| `disabled` | 显式关闭，不参与任何运行时流程 |

**Capability 三不原则：**
- `planned` capability 不暴露任何 enabled tool 给 LLM
- `planned` capability 的 `callable_by_llm` 必须为 `False`
- Capability 状态只能 `planned → enabled → disabled`，**永不删除**

**当前 7 个 Capability：**

| Capability | Status | 职责 |
|------------|--------|------|
| `config_translation` | enabled | 网络配置的格式转换和语义验证 |
| `knowledge` | enabled | RAG 知识库：导入、索引、搜索、分块 |
| `artifact` | enabled | 制品生命周期管理：列表、读取、保存、差异对比 |
| `review` | enabled | 人工评审流程：创建、分配、裁决 |
| `topology` | planned | 网络拓扑绘制与分析 |
| `inspection` | planned | 网络巡检与合规检查 |
| `cmdb` | planned | 配置管理数据库 |

### 1.2 Module（编排层）

Module 是 **业务实现层**，编排 tools/skills/context 到具体的任务流程中。
Module 不直接暴露给 LLM。

**关键约束：**
- Module 不知道 LLM / Skill / ToolRouter 的存在
- Module 通过 service 函数实现业务逻辑
- Capability 的 `module.service_path` 指向 Module 的 service 实现
- Module 不包含 risk/approval 元数据——这些属于 Tool 层

**标准路径：** `agent/modules/<name>/service.py`

### 1.3 Skill（行为指导）

Skill 为 LLM 提供**行为指导**——告诉模型何时使用 Capability、需要什么输入、
有什么前置/后置条件。Skill **不执行代码**，**不绕过 ToolRouter**。

**关键约束：**
- Skill 不执行代码，不调用 handler
- Skill 不直接注入系统提示词；`skill.request_load` 仅记录请求
- Skill 通过 `CapabilitySkillSpec` 声明：`intent_patterns`、`required_inputs`、`preconditions`、`postconditions`、`safety_rules`
- Skill 通过 `skill.yaml` + `SKILL.md` 定义；`adapter.py` 为可选遗留适配器

**标准路径：** `skills/<name>/SKILL.md` + `skill.yaml` + `adapter.py`（可选）

### 1.4 Tool（原子执行单元）

Tool 是 LLM 可调用的**原子执行单元**。每个 Tool 必须声明：

- **schema**：输入/输出 JSON Schema
- **risk**：风险等级（low/medium/high/forbidden）
- **approval**：是否需要审批
- **timeout**：超时时间
- **handler**：执行函数
- **tests**：单元测试、合约测试、E2E 测试

**关键约束：**
- `high-risk` 必须 `requires_approval=True`
- `approval_id` 只能由 `/api/tools/invoke` 或受信任的 `ToolRuntimeContext` 提供
- LLM 提供的 `approval_id` 不绕过审批门禁
- Tool 通过 `tool_runtime/general_tools.py`（运行时工具）或 `agent/modules/<name>/tools.py`（Capability 工具）注册

### 1.5 Agent Runtime（运行时引擎）

Agent Runtime 是核心执行循环，位于 `agent/runtime/loop.py`。

**执行流程：**

```
run_turn()
  │
  ├─ 1. 审计事件：turn_started
  ├─ 2. 构建上下文：build_turn_context()
  │     ├─ session history
  │     ├─ workspace state
  │     ├─ RAG knowledge / memory citations
  │     ├─ capability snapshot
  │     ├─ skill injections
  │     └─ ToolRouter (model-visible tools)
  ├─ 3. 构建消息：system prompt + snapshot + skill + history + user input
  ├─ 4. LLM 调用：invoke_llm()
  │     ├─ token hard limit (90% of max_context)
  │     ├─ context compaction (auto before hard reject)
  │     └─ tool loop (max 8 steps)
  ├─ 5. ToolRouter
  │     ├─ build_tool_call() — 拒绝未知/不可见工具
  │     ├─ pre_tool hook — 可拒绝/修改
  │     ├─ approval gate — high-risk 必经
  │     ├─ dispatch() — capability handler 或 ToolRuntime
  │     └─ result → safe projection → LLM
  ├─ 6. 结果：AgentResult
  │     ├─ final_response, tool_calls, warnings, errors
  │     ├─ artifacts, source_count, manual_review_count
  │     └─ metadata (selected_skills, visible_tools, context_sources)
  └─ 7. 持久化
        ├─ run record (workspace/run_store)
        ├─ session messages (workspace/message_store)
        ├─ trace events (workspace/runs/<id>.trace.json)
        └─ rollout record
```

---

## 2. 当前统计数据

| 指标 | 数值 |
|------|------|
| 注册工具总数 | 88 |
| LLM 可见工具数 | 88 |
| Capability 总数 | 7 |
| Enabled Capability | 4 (`config_translation`, `knowledge`, `artifact`, `review`) |
| Planned Capability | 3 (`topology`, `inspection`, `cmdb`) |
| High-Risk 工具 | 3 (`host.shell.exec`, `host.powershell.exec`, `python.exec`) |
| High-Risk 均需审批 | 是（全部 `requires_approval=True`） |
| Sub-Agent 默认可见工具 | 36（仅只读低风险工具） |
| MAX_STEPS | 8 |
| MAX_SUB_AGENT_TURNS | 3 |

---

## 3. 显式安全边界

以下操作**不在当前运行时边界内**，不可暴露给 LLM：

| 禁止操作 | 状态 |
|----------|------|
| 真实设备访问 | 不允许 |
| `config.push`（配置推送） | 禁止 |
| SSH / Telnet / SNMP | 不暴露 |
| nmap / ping sweep | 不暴露 |
| 任意文件读写 | 限制在 workspace 路径内 |
| 读取 secrets / tokens / API keys | 禁止 |

**`python.exec` 安全性声明：**
- `python.exec` 是 high-risk 审批工具
- 只运行 allowlisted Python 脚本
- 需要 `approval_id` 门禁
- **不是容器隔离**，是 best-effort 沙箱

**上下文安全投影：**
- `ToolResult` 数据通过 allowlist 投影后才返回 LLM
- 禁止字段：`source_config`, `raw_config`, `secret`, `password`, `token`, `api_key`, `authorization`, `credentials`, `ssh_key`, `private_key`
- 结果字段 `max_text=4000`，嵌套值 `max_text=1200`

**Sub-Agent 隔离：**
- Sub-agent 使用受限 ToolRouter，仅包含 `DEFAULT_ALLOWED_TOOLS`
- 禁止工具包括：`host.shell.exec`, `host.powershell.exec`, `python.exec`, `agent.spawn`, 所有写操作工具
- Sub-agent 不可 spawn 子 agent（防止递归嵌套）
- `max_turns ≤ 3`

---

## 4. Capability Manifest 数据模型

定义在 `agent/capabilities/schemas.py`：

```python
CapabilityManifest
  capability_id: str           # e.g. "config_translation"
  name: str                    # 人类可读名称
  status: str                  # enabled | planned | disabled
  description: str
  module: CapabilityModuleSpec  # 业务实现层引用
  skills: list[CapabilitySkillSpec]  # LLM 行为指导
  tools: list[CapabilityToolRef]     # LLM 可调用入口
  outputs: list[CapabilityOutputSpec]  # 产出合约
  safety: CapabilitySafetySpec          # 安全合约
  dependencies: list[str]
  metadata: dict
```

---

## 5. ToolSpec 数据模型

定义在 `tool_runtime/schemas.py`：

```python
ToolSpec
  tool_id: str                # e.g. "network.config.parse"
  name: str                   # 显示名称
  description: str            # 功能描述
  category: str               # artifact|parser|report|command|knowledge|web|...
  risk_level: str             # low | medium | high | forbidden
  input_schema: dict          # JSON Schema
  output_schema: dict         # JSON Schema (optional)
  timeout_seconds: int        # 默认 30
  dry_run_supported: bool
  requires_approval: bool     # high-risk 必须 True
  callable_by_llm: bool
  enabled: bool
  forbidden: bool             # True 时 callable_by_llm 必须 False
```

---

## 6. 注册表层次

```
CapabilityRegistry (agent/capabilities/)
  ├── builtin.py — 默认 7 个 Capability
  │
  ├── ModuleRegistry — 从 CapabilityRegistry 派生
  ├── SkillRegistry  — 从 CapabilityRegistry 派生
  └── ToolRegistry   — ToolRuntime catalog + Capability tools
       │
       └── ToolRouter (per-turn)
            └── model_visible_tools() → LLM function definitions
```

`ToolRegistry` 构建顺序：
1. 从 `tool_runtime.integration` 加载 ToolRuntime catalog
2. 从 `CapabilityRegistry` 注册 capability-layer tools
3. Capability tools 覆盖同 ID 的 runtime tools

---

## 7. 成熟度检查点

本文档由以下脚本验证：
- `python3 scripts/inspect_runtime_tools.py` — 运行时工具审计
- `python3 scripts/verify_docs_runtime_consistency.py` — 文档一致性检查
- `python3 -m pytest harness -q` — 测试套件

**Production Foundation Readiness 标准：**
- `tool_contract_ok` — 所有工具具有必需字段
- `approval_contract_ok` — 所有 high-risk 工具 `requires_approval=True`
- `docs_consistency_ok` — 工具计数与文档一致
- `e2e_tests_present` — E2E 测试文件存在
- `extension_templates_present` — 扩展模板目录存在
