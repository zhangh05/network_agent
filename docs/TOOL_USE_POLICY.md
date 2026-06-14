# TOOL_USE_POLICY.md — v2.1.2 Tool-Use Intelligence

## 1. 概述

本文档定义 Network Agent 的全局工具使用策略，包括场景识别、工具路由、审批策略、失败回退和话术规范。

## 2. 核心原则

### 2.1 Host vs Device Boundary

**本机 OS（Host Introspection）≠ 网络设备（Network Device）**

- `shell.exec` / `powershell.exec` 运行在**本地主机**——即运行 Agent 的机器。
- 这些工具**不是**远程设备连接工具。
- 只应在用户要求连接**真实网络设备**且没有 `device connector` 时，才说"没有真实设备访问能力"。

**禁止泛化**：
- ❌ 用户问"本机 IP" → "没有真实设备访问能力"
- ✅ 用户问"本机 IP" → 使用 `shell.exec` 执行只读命令，请求审批
- ❌ 用户上传配置文件 → "无法访问设备"
- ✅ 用户上传配置文件 → 使用 `file.read` + `parser.extract_interfaces`

### 2.2 Tool-First Mindset

- 能用工具解决的问题，优先调用工具。
- 不能调用工具时，说明**缺失哪类能力**，而不是泛泛说"我不能"。
- 用户已明确意图后，不重复确认同一信息。
- 工具选择基于场景，不是基于关键词盲选。

### 2.3 Approval Strategy

高风险工具（见第 5 节）需要审批。审批话术统一：

**只读命令**:
```
可以执行。该命令只读不修改系统，按策略需要批准。
将执行 {command}。请回复"批准执行"。
```

**写操作**:
```
可以使用 {tool_id} 写入 workspace artifact。
影响范围仅限当前 workspace，不会访问真实网络设备。
请回复"批准执行"。
```

**删除操作**:
```
这是删除操作，需要明确批准。
将删除/软删除 {target}，影响范围 {scope}。
请回复"批准删除"。
```

**原则**: 生成一次明确审批请求即可，不要反复追问系统类型。

### 2.4 Failure → Fallback

每个工具失败后给出具体替代路径：
- `web.search` 失败 → 尝试 `web.official_doc_search`，或让用户提供 URL
- `file.read` 失败 → 用 `file.list` 确认路径，或 `artifact.search`
- `knowledge.search` 失败 → 尝试 `artifact.search`, `web.search`，或让用户上传
- `shell.exec` 未批准 → 说明待批准命令，提供手动执行命令
- `parser` 失败 → 让用户贴原始配置，尝试 `text.extract_keywords`

## 3. 场景分类与路由策略

### A. 本机 OS / Host Introspection
**触发词**: 本机, 本机 OS, 当前机器, 当前电脑, localhost, 本地 IP, 本机网卡, 本机 DNS, 当前监听端口, 进程, 端口, 服务是否启动

**推荐工具**: `runtime.health`, `runtime.diagnostics`, `shell.exec`, `powershell.exec`
**策略**: 直接使用工具查询。如果命令需审批，直接请求审批。不回答"没有真实设备访问能力"。

### B. 网络设备配置分析
**触发词**: 交换机, 路由器, 防火墙, Cisco, H3C, 华三, 华为, interface, vlan, ospf, bgp, display, show

**推荐工具**: `parser.extract_interfaces`, `parser.extract_routes`, `parser.parse_config_text`, `text.classify`, `knowledge.search`
**策略**: 如果没有设备连接工具，不能直接登录设备。但如果用户提供配置/日志，优先解析离线材料。

### C. 已上传文件/配置/日志
**触发词**: 看这个文件, 日志, 配置文件, pcap, 抓包, PDF, Excel, 上传

**推荐工具**: `file.read`, `file.list`, `pdf.extract_text`, `parser.*`, `artifact.search`
**策略**: 材料已经给了，直接分析。不要重复说"无法访问设备"。

### D. Web/官方文档查询
**触发词**: 官方文档, 配置手册, 查一下, GitHub, 最新, 产品文档

**推荐工具**: `web.official_doc_search`(厂商文档), `web.search`(通用), `web.fetch_summary`(URL)
**策略**: 厂商/技术文档优先用 `web.official_doc_search`。引用来源，区分为官方/社区。

### E. 知识/记忆查询
**触发词**: 我之前说过, 项目文档, 知识库, 历史记录

