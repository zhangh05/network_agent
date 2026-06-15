# Capability Contract — Network Agent v2.0

本文档定义 Capability 的**完整生命周期**、**注册流程**、和**当前已注册的 Capability 列表**。

---

## 1. Capability 生命周期

```
 ┌──────────┐     ┌──────────┐     ┌───────────┐
 │ planned  │ ──→ │ enabled  │ ──→ │ disabled  │
 └──────────┘     └──────────┘     └───────────┘
```

- **planned**：已注册但未激活。不可调用、不可注入、不可暴露给 LLM。
- **enabled**：已激活。其 tools/skills/modules 可参与运行时。
- **disabled**：显式关闭。保留在注册表中但不可用。

**关键约束：**
- 状态只能**单向**转换：`planned → enabled → disabled`
- **永不删除** Capability（保留审计历史）
- `planned` 状态不能有任何 `enabled` 的 tool
- `planned` 状态的 tool 必须 `callable_by_llm=False`

---

## 2. CapabilityManifest 完整结构

定义在 `agent/capabilities/schemas.py`。每个 Capability 必须声明：

### 2.1 基础信息
- **capability_id** (str): 唯一标识，如 `"config_translation"`
- **name** (str): 人类可读名称
- **status** (str): `enabled` | `planned` | `disabled`
- **description** (str): 功能描述

### 2.2 Module（业务实现层）
- **module_id** (str): 模块标识
- **service_path** (str): Python 模块路径，如 `"agent.modules.config_translation.service"`
- **operations** (list[str]): 入口操作名称
- **status** (str): 模块状态

### 2.3 Skills（行为指导）
每个 Skill 通过 `CapabilitySkillSpec` 声明：
- **skill_id** (str): 技能标识
- **intent_patterns** (list[str]): 触发意图模式
- **required_inputs** (list[str]): 必要输入
- **preconditions** (list[str]): 前置条件
- **postconditions** (list[str]): 后置条件
- **safety_rules** (list[str]): 安全规则
- **related_tools** (list[str]): 关联的工具 ID

### 2.4 Tools（LLM 可调用入口）
每个 Tool 通过 `CapabilityToolRef` 声明：
- **tool_id** (str): 工具标识
- **status** (str): 工具状态
- **callable_by_llm** (bool): LLM 是否可调用
- **risk_level** (str): `low` | `medium` | `high` | `forbidden`
- **requires_approval** (bool): 是否需要审批
- **forbidden** (bool): 是否禁止
- **handler_ref** (str): handler 的 Python 路径
- **input_schema** (dict): JSON Schema
- **description** (str): 工具描述

### 2.5 Outputs（产出合约）
每个 Output 通过 `CapabilityOutputSpec` 声明 capability 会产出什么：
- **output_id** / **output_type** / **artifact_type**
- **sensitivity**：`public` | `internal` | `sensitive` | `secret`
- **authoritative**：是否是该产出的权威生产者

### 2.6 Safety（安全合约）
通过 `CapabilitySafetySpec` 声明安全边界：
- **real_device_access** (bool): 默认 `False`
- **allows_config_push** (bool): 默认 `False`
- **produces_deployable_config** (bool): 默认 `False`
- **may_fabricate_sources** (bool): 默认 `False`
- **requires_human_review** (bool): 默认 `False`

### 2.7 依赖
- **dependencies** (list[str]): 依赖的其他 capability_id

### 2.8 元数据
- **metadata** (dict): 任意附加信息

---

## 3. 注册流程

### 3.1 创建 Capability

在 `agent/modules/<name>/capability.py` 中定义 `CAPABILITY_<NAME>` 常量：

```python
from agent.capabilities.schemas import (
    CapabilityManifest, CapabilityModuleSpec, CapabilitySkillSpec,
    CapabilityToolRef, CapabilityOutputSpec, CapabilitySafetySpec
)

CAPABILITY_EXAMPLE = CapabilityManifest(
    capability_id="example",
    name="Example Capability",
    status="planned",
    description="An example capability",
    module=CapabilityModuleSpec(
        module_id="example",
        status="planned",
        service_path="agent.modules.example.service",
        operations=["run_example"],
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="example_skill",
            status="planned",
            intent_patterns=["run example", "do example"],
            required_inputs=["input_data"],
            safety_rules=["Do not access real devices"],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="example.run",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            handler_ref="agent.modules.example.tools.tool_handler",
            description="Run the example tool",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="example_result",
            output_type="result_data",
            artifact_type="example_result",
            sensitivity="internal",
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
    ),
)
```

