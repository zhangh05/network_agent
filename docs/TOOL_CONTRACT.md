# Tool Contract — Network Agent v2.2

本文档定义每个 Tool 的**必需字段**、**标准化返回值**、和**风险等级规则**。

---

## 1. Tool 必需字段

每个 Tool（运行时工具和 Capability 工具）**必须**填充以下字段：

### 1.1 标识字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `tool_id` | str | 分类.名称 格式 | `"web.search"`, `"artifact.list"` |
| `name` | str | 人类可读名称 | `"Web Search"`, `"List Artifacts"` |
| `description` | str | 功能描述（LLM 可见） | `"Search the web for current information"` |

v2.2 adds a namespace metadata layer. The execution `tool_id` remains the
stable runtime id; the canonical id is used by LLM and frontend catalog views.

| Metadata 字段 | 类型 | 说明 |
|------|------|------|
| `canonical_tool_id` | str | 目录化展示/LLM 调用 id，例如 `workspace.file.read` |
| `execution_tool_id` | str | 实际执行 id，例如 `file.read` |
| `legacy_tool_ids` | list[str] | 兼容旧 id 和别名；不注册成额外工具 |
| `category` | str | 顶层目录：`host`, `workspace`, `knowledge`, `network`, `web`, `runtime`, `memory`, `report_data`, `agent` |
| `group` | str | 小类目录，例如 `file`, `artifact`, `config`, `docs` |
| `action` | str | 动作，例如 `read`, `search`, `exec`, `render` |
| `display_name` / `short_label` | str | 前端展示名称 |
| `usage_hint` / `not_for` | str | 选择提示和边界说明 |

### 1.2 分发字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `category` | str | 工具分类：`artifact`, `parser`, `report`, `command`, `knowledge`, `web`, `session`, `runtime`, `text`, `workspace`, `shell`, `powershell`, `python`, `skill`, `memory` |
| `callable_by_llm` | bool | LLM 是否可直接调用。`False` 表示仅 backend/API 可调用 |
| `enabled` | bool | 是否激活。`False` 的工具不注册到 ToolRegistry |
| `forbidden` | bool | 是否被禁止。`True` 时 `callable_by_llm` 必须为 `False` |

### 1.3 安全字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `risk_level` | str | `low` / `medium` / `high` / `forbidden` |
| `requires_approval` | bool | `high` risk 必须 `True` |

### 1.4 生命周期字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `timeout_seconds` | int | 30 | 超时时间 |
| `dry_run_supported` | bool | True | 是否支持干运行 |

### 1.5 Schema 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `input_schema` | dict (JSON Schema) | **每个参数必须有 `description`** |
| `output_schema` | dict (JSON Schema) | 可选，推荐 |

### 1.6 实现字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `handler` | callable | 执行函数 |
| `source` | str | `"runtime"` 或 `"capability:<name>"` |

### 1.7 测试字段

| 要求 | 说明 |
|------|------|
| `tests` | 必须有对应的单元测试、合约测试和 E2E 测试 |

---

## 2. 标准化返回值

所有 tool handler 必须返回结构化 dict，包含以下字段：

```python
{
    "ok": True,                    # bool: 操作是否成功
    "status": "succeeded",         # str: succeeded | failed | blocked | dry_run
    "summary": "...",             # str: 简短摘要
    "data": {},                   # dict: 主要数据（可选）
    "result": {},                 # dict: 结果数据（可选）
    "warnings": [],               # list[str]: 警告信息
    "errors": [],                 # list[str]: 错误信息
    "artifacts": [],              # list[dict]: 关联的 artifact 引用
    "source_count": 0,            # int: 返回的来源/条目数量
    "manual_review_count": 0,     # int: 需要人工审查的条目数
    "metadata": {},               # dict: 额外元数据
}
```

### 2.1 辅助函数

`tool_runtime/general_tools.py` 提供标准辅助函数：

```python
def _ok(output: dict = None) -> dict:
    return {"ok": True, **(output or {})}

def _error(msg: str) -> dict:
    return {"ok": False, "error": msg}
```

