# Extension Contract — Network Agent v2.0

本文档定义了扩展 Network Agent 系统的**强制性规则**和**标准路径**。
任何新增的 Capability、Module、Skill 或 Tool 都必须遵守以下约定。

---

## 十条扩展规则

### 规则 1：禁止修改运行时循环

`agent/runtime/loop.py` 中的 `run_turn()` 是核心执行引擎。
**除非进行框架级升级**，否则不得修改其控制流。

允许的修改范围：
- 修复 Bug
- 添加 hook 点（pre_turn / post_turn / pre_tool / post_tool / stop）
- 框架级安全加固

禁止的修改：
- 添加特例分支（special-case tool dispatch）
- 绕过 ToolRouter 直接调用 handler
- 修改 `_build_tool_message_payload` 的 allowlist 逻辑

### 规则 2：Tool 必须通过注册表注册

Tool 必须通过 `ToolRegistry` 注册，**不得直接暴露给 LLM**。

- 运行时工具：在 `tool_runtime/general_tools.py` 中使用 `_reg()` 注册
- Capability 工具：在 `agent/modules/<name>/tools.py` 中定义 `ToolSpec` + handler
- 注册后由 `ToolRouter.model_visible_tools()` 生成 LLM function definitions
- LLM 只能调用 `ToolRouter` 暴露的工具，无法绕过

### 规则 3：禁止绕过 high-risk 审批

所有 `risk_level=high` 的工具**必须经过审批门禁**（`requires_approval=True`）。

- 审批通过 `agent/approval.py` 的 `get_approval_store()` 进行
- `approval_id` 只接受来自 `/api/tools/invoke`（已验证）或受信任上下文的来源
- LLM 提供的 `approval_id` 不绕过审批
- 审批超时时间：120 秒

### 规则 4：禁止在 workspace 路径之外写入

所有文件写入操作必须限制在 `workspaces/<workspace_id>/` 内。

- `_validate_workspace_path()` 阻止路径穿越
- 不允许写入系统目录、配置目录或其他 workspace
- Workspace 根路径：`ROOT / "workspaces"`

### 规则 5：禁止读取 secrets

不得读取或暴露以下内容：
- API keys、tokens、passwords
- SSH 私钥
- 凭证文件
- 环境变量中的敏感值
- 本地配置文件（`config/llm.local.yaml`）

`_is_forbidden_prompt_key()` 在上下文投影时过滤这些 key。

### 规则 6：禁止访问真实设备

不允许以下操作暴露给 LLM：
- SSH / Telnet 连接
- SNMP 查询
- nmap / ping sweep 扫描
- 真实网络设备 API 调用

这些工具类别在 `VALID_TOOL_CATEGORIES` 中存在但不被注册或暴露。

### 规则 7：禁止 config.push

`config.push` 是**明确禁止**的操作。
虽然 parser category 可以生成翻译后的配置，但系统不会推送配置到设备。

Capability 的 `CapabilitySafetySpec.allows_config_push` 默认为 `False`，
`produces_deployable_config` 默认为 `False`。

### 规则 8：必须有测试

每个扩展必须包含：
- **单元测试**：per handler, per service function
- **合约测试**：per tool（验证 schema 匹配、risk 正确、approval 执行）
- **E2E 测试**：完整链条（user input → LLM → tools → result）

测试位置：`harness/` 目录，命名约定 `test_<feature>_<version>.py`

### 规则 9：必须被 inspect_runtime_tools.py 识别

新增的工具和 capability 必须被 `scripts/inspect_runtime_tools.py` 正确识别和统计。

- 工具必须出现在 `registered tools` 计数中
- Capability 必须出现在 capability 列表中
- 不能有未注册的"幽灵"工具

### 规则 10：文档工具计数必须自动验证

`README.md` 和 `docs/CAPABILITIES_AND_TOOLS.md` 中的工具计数必须与实际运行时一致。
使用 `scripts/verify_docs_runtime_consistency.py` 自动验证。

---

## 标准扩展路径

### 添加 Capability

```
agent/modules/<name>/capability.py     # CapabilityManifest 定义
agent/modules/<name>/tools.py          # ToolSpec + handler
agent/modules/<name>/service.py        # 业务逻辑
agent/modules/<name>/__init__.py

agent/capabilities/builtin.py          # 注册到 BUILTIN_CAPABILITIES
```

1. 在 `agent/modules/<name>/capability.py` 中定义 `CAPABILITY_<NAME>` (CapabilityManifest)
2. 在 `agent/capabilities/builtin.py` 的 `BUILTIN_CAPABILITIES` 列表中添加
3. 状态设为 `planned`，完成实现后改为 `enabled`
4. 运行 `python3 scripts/inspect_runtime_tools.py` 验证

### 添加 Tool（运行时工具）

```
tool_runtime/general_tools.py
```

使用 `_reg()` 函数注册：

```python
_reg("category.name", "Display Name", "category", "risk_level",
     "Description of what the tool does", handler_function)
```

同时需要在 `GENERAL_TOOL_INPUT_SCHEMAS` 字典中添加对应的 schema。

### 添加 Tool（Capability 工具）

```
agent/modules/<name>/tools.py
```

定义 `ToolSpec` 实例和 handler 函数，在 CapabilityManifest 中通过 `CapabilityToolRef` 引用。

### 添加 Module

```
agent/modules/<name>/capability.py
agent/modules/<name>/tools.py
agent/modules/<name>/service.py
agent/modules/<name>/__init__.py
```

Module 通过 `agent/modules/registry.py` 的 `ModuleRegistry.from_capabilities()` 自动注册。

### 添加 Skill

```
skills/<name>/SKILL.md      # LLM 可读的指令文档
skills/<name>/skill.yaml    # 元数据（推荐）
skills/<name>/adapter.py    # 遗留适配器（可选）
```

Skill 通过 CapabilityManifest 的 `CapabilitySkillSpec` 注册。

---

## 扩展检查清单

扩展完成后，逐项验证：

- [ ] `python3 scripts/inspect_runtime_tools.py` 通过
- [ ] `python3 scripts/verify_docs_runtime_consistency.py` 通过
- [ ] `python3 -m pytest harness -q` 全部通过
- [ ] README.md 工具计数已更新
- [ ] docs/CAPABILITIES_AND_TOOLS.md 已更新
- [ ] 无 high-risk 工具缺少 `requires_approval=True`
- [ ] 无工具写入 workspace 之外的路径
- [ ] 无工具暴露 secrets 或真实设备访问
- [ ] 新增测试覆盖 unit/contract/E2E