### 3.2 注册到 Registry

在 `agent/capabilities/builtin.py` 的 `BUILTIN_CAPABILITIES` 列表中添加：

```python
from agent.modules.example.capability import CAPABILITY_EXAMPLE

BUILTIN_CAPABILITIES: list[CapabilityManifest] = [
    # ... existing capabilities ...
    CAPABILITY_EXAMPLE,
]
```

### 3.3 激活

1. 完成 Module 实现（`service.py`）
2. 完成 Tool 实现（`tools.py`）
3. 更新 status 为 `enabled`
4. 运行 `python3 scripts/inspect_runtime_tools.py` 验证

---

## 4. 当前 Capability 清单

共 **7 个** Capability，在 `agent/capabilities/builtin.py` 中注册。

### 4.1 Config Translation (enabled)

| 属性 | 值 |
|------|----|
| `capability_id` | `config_translation` |
| `status` | `enabled` |
| `module` | `config_translation` |
| `skill` | `config_translation` |
| `safety.allows_config_push` | `False` |

**Tool：** `config.translate`

网络配置格式转换和语义验证。

### 4.2 Knowledge / RAG (enabled)

| 属性 | 值 |
|------|----|
| `capability_id` | `knowledge` |
| `status` | `enabled` |
| `module` | `knowledge` |
| `skill` | `knowledge_query` |

**Tools：** `knowledge.query`, `knowledge.list_sources`, `knowledge.search`,
`knowledge.read_chunk`, `knowledge.read_parent`, `knowledge.import_document`,
`knowledge.import_file`, `knowledge.import_chunks`, `knowledge.index_artifact`,
`knowledge.reindex`

RAG 知识库：文档导入、索引构建、语义搜索、分块读取。

### 4.3 Artifact Management (enabled)

| 属性 | 值 |
|------|----|
| `capability_id` | `artifact` |
| `status` | `enabled` |
| `module` | `artifact` |
| `skill` | `artifact_management` |

**Tools：** `artifact.list`, `artifact.read`, `artifact.diff`, `artifact.export`,
`workspace.artifact.save`

制品生命周期管理：列表、读取、保存、差异对比、导出。

### 4.4 Manual Review (enabled)

| 属性 | 值 |
|------|----|
| `capability_id` | `review` |
| `status` | `enabled` |
| `module` | `review` |
| `skill` | `review_flow` |

**Tools：** `review.list`, `review.get_detail`

人工评审流程：创建、分配、裁决。

### 4.5 Topology (planned)

| 属性 | 值 |
|------|----|
| `capability_id` | `topology` |
| `status` | `planned` |
| `module` | `topology` |
| `skill` | `topology` |

**Tools：** `topology.draw`（planned，不可调用）

网络拓扑绘制与分析。

### 4.6 Inspection (planned)

| 属性 | 值 |
|------|----|
| `capability_id` | `inspection` |
| `status` | `planned` |
| `module` | `inspection` |
| `skill` | `inspection` |

**Tools：** `inspection.run`（planned，不可调用）

网络巡检与合规检查。

### 4.7 CMDB (planned)

| 属性 | 值 |
|------|----|
| `capability_id` | `cmdb` |
| `status` | `planned` |
| `module` | `cmdb` |
| `skill` | `cmdb` |

**Tools：** `cmdb.query`（planned，不可调用）

配置管理数据库。

---

## 5. Capability 验证

### 5.1 自动验证

```bash
python3 scripts/inspect_runtime_tools.py
```

输出包含：
- Capability 总数、enabled/planned/disabled 计数
- 每个 Capability 的名称和状态

### 5.2 手动检查

- 检查 `agent/capabilities/builtin.py` 中 `expected` 集合包含所有已注册的 capability_id
- `planned` capability 不应有 enabled 的 tool
- `enabled` capability 必须有 module 和至少一个 tool