### 2.2 ToolResult 标准化

`tool_runtime/schemas.py` 提供 `ToolResult` dataclass：

```python
@dataclass
class ToolResult:
    invocation_id: str = ""
    tool_id: str = ""
    status: str = "succeeded"    # succeeded | failed | blocked | dry_run
    output: dict = field(default_factory=dict)
    summary: str = ""
    artifact_ids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duration_ms: int = 0
    redacted: bool = False
    policy_decision: Optional[PolicyDecision] = None
```

---

## 3. 风险等级规则

### 3.1 low（低风险）

**适用于：** 只读查询/检查工具，无副作用

| 条件 | 说明 |
|------|------|
| 只读操作 | 不修改任何状态 |
| 无网络调用 | 仅访问本地存储 |
| `requires_approval=False` | 无需审批 |

示例：`artifact.list`, `session.list`, `memory.search`, `knowledge.query`

### 3.2 medium（中风险）

**适用于：** 写操作、网络调用、状态变更

| 条件 | 说明 |
|------|------|
| 写操作 | 修改 artifact、memory、session 状态 |
| 网络调用 | 外部 API、Web 搜索 |
| 状态变更 | 创建/删除资源 |

示例：`web.search`, `weather.current`, `artifact.save_result`, `memory.create`

### 3.3 high（高风险）

**适用于：** 任意代码执行、系统级操作

| 条件 | 说明 |
|------|------|
| `requires_approval=True` | **必须经过审批门禁** |
| 审批时间限制 | 120 秒超时 |
| 审批存储 | `data/tool_approvals.json` |

示例：`shell.exec`, `powershell.exec`, `python.exec`

### 3.4 forbidden（禁止）

**适用于：** 已退役或明确禁止的操作

| 条件 | 说明 |
|------|------|
| `callable_by_llm=False` | 不可被 LLM 调用 |
| 不注册到 ToolRegistry | 不出现在任何工具列表中 |

---

## 4. Tool 注册模板

### 4.1 运行时工具注册

在 `tool_runtime/general_tools/registry.py` 中注册，handler body 位于
`tool_runtime/general_tools/*.py` 子模块中。`tool_runtime/general_tools_base.py`
仅是兼容 shim，不保存 handler 实现。

```python
# 注册
_reg("category.tool_name", "Display Name", "category", "risk_level",
     "Description of what this tool does", handle_function)

# Schema
GENERAL_TOOL_INPUT_SCHEMAS = {
    "category.tool_name": _schema({
        "param1": {"type": "string", "description": "Description of param1"},
        "param2": {"type": "integer", "description": "Description of param2", "default": 10},
    }),
}

# Handler
def handle_function(inv: ToolInvocation) -> dict:
    args = inv.arguments
    # ... implementation ...
    return _ok({"result": "data"})
```

v2.2 namespace 映射维护在 `tool_runtime/tool_namespace.py` 和
`tool_runtime/tool_namespace_data.py`。新增工具必须同时更新：

- `baselines/execution_tool_ids_v2.2.txt`
- `baselines/canonical_tool_ids_v2.2.txt`
- `baselines/tool_aliases_v2.2.json`
- `scripts/inspect_tool_namespace.py`

### 4.2 Capability 工具注册

在 `agent/modules/<name>/tools.py` 中：

```python
from tool_runtime.schemas import ToolSpec

TOOL_MY_TOOL = ToolSpec(
    tool_id="my_category.my_tool",
    name="My Tool",
    description="What this tool does",
    category="my_category",
    risk_level="low",
    input_schema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    },
    requires_approval=False,
    callable_by_llm=True,
    enabled=True,
)

def tool_handler(inv: ToolInvocation) -> dict:
    # ... implementation ...
    return {"ok": True, "summary": "Done", "data": {}}
```

---

## 5. 验证

所有 Tool 必须通过以下验证：
- `python3 scripts/inspect_runtime_tools.py` — 工具审计
- Contract test：验证 schema 匹配 handler、risk_level 正确、approval 执行正确
- E2E test：完整调用链条验证
