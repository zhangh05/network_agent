# Capabilities And Tools

## 分层

- **Capability**：面向用户的能力边界，例如报文分析、配置翻译、知识检索。
- **Planner**：根据用户意图选择最小且足够的候选工具。
- **ToolRouter**：按 canonical tool id 定位 handler。
- **ToolRuntime**：执行 schema、权限、审批、路径、审计和脱敏策略。

## 工具来源

| 来源 | 文件 |
|------|------|
| Canonical registry | `tool_runtime/canonical_registry.py` |
| 名称空间与模型提示 | `tool_runtime/tool_namespace_data.py` |
| 能力动作映射 | `tool_runtime/capability_actions.py` |
| 分类路由 | `agent/runtime/tool_category_router.py` |
| 计划校验 | `agent/runtime/tool_planner.py` |

这些文件必须保持同一组工具 id。模型不可见、内部或禁止的工具不得进入 planner 候选集。

## 选择原则

1. 优先使用语义最具体的工具。
2. 文件读取、知识检索、报文分析、配置分析分别进入对应名称空间。
3. 多步骤任务先读取和分析，再执行写入或外部动作。
4. 工具参数必须来自用户输入、可信上下文或前一步真实结果。
5. 工具无结果时明确返回无结果，不伪造来源、文件、设备状态或执行结果。

## 知识工具

知识能力使用 `knowledge.search` 进行检索，并通过来源与 parent chunk 补充上下文。导入、来源管理、重建索引和分块读取均由 `agent/modules/knowledge/` 实现。

## 报文工具

报文工具覆盖 pcap 解析、连接筛选和 TCP 对齐。报文必须来自工作区文件或本次明确上传，不允许声称连接了远端设备。

## 验证

```bash
python3 -m pytest \
  harness/test_registry_contract.py \
  harness/test_tool_architecture.py \
  harness/test_tool_governance.py \
  harness/test_tool_runtime_integration_contract.py \
  harness/test_tool_intent_planner.py -q
```
