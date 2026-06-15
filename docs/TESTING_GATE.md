# Testing Gate — Network Agent v2.0

本文档定义 Network Agent 的测试要求和发布门禁检查清单。

---

## 1. 测试层次

### 1.1 单元测试（Unit Tests）

**要求：** 每个 handler 函数和 service 函数必须有对应的单元测试。

**覆盖范围：**
- Tool handler 函数（`handle_*`）
- Module service 函数
- 辅助函数（`_ok`, `_error`, `_validate_workspace_path` 等）
- Schema 验证逻辑

**示例：**
```python
# harness/test_artifact_baseline.py
def test_handle_artifact_list():
    result = handle_artifact_list(inv)
    assert result["ok"] is True
    assert "artifacts" in result
```

### 1.2 合约测试（Contract Tests）

**要求：** 每个 Tool 必须有合约测试。

**验证内容：**
1. **Schema 匹配**：Tool 的 `input_schema` 与 handler 接受的参数一致
2. **Risk 正确**：`risk_level` 字段与实际行为匹配
3. **Approval 执行**：`high` risk 工具的 `requires_approval=True` 且审批流程正确执行
4. **返回值格式**：handler 返回符合标准化格式的 dict

**示例：**
```python
# harness/test_approval_guard.py
def test_high_risk_requires_approval():
    spec = registry.get("host.shell.exec")
    assert spec.risk_level == "high"
    assert spec.requires_approval is True
```

### 1.3 E2E 测试（End-to-End Tests）

**要求：** 每个业务链条必须有 E2E 测试。

**覆盖范围：**
- `user input → LLM → tools → result` 完整链条
- `config_translation` 闭环（翻译 → 审查 → 制品）
- `artifact` 闭环（创建 → 列表 → 读取 → 差异）
- `review` 闭环（创建 → 分配 → 裁决）

**示例：**
```python
# harness/test_config_translation_quality_hardening.py
def test_full_translation_chain():
    # user input → translation → review → artifact
    pass
```

### 1.4 回归测试（Regression Tests）

**要求：** 关键安全路径必须有回归测试。

**覆盖范围：**
- High-risk 审批门禁
- `config_translation` / `artifact` / `review` 闭环
- Sub-agent 工具隔离
- Context 安全投影（forbidden keys 过滤）

---

## 2. 发布门禁检查清单

发布前必须**全部通过**以下检查：

### Gate 1: 工具审计

```bash
python3 scripts/inspect_runtime_tools.py
```

**通过标准：**
- 输出显示注册工具数为 88
- 输出显示 LLM 可见工具数为 88
- High-risk 工具列表正确（`host.shell.exec`, `host.powershell.exec`, `python.exec`）
- 所有 high-risk 工具 `approval=True`
- Capability 计数正确（7 total, 4 enabled, 3 planned）
- Production Foundation readiness 全部 `OK`

### Gate 2: 文档一致性

```bash
python3 scripts/verify_docs_runtime_consistency.py
```

**通过标准：**
- exit code 0
- 所有检查项显示 `PASS`
- 无 `FAIL` 或 `WARNING`

### Gate 3: 测试套件

```bash
python3 -m pytest harness -q
```

**通过标准：**
- 所有测试通过
- 无 skipped 或 xfailed 测试（除非有明确注释说明原因）

### Gate 4: High-Risk 审批

**手动验证：**
- 所有 `risk_level=high` 的工具必须在 ToolSpec 中设置 `requires_approval=True`
- `agent/runtime/loop.py` 中 high-risk 审批路径可达
- `agent/approval.py` 中 `get_approval_store()` 可正常工作

**自动验证：**
```bash
python3 -c "
from agent.runtime.services import default_runtime_services
svc = default_runtime_services()
reg = svc.tool_service.registry
high = [t for t in reg.list_all() if getattr(t, 'risk_level', '') == 'high']
for t in high:
    assert getattr(t, 'requires_approval', False), f'{t.tool_id} missing requires_approval'
print(f'All {len(high)} high-risk tools have requires_approval=True')
"
```

### Gate 5: Sub-Agent 隔离

**验证内容：**
- Sub-agent 的 `DEFAULT_ALLOWED_TOOLS` 不包含任何 high-risk 工具
- Sub-agent 的 `FORBIDDEN_FOR_SUB_AGENT` 包含 `host.shell.exec`, `host.powershell.exec`, `python.exec`, `agent.spawn`
- Sub-agent 不能 spawn 子 agent
- `MAX_SUB_AGENT_TURNS = 3`

### Gate 6: 闭环完整性

**验证内容：**
- `config_translation` 闭环：翻译 → 审查 → 制品创建
- `artifact` 闭环：创建 → 列表 → 读取 → 差异
- `review` 闭环：创建 → 列表 → 详情

**自动验证：**
```bash
python3 -m pytest harness/test_artifact_baseline.py \
  harness/test_config_translation_quality_hardening.py \
  harness/test_knowledge_index_runtime.py -q
```

---

## 3. 测试运行命令

### 全部测试

```bash
python3 -m pytest harness -q
```

### 关键安全测试

```bash
python3 -m pytest harness/test_approval_guard.py -q
python3 -m pytest harness/test_artifact_source_path_size_guard.py -q
```

### Capability 测试

```bash
python3 -m pytest harness/test_config_translation_quality_hardening.py -q
python3 -m pytest harness/test_knowledge_index_runtime.py -q
python3 -m pytest harness/test_artifact_deep_integration.py -q
```

### 运行时测试

```bash
python3 -m pytest harness/test_loop_persistence.py -q
python3 -m pytest harness/test_session_api_contract.py -q
```

### Context/RAG 测试

```bash
python3 -m pytest harness/test_rag_context_foundation.py \
  harness/test_rag_context_eval_script.py -q
```

---

## 4. 新增测试模板

### 4.1 合约测试模板

```python
# harness/test_tool_contract_<name>.py

def test_<tool_id>_schema():
    """验证 tool schema 与 handler 一致"""
    reg = default_runtime_services().tool_service.registry
    spec = reg.get("<tool_id>")
    assert spec is not None, "Tool not found"
    assert spec.tool_id == "<tool_id>"
    assert spec.risk_level in ("low", "medium", "high")
    assert spec.input_schema, "Must have input_schema"
    if spec.risk_level == "high":
        assert spec.requires_approval, "High-risk must require approval"

def test_<tool_id>_handler():
    """验证 handler 返回标准化格式"""
    from tool_runtime.general_tools import handle_<name>
    from tool_runtime.schemas import ToolInvocation
    inv = ToolInvocation(tool_id="<tool_id>", arguments={"param": "value"})
    result = handle_<name>(inv)
    assert "ok" in result
    assert isinstance(result["ok"], bool)
```

### 4.2 E2E 测试模板

```python
# harness/test_v2_production_foundation_e2e.py

def test_full_chain_<feature>():
    """E2E: user input → LLM → tools → result"""
    # Setup
    # Execute
    # Assert
    pass
```

---

## 5. CI/CD 集成

建议的 CI 流水线：

```yaml
# .github/workflows/test.yml
steps:
  - name: Runtime Audit
    run: python3 scripts/inspect_runtime_tools.py
  - name: Docs Consistency
    run: python3 scripts/verify_docs_runtime_consistency.py
  - name: Unit & Contract Tests
    run: python3 -m pytest harness -q
  - name: High-Risk Audit
    run: python3 scripts/audit_registry_contract.py
  - name: Security Audit
    run: |
      python3 scripts/audit_artifact_security.py
      python3 scripts/audit_llm_security.py
      python3 scripts/audit_job_runtime_security.py
```