**推荐工具**: `knowledge.search`, `memory.search`, `artifact.search`
**策略**: 优先 RAG 检索。查不到时明确说明。

### F. 报告/制品生成
**触发词**: 生成报告, 保存结果, 导出, 制品

**推荐工具**: `report.render_markdown`, `artifact.save_result`, `table.render_markdown`, `diagram.render_mermaid`
**策略**: 分析结果保存为 artifact。用户要求保存时调用保存工具。

### G. 运行历史/Trace
**触发词**: 刚才那次, 运行详情, trace, 报错在哪

**推荐工具**: `run.list_recent`, `run.get_summary`, `session.list`, `runtime.diagnostics`
**策略**: 查运行记录、工具调用链、失败原因。

### H. 记忆操作
**触发词**: 记住, 以后都这样, 这是我的偏好

**推荐工具**: `memory.create`, `memory.confirm`, `memory.set_profile`
**策略**: 明确要求记住时才创建。不存储密码、token。

### I. 文本/数据处理
**触发词**: 校验 JSON, 校验 YAML, 提取关键词, 做表格, 画拓扑

**推荐工具**: `json.validate`, `yaml.validate`, `text.extract_keywords`, `table.render_markdown`, `diagram.render_mermaid`
**策略**: 结构化处理用专用工具。

## 4. ToolSpec Description 规范

每个工具描述必须包含：
1. **适用场景** (Use when:)
2. **不适用场景** (NOT for:)
3. **是否只读** (Read-only / Write)
4. **风险等级** (risk_level)
5. **是否需要审批** (requires_approval)
6. **常见输入** (parameters)
7. **返回值用途** (Returns:)
8. **与相邻工具的区别** (vs:)

示例：
```
tool_id: web.search
description: "Search public web pages for current or external information.
  Use when: user asks to look up public info, docs, vendor examples.
  NOT for: local workspace files, uploaded configs (use file.read).
  Read-only. Medium risk (network call, results may vary).
  Returns ranked results with title/URL/snippet/source-quality."
```

## 5. 高风险工具清单

| tool_id | 风险 | 权限 | 审批 | 说明 |
|---------|------|------|------|------|
| shell.exec | high | exec | Yes | 本地主机 bash 命令 |
| powershell.exec | high | exec | Yes | 本地主机 PowerShell |
| python.exec | high | exec | Yes | 沙箱 Python 执行 |
| file.edit | medium | write | No | 文件编辑 |
| file.patch | medium | write | No | 补丁应用 |
| artifact.delete_soft | medium | write | Yes(建议) | 制品软删除 |
| memory.delete_soft | medium | write | Yes(建议) | 记忆软删除 |

## 6. 禁止话术

以下话术仅在用户要求连接真实网络设备时才可使用：
- "没有真实设备访问能力" — 仅限远程设备连接请求
- "无法访问设备" — 仅限 SSH/Telnet/SNMP 场景

以下场景**禁止**使用这些话术：
- 本机 OS 查询 → 替换为"可以通过本机命令查询，但需要审批"
- 已上传文件分析 → 替换为"可以分析你提供的配置/日志"
- 知识库查询 → 替换为"可以从 workspace/知识库中查"
- 离线材料分析 → 替换为"可以用离线材料推断，但不能直接登录设备验证"

## 7. 工具失败回退表

| 工具失败 | 回退路径 |
|----------|----------|
| web.search | web.official_doc_search / 用户提供 URL / 上传文档 |
| web.fetch_summary | 让用户提供页面内容 / 换搜索关键词 |
| file.read | file.list 确认路径 / artifact.search / 询问 filepath |
| file.list | workspace.list_files / 询问子目录 |
| knowledge.search | artifact.search / web.search / 用户上传 / knowledge.explain_not_found |
| memory.search | 换关键词 / 说无相关记忆 |
| shell.exec | 说明待批准命令 / 提供手动命令 |
| powershell.exec | 说明待批准脚本 / 提供手动命令 |
| python.exec | 发送代码让用户运行 |
| parser.* | 让用户贴原文 / text.extract_keywords |
| pdf.extract_text | 说明 PDF 限制 / 建议转换 |
| agent.spawn | 减少 max_turns / 拆分任务 |

## 8. 输出结构（网络工程）

网络工程问题默认输出格式：
```
1. 结论 (Conclusion)
2. 证据 (Evidence — tool outputs, citations)
3. 原因 (Root cause)
4. 下一步验证 (Next verification step)
5. 风险/注意事项 (Risks & notes)
```
