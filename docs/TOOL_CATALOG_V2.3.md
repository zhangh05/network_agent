# Network Agent Tool Catalog v2.3

> 单一口径来源：`tool_runtime/tool_namespace.py` + `tool_runtime/tool_governance.py` + `tool_runtime/capability_actions.py`。本目录由 `scripts/build_tool_catalog_v23.py` 生成；不手工拼接。

机器可读版本：`reports/tool_catalog_v23.json`。校验脚本：`scripts/verify_tool_catalog_doc.py`。

## 1. 口径说明

v2.3 工具命名是五层模型，本目录统一使用下列口径：

- **canonical_tool_id**：LLM / 前端 / planner 使用的正式工具名。 三级标题一律使用 canonical id。
- **execution_tool_id**：底层 handler 调用的稳定 ID，保留兼容与 trace 可读性，不作为新文档主标题。
- **legacy_aliases**：历史入口；不可作为新文档主口径，Planner 不会主动选它们。
- **capability_action**：planner 选择的高层能力动作；一个动作可以包含多个 preferred / fallback canonical tools。
- **governance_status**：治理状态，取值 `keep / alias / merged / deprecated / removed_candidate`。仅 `keep` 在 planner 默认候选里。

## 2. 总览统计

以下数字全部来自 runtime registry 与 governance 层，未在文档中估算。

- **execution_count**：88
- **canonical_count**：88
- **model_visible_count**：88
- **planner_visible_count**：84
- **legacy_alias_count**：90
- **capability_action_count**：95
- **category_count**：9

### 2.1 Governance Summary

| status | count | 说明 |
|---|---|---|
| keep | 84 | 稳定可见，是 planner 默认候选 |
| alias | 1 | 兼容别名，planner 重定向到 replacement |
| merged | 1 | 已合并，planner 重定向到 replacement |
| deprecated | 1 | 不再进入 planner，legacy 调用仍可执行 |
| removed_candidate | 1 | v2.4 起在文档中加 deprecate_after，下一 major 之前不会真删 |

## 3. 能力域目录

按 v2.3 category 分组。下表是 planner 默认可见的 `keep` 工具分布。

| 能力域 | 说明 | 典型场景 | 不适用场景 | groups | tools | planner 默认可见 |
|---|---|---|---|---|---|---|
| **Agent 多 Agent** (`agent`) | 技能、子 Agent、角色、团队和结果读取 | 子 Agent、技能、角色、团队任务编排 | agent.spawn 受 max_turns≤3 限制；skill.create 不自动启用未经审查技能 | 5 | 10 | 10 |
| **Host 本机环境** (`host`) | 当前运行机器上的本机 OS、Shell、PowerShell、Python 工具 | 本机 shell/powershell/python 执行、slash 命令、运行诊断 | 不用于网络设备 SSH/Telnet/SNMP/真实设备访问；不用于解析配置文本 | 4 | 4 | 4 |
| **Knowledge 知识库** (`knowledge`) | 知识库问答、检索、导入和索引管理 | 知识库检索、chunk/source 维护、导入文件/文档 | 不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体 | 6 | 12 | 12 |
| **Memory 记忆** (`memory`) | 记忆搜索、创建、确认、profile 和更新 | 用户偏好与历史记忆的搜索、写入、确认、profile | 不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认 | 2 | 8 | 8 |
| **Network 网络分析** (`network`) | 离线网络配置解析、接口/路由提取和配置翻译 | 解析/翻译/接口提取/路由提取等离线分析 | 不登录真实设备；不下发配置；translated_config 不等于 deployable_config | 3 | 4 | 4 |
| **Report/Data/Text 输出处理** (`report_data`) | 报告、表格、文本、JSON/YAML/CSV 和图表处理 | 报告/表格/图表/JSON/YAML/CSV/文本处理输出 | 不包含原始敏感配置作为最终输出；text.redact 用于脱敏；validate 不执行代码 | 8 | 13 | 12 |
| **Runtime 运行审计** (`runtime`) | 运行状态、session、run、review 和审计信息 | 运行健康/诊断、session/run/review 审计 | 不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物 | 4 | 13 | 13 |
| **Web 外部资料** (`web`) | 公开 Web、官方文档、新闻、天气和网页摘要 | 公开 Web 搜索、厂商官方文档、新闻、天气查询 | 不抓私网/本地/登录墙 URL；weather 仅在明确天气需求时使用 | 5 | 8 | 7 |
| **Workspace 工作区** (`workspace`) | 工作区文件、Artifact 制品和 workspace 元数据 | 工作区文件列表/读取/编辑、artifact 元数据、安全摘要读写 | 不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径 | 4 | 16 | 14 |

## 4. Capability Actions

Planner 在 v2.2.1 rule_scene 之上，再走 capability_action 计划，把动作展开成 preferred / fallback 工具集后再走 governance 过滤。

```text
用户请求
→ capability_action plan
→ canonical tools
→ governance filter (keep only)
→ candidate_tools
→ ToolRouter
→ execution_tool_id
```

| capability_action | category | group | preferred_tools | fallback_tools | 用途 |
|---|---|---|---|---|---|
| `agent.result.get` | agent | result | `agent.result.get` | — | Direct canonical action for a stable, non-overlapping tool. |
| `agent.role.list` | agent | role | `agent.role.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `agent.spawn` | agent | subagent | `agent.spawn` | — | Direct canonical action for a stable, non-overlapping tool. |
| `agent.team.coordinate` | agent | subagent | `agent.spawn`, `agent.role.list`, `agent.result.get` | `agent.team.run`, `skill.list`, `skill.request_load`, `skill.load`, `skill.find`, `skill.inspect`, `skill.create` | Coordinate skills and sub-agent work under runtime limits. |
| `agent.team.run` | agent | team | `agent.team.run` | — | Direct canonical action for a stable, non-overlapping tool. |
| `data.csv.summarize` | report_data | csv | `data.csv.summarize` | — | Direct canonical action for a stable, non-overlapping tool. |
| `data.json.validate` | report_data | json | `data.json.validate` | — | Direct canonical action for a stable, non-overlapping tool. |
| `data.table.extract` | report_data | table | `data.table.extract` | — | Direct canonical action for a stable, non-overlapping tool. |
| `data.table.render` | report_data | table | `data.table.render` | — | Direct canonical action for a stable, non-overlapping tool. |
| `data.text.process` | report_data | text | `text.redact`, `text.diff`, `text.keywords.extract` | `data.json.validate`, `data.yaml.validate`, `data.csv.summarize`, `data.table.extract`, `data.table.render` | Process structured data and safe text outputs. |
| `data.yaml.validate` | report_data | yaml | `data.yaml.validate` | — | Direct canonical action for a stable, non-overlapping tool. |
| `diagram.mermaid.render` | report_data | diagram | `diagram.mermaid.render` | — | Direct canonical action for a stable, non-overlapping tool. |
| `document.safe_summary.render` | report_data | document | `document.safe_summary.render` | — | Direct canonical action for a stable, non-overlapping tool. |
| `host.command.slash_run` | host | command | `host.command.slash_run` | — | Direct canonical action for a stable, non-overlapping tool. |
| `host.environment.inspect` | host | shell | `host.shell.exec`, `host.powershell.exec`, `host.python.exec`, `runtime.health`, `runtime.diagnostics` | — | Inspect or operate on the current local host under approval policy. |
| `host.powershell.exec` | host | powershell | `host.powershell.exec` | — | Direct canonical action for a stable, non-overlapping tool. |
| `host.python.exec` | host | python | `host.python.exec` | — | Direct canonical action for a stable, non-overlapping tool. |
| `host.shell.exec` | host | shell | `host.shell.exec` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.chunk.list` | knowledge | chunk | `knowledge.chunk.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.chunk.read` | knowledge | chunk | `knowledge.chunk.read` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.import.document` | knowledge | import | `knowledge.import.document` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.import.file` | knowledge | import | `knowledge.import.file` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.parent.read` | knowledge | parent | `knowledge.parent.read` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.query` | knowledge | query | `knowledge.query` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.search` | knowledge | search | `knowledge.search` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.search_and_answer` | knowledge | search | `knowledge.query`, `knowledge.search` | `knowledge.chunk.read`, `knowledge.source.read`, `knowledge.parent.read` | Search the knowledge base and answer from safe excerpts. |
| `knowledge.source.delete` | knowledge | source | `knowledge.source.delete` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.source.disable` | knowledge | source | `knowledge.source.disable` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.source.list` | knowledge | source | `knowledge.source.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.source.read` | knowledge | source | `knowledge.source.read` | — | Direct canonical action for a stable, non-overlapping tool. |
| `knowledge.source.reindex` | knowledge | source | `knowledge.source.reindex` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.confirm` | memory | record | `memory.confirm` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.create` | memory | record | `memory.create` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.delete_soft` | memory | record | `memory.delete_soft` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.list` | memory | record | `memory.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.profile.get` | memory | profile | `memory.profile.get` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.profile.manage` | memory | profile | `memory.search`, `memory.list`, `memory.profile.get`, `memory.profile.set` | `memory.create`, `memory.confirm`, `memory.update`, `memory.delete_soft` | Search and manage memory records and profile fields. |
| `memory.profile.set` | memory | profile | `memory.profile.set` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.search` | memory | record | `memory.search` | — | Direct canonical action for a stable, non-overlapping tool. |
| `memory.update` | memory | record | `memory.update` | — | Direct canonical action for a stable, non-overlapping tool. |
| `network.config.analyze` | network | config | `network.config.parse`, `network.interface.extract`, `network.route.extract` | — | Offline network configuration analysis. |
| `network.config.parse` | network | config | `network.config.parse` | — | Direct canonical action for a stable, non-overlapping tool. |
| `network.config.translate` | network | config | `network.config.translate` | — | Offline network configuration translation. |
| `network.interface.extract` | network | interface | `network.interface.extract` | — | Direct canonical action for a stable, non-overlapping tool. |
| `network.route.extract` | network | route | `network.route.extract` | — | Direct canonical action for a stable, non-overlapping tool. |
| `report.artifact.save` | report_data | report | `report.artifact.save` | — | Direct canonical action for a stable, non-overlapping tool. |
| `report.create_and_save` | report_data | report | `report.markdown.render`, `workspace.artifact.save` | `data.table.render`, `diagram.mermaid.render` | Render a report and save it as a workspace artifact. |
| `report.markdown.render` | report_data | report | `report.markdown.render` | — | Direct canonical action for a stable, non-overlapping tool. |
| `review.item.list` | runtime | review | `review.item.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `review.item.update` | runtime | review | `review.item.update` | — | Direct canonical action for a stable, non-overlapping tool. |
| `run.list` | runtime | run | `run.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `run.summary.get` | runtime | run | `run.summary.get` | — | Direct canonical action for a stable, non-overlapping tool. |
| `runtime.audit.inspect` | runtime | run | `runtime.health`, `runtime.diagnostics`, `run.list`, `run.summary.get`, `session.list`, `session.summary.get` | `session.snapshot.list`, `session.export` | Inspect runtime, run, and session audit metadata. |
| `runtime.diagnostics` | runtime | health | `runtime.diagnostics` | — | Direct canonical action for a stable, non-overlapping tool. |
| `runtime.health` | runtime | health | `runtime.health` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.checkpoint` | runtime | session | `session.checkpoint` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.export` | runtime | session | `session.export` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.list` | runtime | session | `session.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.rewind` | runtime | session | `session.rewind` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.snapshot.create` | runtime | session | `session.snapshot.create` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.snapshot.list` | runtime | session | `session.snapshot.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `session.summary.get` | runtime | session | `session.summary.get` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.create` | agent | skill | `skill.create` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.find` | agent | skill | `skill.find` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.inspect` | agent | skill | `skill.inspect` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.list` | agent | skill | `skill.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.load` | agent | skill | `skill.load` | — | Direct canonical action for a stable, non-overlapping tool. |
| `skill.request_load` | agent | skill | `skill.request_load` | — | Direct canonical action for a stable, non-overlapping tool. |
| `text.diff` | report_data | text | `text.diff` | — | Direct canonical action for a stable, non-overlapping tool. |
| `text.keywords.extract` | report_data | text | `text.keywords.extract` | — | Direct canonical action for a stable, non-overlapping tool. |
| `text.redact` | report_data | text | `text.redact` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.docs.official_search` | web | docs | `web.docs.official_search` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.official_docs.search` | web | docs | `web.docs.official_search`, `web.search`, `web.page.summarize` | `web.page.extract_links` | Search official documentation and summarize public pages. |
| `web.page.extract_links` | web | page | `web.page.extract_links` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.page.save_artifact` | web | page | `web.page.save_artifact` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.page.summarize` | web | page | `web.page.summarize` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.search` | web | search | `web.search` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.weather.current` | web | weather | `web.weather.current` | — | Direct canonical action for a stable, non-overlapping tool. |
| `web.weather.forecast` | web | weather | `web.weather.forecast` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.artifact.diff` | workspace | artifact | `workspace.artifact.diff` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.artifact.export` | workspace | artifact | `workspace.artifact.export` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.artifact.list` | workspace | artifact | `workspace.artifact.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.artifact.manage` | workspace | artifact | `workspace.artifact.list`, `workspace.artifact.search`, `workspace.artifact.read`, `workspace.artifact.save` | `workspace.artifact.diff`, `workspace.artifact.export`, `workspace.artifact.tag`, `workspace.artifact.delete_soft` | Work with workspace artifact metadata and safe content. |
| `workspace.artifact.read` | workspace | artifact | `workspace.artifact.read` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.artifact.save` | workspace | artifact | `workspace.artifact.save` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.document.pdf.extract_text` | workspace | document | `workspace.document.pdf.extract_text` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.edit` | workspace | file | `workspace.file.edit` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.exists` | workspace | file | `workspace.file.exists` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.list` | workspace | file | `workspace.file.list` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.manage` | workspace | file | `workspace.file.list`, `workspace.file.exists`, `workspace.file.edit`, `workspace.file.patch` | — | List, check, edit, or patch workspace files. |
| `workspace.file.patch` | workspace | file | `workspace.file.patch` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.preview` | workspace | file | `workspace.file.preview` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.file.read` | workspace | file | `workspace.file.read`, `workspace.file.preview` | `workspace.file.list` | Read or preview workspace files before analysis. |
| `workspace.file.write_artifact` | workspace | file | `workspace.file.write_artifact` | — | Direct canonical action for a stable, non-overlapping tool. |
| `workspace.metadata.get` | workspace | metadata | `workspace.metadata.get` | — | Direct canonical action for a stable, non-overlapping tool. |

## 5. 完整工具清单

本节按能力域排序，每个 canonical tool 一节，格式严格统一：**canonical id 为三级标题**，execution / legacy 为兼容字段。

### 5.1. Agent 多 Agent (`agent`)

**说明**：技能、子 Agent、角色、团队和结果读取

**典型场景**：子 Agent、技能、角色、团队任务编排

**不适用场景**：agent.spawn 受 max_turns≤3 限制；skill.create 不自动启用未经审查技能

**包含 groups**：`result, role, skill, subagent, team`

**canonical tools 数**：10

### `agent.result.get`

- **display_name**: 获取子 Agent 结果
- **execution_tool_id**: `agent.get_result`
- **legacy_aliases**: `agent.get_result`
- **category / group / action**: agent / result / get
- **capability_actions**: `agent.result.get`, `agent.team.coordinate`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取已完成子 Agent 的安全结果摘要
- **边界**: 不要用于启动新 Agent

### `agent.role.list`

- **display_name**: 列出 Agent 角色
- **execution_tool_id**: `agent.list_roles`
- **legacy_aliases**: `agent.list_roles`
- **category / group / action**: agent / role / list
- **capability_actions**: `agent.role.list`, `agent.team.coordinate`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 查看 planner/worker/reviewer 等可用角色
- **边界**: 不要用于运行团队任务

### `agent.spawn`

- **display_name**: 启动子 Agent
- **execution_tool_id**: `agent.spawn`
- **legacy_aliases**: `agent.spawn`
- **category / group / action**: agent / subagent / spawn
- **capability_actions**: `agent.spawn`, `agent.team.coordinate`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 把受限任务交给子 Agent 执行
- **边界**: 不要递归启动子 Agent

### `agent.team.run`

- **display_name**: 运行 Agent 团队预览
- **execution_tool_id**: `agent.team`
- **legacy_aliases**: `agent.team`
- **category / group / action**: agent / team / run
- **capability_actions**: `agent.team.coordinate`, `agent.team.run`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 预览多 Agent 协作流程
- **边界**: 不要当作生产自动化

### `skill.create`

- **display_name**: 创建技能
- **execution_tool_id**: `skill.create`
- **legacy_aliases**: `skill.create`
- **category / group / action**: agent / skill / create
- **capability_actions**: `agent.team.coordinate`, `skill.create`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 创建本地 agent skill 草案
- **边界**: 不要自动启用未经审查技能

### `skill.find`

- **display_name**: 查找技能
- **execution_tool_id**: `skill.find_skills`
- **legacy_aliases**: `skill.find_skills`
- **category / group / action**: agent / skill / find
- **capability_actions**: `agent.team.coordinate`, `skill.find`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 查找可用技能
- **边界**: 不要加载技能

### `skill.inspect`

- **display_name**: 检查技能
- **execution_tool_id**: `skill.inspect`
- **legacy_aliases**: `skill.inspect`
- **category / group / action**: agent / skill / inspect
- **capability_actions**: `agent.team.coordinate`, `skill.inspect`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 查看技能详情
- **边界**: 不要执行技能

### `skill.list`

- **display_name**: 列出技能
- **execution_tool_id**: `skill.list`
- **legacy_aliases**: `skill.list`
- **category / group / action**: agent / skill / list
- **capability_actions**: `agent.team.coordinate`, `skill.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出已注册技能
- **边界**: 不要加载技能

### `skill.load`

- **display_name**: 加载技能
- **execution_tool_id**: `skill.load`
- **legacy_aliases**: `skill.load`
- **category / group / action**: agent / skill / load
- **capability_actions**: `agent.team.coordinate`, `skill.load`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 加载指定技能提示
- **边界**: 不要加载未知来源技能

### `skill.request_load`

- **display_name**: 请求加载技能
- **execution_tool_id**: `skill.request_load`
- **legacy_aliases**: `skill.request_load`
- **category / group / action**: agent / skill / request_load
- **capability_actions**: `agent.team.coordinate`, `skill.request_load`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 创建技能加载请求
- **边界**: 不要绕过用户确认

### 5.2. Host 本机环境 (`host`)

**说明**：当前运行机器上的本机 OS、Shell、PowerShell、Python 工具

**典型场景**：本机 shell/powershell/python 执行、slash 命令、运行诊断

**不适用场景**：不用于网络设备 SSH/Telnet/SNMP/真实设备访问；不用于解析配置文本

**包含 groups**：`command, powershell, python, shell`

**canonical tools 数**：4

### `host.command.slash_run`

- **display_name**: 运行 Slash 命令
- **execution_tool_id**: `slash.run`
- **legacy_aliases**: `slash.run`
- **category / group / action**: host / command / slash_run
- **capability_actions**: `host.command.slash_run`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 执行内置 slash 命令
- **边界**: 不要执行任意 shell

### `host.powershell.exec`

- **display_name**: 执行本机 PowerShell
- **execution_tool_id**: `powershell.exec`
- **legacy_aliases**: `powershell.exec`
- **category / group / action**: host / powershell / exec
- **capability_actions**: `host.environment.inspect`, `host.powershell.exec`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **用途**: 在本机执行已审批 PowerShell 脚本
- **边界**: 不用于网络设备 SSH/Telnet/SNMP

### `host.python.exec`

- **display_name**: 执行本机 Python
- **execution_tool_id**: `python.exec`
- **legacy_aliases**: `python.exec`
- **category / group / action**: host / python / exec
- **capability_actions**: `host.environment.inspect`, `host.python.exec`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **用途**: 在本机执行已审批 Python 脚本
- **边界**: 不用于网络设备或无审批执行

### `host.shell.exec`

- **display_name**: 执行本机 Shell
- **execution_tool_id**: `shell.exec`
- **legacy_aliases**: `shell.exec`
- **category / group / action**: host / shell / exec
- **capability_actions**: `host.environment.inspect`, `host.shell.exec`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **用途**: 在本机执行已审批 Shell 命令
- **边界**: 不用于网络设备 SSH/Telnet/SNMP

### 5.3. Knowledge 知识库 (`knowledge`)

**说明**：知识库问答、检索、导入和索引管理

**典型场景**：知识库检索、chunk/source 维护、导入文件/文档

**不适用场景**：不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体

**包含 groups**：`chunk, import, parent, query, search, source`

**canonical tools 数**：12

### `knowledge.chunk.list`

- **display_name**: 列出知识块
- **execution_tool_id**: `knowledge.list_chunks`
- **legacy_aliases**: `knowledge.list_chunks`
- **category / group / action**: knowledge / chunk / list
- **capability_actions**: `knowledge.chunk.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出某知识源的 chunks
- **边界**: 不要返回全文

### `knowledge.chunk.read`

- **display_name**: 读取知识块
- **execution_tool_id**: `knowledge.read_chunk`
- **legacy_aliases**: `knowledge.read_chunk`
- **category / group / action**: knowledge / chunk / read
- **capability_actions**: `knowledge.chunk.read`, `knowledge.search_and_answer`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取安全 chunk 摘要
- **边界**: 不要返回未经脱敏全文

### `knowledge.import.document`

- **display_name**: 导入文档
- **execution_tool_id**: `knowledge.import_document`
- **legacy_aliases**: `knowledge.import_document`
- **category / group / action**: knowledge / import / document
- **capability_actions**: `knowledge.import.document`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 导入文档内容到知识库
- **边界**: 不要导入未授权敏感文件

### `knowledge.import.file`

- **display_name**: 导入文件
- **execution_tool_id**: `knowledge.import_file`
- **legacy_aliases**: `knowledge.import_file`
- **category / group / action**: knowledge / import / file
- **capability_actions**: `knowledge.import.file`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 导入 workspace 文件到知识库
- **边界**: 不要导入工作区外文件

### `knowledge.parent.read`

- **display_name**: 读取父文档摘要
- **execution_tool_id**: `knowledge.read_parent`
- **legacy_aliases**: `knowledge.read_parent`
- **category / group / action**: knowledge / parent / read
- **capability_actions**: `knowledge.parent.read`, `knowledge.search_and_answer`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 chunk 所属父文档安全摘要
- **边界**: 不要泄露绝对路径

### `knowledge.query`

- **display_name**: 知识库问答
- **execution_tool_id**: `knowledge.query`
- **legacy_aliases**: `knowledge.query`
- **category / group / action**: knowledge / query / answer
- **capability_actions**: `knowledge.query`, `knowledge.search_and_answer`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 基于知识库安全摘录回答问题
- **边界**: 不要凭空引用未检索内容

### `knowledge.search`

- **display_name**: 搜索知识块
- **execution_tool_id**: `knowledge.search_chunks`
- **legacy_aliases**: `knowledge.search_chunks`
- **category / group / action**: knowledge / search / chunks
- **capability_actions**: `knowledge.search`, `knowledge.search_and_answer`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 搜索知识库安全 chunks
- **边界**: 不要作为 Web 搜索替代

### `knowledge.source.delete`

- **display_name**: 删除知识源
- **execution_tool_id**: `knowledge.delete_source`
- **legacy_aliases**: `knowledge.delete_source`
- **category / group / action**: knowledge / source / delete
- **capability_actions**: `knowledge.source.delete`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 删除 workspace 知识源记录
- **边界**: 不要删除 artifact 本体

### `knowledge.source.disable`

- **display_name**: 停用知识源
- **execution_tool_id**: `knowledge.disable_source`
- **legacy_aliases**: `knowledge.disable_source`
- **category / group / action**: knowledge / source / disable
- **capability_actions**: `knowledge.source.disable`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 停用知识源参与检索
- **边界**: 不要删除源内容

### `knowledge.source.list`

- **display_name**: 列出知识源
- **execution_tool_id**: `knowledge.list_sources`
- **legacy_aliases**: `knowledge.list_sources`
- **category / group / action**: knowledge / source / list
- **capability_actions**: `knowledge.source.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出知识库 sources
- **边界**: 不要读取完整源内容

### `knowledge.source.read`

- **display_name**: 读取知识源
- **execution_tool_id**: `knowledge.read_source`
- **legacy_aliases**: `knowledge.read_source`
- **category / group / action**: knowledge / source / read
- **capability_actions**: `knowledge.search_and_answer`, `knowledge.source.read`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取知识源安全元数据
- **边界**: 不要读取 secret 原文

### `knowledge.source.reindex`

- **display_name**: 重建知识源索引
- **execution_tool_id**: `knowledge.reindex_source`
- **legacy_aliases**: `knowledge.reindex_source`
- **category / group / action**: knowledge / source / reindex
- **capability_actions**: `knowledge.source.reindex`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 重建单个知识源索引
- **边界**: 不要批量重建全部源

### 5.4. Memory 记忆 (`memory`)

**说明**：记忆搜索、创建、确认、profile 和更新

**典型场景**：用户偏好与历史记忆的搜索、写入、确认、profile

**不适用场景**：不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认

**包含 groups**：`profile, record`

**canonical tools 数**：8

### `memory.confirm`

- **display_name**: 确认记忆
- **execution_tool_id**: `memory.confirm`
- **legacy_aliases**: `memory.confirm`
- **category / group / action**: memory / record / confirm
- **capability_actions**: `memory.confirm`, `memory.profile.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 确认并写入重要记忆
- **边界**: 不要自动写入未经确认偏好

### `memory.create`

- **display_name**: 创建记忆
- **execution_tool_id**: `memory.create`
- **legacy_aliases**: `memory.create`
- **category / group / action**: memory / record / create
- **capability_actions**: `memory.create`, `memory.profile.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 创建短期/长期记忆记录
- **边界**: 不要保存 secret

### `memory.delete_soft`

- **display_name**: 软删除记忆
- **execution_tool_id**: `memory.delete_soft`
- **legacy_aliases**: `memory.delete_soft`
- **category / group / action**: memory / record / delete_soft
- **capability_actions**: `memory.delete_soft`, `memory.profile.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 软删除记忆记录
- **边界**: 不要物理删除数据

### `memory.list`

- **display_name**: 列出记忆
- **execution_tool_id**: `memory.list`
- **legacy_aliases**: `memory.list`
- **category / group / action**: memory / record / list
- **capability_actions**: `memory.list`, `memory.profile.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出记忆记录摘要
- **边界**: 不要返回敏感全文

### `memory.profile.get`

- **display_name**: 读取记忆 Profile
- **execution_tool_id**: `memory.get_profile`
- **legacy_aliases**: `memory.get_profile`
- **category / group / action**: memory / profile / get
- **capability_actions**: `memory.profile.get`, `memory.profile.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取用户偏好档案
- **边界**: 不要读取 secret

### `memory.profile.set`

- **display_name**: 更新记忆 Profile
- **execution_tool_id**: `memory.set_profile`
- **legacy_aliases**: `memory.set_profile`
- **category / group / action**: memory / profile / set
- **capability_actions**: `memory.profile.manage`, `memory.profile.set`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 更新用户偏好档案
- **边界**: 不要写入 secret

### `memory.search`

- **display_name**: 搜索记忆
- **execution_tool_id**: `memory.search`
- **legacy_aliases**: `memory.search`
- **category / group / action**: memory / record / search
- **capability_actions**: `memory.profile.manage`, `memory.search`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 搜索记忆摘要
- **边界**: 不要替代知识库检索

### `memory.update`

- **display_name**: 更新记忆
- **execution_tool_id**: `memory.update`
- **legacy_aliases**: `memory.update`
- **category / group / action**: memory / record / update
- **capability_actions**: `memory.profile.manage`, `memory.update`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 更新既有记忆记录
- **边界**: 不要绕过确认策略

### 5.5. Network 网络分析 (`network`)

**说明**：离线网络配置解析、接口/路由提取和配置翻译

**典型场景**：解析/翻译/接口提取/路由提取等离线分析

**不适用场景**：不登录真实设备；不下发配置；translated_config 不等于 deployable_config

**包含 groups**：`config, interface, route`

**canonical tools 数**：4

### `network.config.parse`

- **display_name**: 解析网络配置
- **execution_tool_id**: `parser.parse_config_text`
- **legacy_aliases**: `parser.parse_config_text`
- **category / group / action**: network / config / parse
- **capability_actions**: `network.config.analyze`, `network.config.parse`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 离线解析网络配置文本
- **边界**: 不要执行配置

### `network.config.translate`

- **display_name**: 翻译网络配置
- **execution_tool_id**: `config_translation.translate_config`
- **legacy_aliases**: `config_translation.translate_config`
- **category / group / action**: network / config / translate
- **capability_actions**: `network.config.translate`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 离线翻译网络设备配置并产出复核项
- **边界**: 不要登录真实设备或下发配置

### `network.interface.extract`

- **display_name**: 提取接口
- **execution_tool_id**: `parser.extract_interfaces`
- **legacy_aliases**: `parser.extract_interfaces`
- **category / group / action**: network / interface / extract
- **capability_actions**: `network.config.analyze`, `network.interface.extract`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 离线提取配置中的接口信息
- **边界**: 不要登录设备

### `network.route.extract`

- **display_name**: 提取路由
- **execution_tool_id**: `parser.extract_routes`
- **legacy_aliases**: `parser.extract_routes`
- **category / group / action**: network / route / extract
- **capability_actions**: `network.config.analyze`, `network.route.extract`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 离线提取配置中的路由信息
- **边界**: 不要登录设备

### 5.6. Report/Data/Text 输出处理 (`report_data`)

**说明**：报告、表格、文本、JSON/YAML/CSV 和图表处理

**典型场景**：报告/表格/图表/JSON/YAML/CSV/文本处理输出

**不适用场景**：不包含原始敏感配置作为最终输出；text.redact 用于脱敏；validate 不执行代码

**包含 groups**：`csv, diagram, document, json, report, table, text, yaml`

**canonical tools 数**：13

### `data.csv.summarize`

- **display_name**: 汇总 CSV
- **execution_tool_id**: `csv.summarize`
- **legacy_aliases**: `csv.summarize`
- **category / group / action**: report_data / csv / summarize
- **capability_actions**: `data.csv.summarize`, `data.text.process`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 汇总 CSV/表格文本的安全统计
- **边界**: 不要处理超大原始文件

### `data.json.validate`

- **display_name**: 校验 JSON
- **execution_tool_id**: `json.validate`
- **legacy_aliases**: `json.validate`
- **category / group / action**: report_data / json / validate
- **capability_actions**: `data.json.validate`, `data.text.process`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 校验 JSON 文本结构
- **边界**: 不要执行 JSON 中的代码

### `data.table.extract`

- **display_name**: 提取表格
- **execution_tool_id**: `table.extract`
- **legacy_aliases**: `table.extract`
- **category / group / action**: report_data / table / extract
- **capability_actions**: `data.table.extract`, `data.text.process`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 从文本提取表格数据
- **边界**: 不要解析 secret 原文

### `data.table.render`

- **display_name**: 渲染 Markdown 表格
- **execution_tool_id**: `table.render_markdown`
- **legacy_aliases**: `table.render_markdown`
- **category / group / action**: report_data / table / render
- **capability_actions**: `data.table.render`, `data.text.process`, `report.create_and_save`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 把结构化数据渲染为 Markdown 表格
- **边界**: 不要包含敏感字段

### `data.yaml.validate`

- **display_name**: 校验 YAML
- **execution_tool_id**: `yaml.validate`
- **legacy_aliases**: `yaml.validate`
- **category / group / action**: report_data / yaml / validate
- **capability_actions**: `data.text.process`, `data.yaml.validate`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 校验 YAML 文本结构
- **边界**: 不要执行 YAML 内容

### `diagram.mermaid.render`

- **display_name**: 渲染 Mermaid 图
- **execution_tool_id**: `diagram.render_mermaid`
- **legacy_aliases**: `diagram.render_mermaid`
- **category / group / action**: report_data / diagram / render
- **capability_actions**: `diagram.mermaid.render`, `report.create_and_save`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 生成 Mermaid 图表文本
- **边界**: 不要渲染不可信脚本

### `document.safe_summary.render`

- **display_name**: 渲染安全摘要文档
- **execution_tool_id**: `doc.render_from_safe_summary`
- **legacy_aliases**: `doc.render_from_safe_summary`
- **category / group / action**: report_data / document / render
- **capability_actions**: `document.safe_summary.render`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 从安全摘要生成文档片段
- **边界**: 不要包含原始敏感配置

### `report.artifact.save`

- **display_name**: 保存报告制品
- **execution_tool_id**: `report.save_artifact`
- **legacy_aliases**: `report.save_artifact`
- **category / group / action**: report_data / report / save_artifact
- **capability_actions**: `report.artifact.save`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 把报告保存为 workspace artifact
- **边界**: 不要保存敏感全文

### `report.markdown.render`

- **display_name**: 渲染 Markdown 报告
- **execution_tool_id**: `report.render_markdown`
- **legacy_aliases**: `report.render_markdown`
- **category / group / action**: report_data / report / render_markdown
- **capability_actions**: `report.create_and_save`, `report.markdown.render`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 从安全结果渲染 Markdown 报告
- **边界**: 不要包含原始 secret

### `text.classify`

- **display_name**: 文本分类
- **execution_tool_id**: `text.classify`
- **legacy_aliases**: `text.classify`
- **category / group / action**: report_data / text / classify
- **capability_actions**: none  
  reason: internal/helper/manual-only
- **governance_status**: `removed_candidate`
- **replacement**: `—`  
  **migration_notes**: Keep in v2.3; require a deprecation release before any real removal.
- **planner_visible**: false
- **risk_level**: low
- **requires_approval**: false
- **用途**: 对短文本做本地规则分类
- **边界**: 不要当作安全审计结论

### `text.diff`

- **display_name**: 文本差异
- **execution_tool_id**: `text.diff`
- **legacy_aliases**: `text.diff`
- **category / group / action**: report_data / text / diff
- **capability_actions**: `data.text.process`, `text.diff`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 比较两段文本差异
- **边界**: 不要处理超大配置全文

### `text.keywords.extract`

- **display_name**: 提取关键词
- **execution_tool_id**: `text.extract_keywords`
- **legacy_aliases**: `text.extract_keywords`
- **category / group / action**: report_data / text / keywords_extract
- **capability_actions**: `data.text.process`, `text.keywords.extract`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 提取文本关键词
- **边界**: 不要当作知识库搜索

### `text.redact`

- **display_name**: 文本脱敏
- **execution_tool_id**: `text.redact`
- **legacy_aliases**: `text.redact`
- **category / group / action**: report_data / text / redact
- **capability_actions**: `data.text.process`, `text.redact`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 对文本进行安全脱敏
- **边界**: 不要保证强隔离沙箱

### 5.7. Runtime 运行审计 (`runtime`)

**说明**：运行状态、session、run、review 和审计信息

**典型场景**：运行健康/诊断、session/run/review 审计

**不适用场景**：不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物

**包含 groups**：`health, review, run, session`

**canonical tools 数**：13

### `review.item.list`

- **display_name**: 列出复核项
- **execution_tool_id**: `review.list_items`
- **legacy_aliases**: `review.list_items`
- **category / group / action**: runtime / review / list
- **capability_actions**: `review.item.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出人工复核项
- **边界**: 不要自动关闭复核

### `review.item.update`

- **display_name**: 更新复核项
- **execution_tool_id**: `review.update_item`
- **legacy_aliases**: `review.update_item`
- **category / group / action**: runtime / review / update
- **capability_actions**: `review.item.update`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 更新人工复核项状态
- **边界**: 不要绕过用户决定

### `run.list`

- **display_name**: 列出最近运行
- **execution_tool_id**: `run.list_recent`
- **legacy_aliases**: `run.list_recent`
- **category / group / action**: runtime / run / list
- **capability_actions**: `run.list`, `runtime.audit.inspect`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出最近 runs
- **边界**: 不要跨 workspace 泄露

### `run.summary.get`

- **display_name**: 获取运行摘要
- **execution_tool_id**: `run.get_summary`
- **legacy_aliases**: `run.get_summary`
- **category / group / action**: runtime / run / summary_get
- **capability_actions**: `run.summary.get`, `runtime.audit.inspect`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 run 安全摘要
- **边界**: 不要读取 trace 全量

### `runtime.diagnostics`

- **display_name**: 运行诊断
- **execution_tool_id**: `runtime.diagnostics`
- **legacy_aliases**: `runtime.diagnostics`
- **category / group / action**: runtime / health / diagnostics
- **capability_actions**: `host.environment.inspect`, `runtime.audit.inspect`, `runtime.diagnostics`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 runtime 诊断
- **边界**: 不要修改状态

### `runtime.health`

- **display_name**: 运行健康
- **execution_tool_id**: `runtime.health`
- **legacy_aliases**: `runtime.health`
- **category / group / action**: runtime / health / get
- **capability_actions**: `host.environment.inspect`, `runtime.audit.inspect`, `runtime.health`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 runtime 健康状态
- **边界**: 不要执行修复

### `session.checkpoint`

- **display_name**: 创建会话检查点
- **execution_tool_id**: `session.checkpoint`
- **legacy_aliases**: `session.checkpoint`
- **category / group / action**: runtime / session / checkpoint
- **capability_actions**: `session.checkpoint`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 创建当前 session 检查点
- **边界**: 不要当作完整备份

### `session.export`

- **display_name**: 导出会话
- **execution_tool_id**: `session.export`
- **legacy_aliases**: `session.export`
- **category / group / action**: runtime / session / export
- **capability_actions**: `runtime.audit.inspect`, `session.export`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 导出 session 安全摘要
- **边界**: 不要导出 secret

### `session.list`

- **display_name**: 列出会话
- **execution_tool_id**: `session.list`
- **legacy_aliases**: `session.list`
- **category / group / action**: runtime / session / list
- **capability_actions**: `runtime.audit.inspect`, `session.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出 workspace sessions
- **边界**: 不要跨 workspace

### `session.rewind`

- **display_name**: 回退会话
- **execution_tool_id**: `session.rewind`
- **legacy_aliases**: `session.rewind`
- **category / group / action**: runtime / session / rewind
- **capability_actions**: `session.rewind`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 回退到 session snapshot
- **边界**: 不要声称完整 checkpoint

### `session.snapshot.create`

- **display_name**: 创建会话快照
- **execution_tool_id**: `session.snapshot`
- **legacy_aliases**: `session.snapshot`
- **category / group / action**: runtime / session / snapshot_create
- **capability_actions**: `session.snapshot.create`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 创建 session snapshot
- **边界**: 不要复制 secret

### `session.snapshot.list`

- **display_name**: 列出会话快照
- **execution_tool_id**: `session.list_snapshots`
- **legacy_aliases**: `session.list_snapshots`
- **category / group / action**: runtime / session / snapshot_list
- **capability_actions**: `runtime.audit.inspect`, `session.snapshot.list`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出 session snapshots
- **边界**: 不要恢复状态

### `session.summary.get`

- **display_name**: 获取会话摘要
- **execution_tool_id**: `session.get_summary`
- **legacy_aliases**: `session.get_summary`
- **category / group / action**: runtime / session / summary_get
- **capability_actions**: `runtime.audit.inspect`, `session.summary.get`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 session 摘要
- **边界**: 不要读取其它 workspace

### 5.8. Web 外部资料 (`web`)

**说明**：公开 Web、官方文档、新闻、天气和网页摘要

**典型场景**：公开 Web 搜索、厂商官方文档、新闻、天气查询

**不适用场景**：不抓私网/本地/登录墙 URL；weather 仅在明确天气需求时使用

**包含 groups**：`docs, news, page, search, weather`

**canonical tools 数**：8

### `web.docs.official_search`

- **display_name**: 搜索官方文档
- **execution_tool_id**: `web.official_doc_search`
- **legacy_aliases**: `web.official_doc_search`
- **category / group / action**: web / docs / official_search
- **capability_actions**: `web.docs.official_search`, `web.official_docs.search`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 搜索厂商/标准官方资料
- **边界**: 不要用于本地文件

### `web.news.search`

- **display_name**: 搜索新闻
- **execution_tool_id**: `news.search`
- **legacy_aliases**: `news.search`
- **category / group / action**: web / news / search
- **capability_actions**: none  
  reason: internal/helper/manual-only
- **governance_status**: `deprecated`
- **replacement**: `—`  
  **migration_notes**: Do not select in planner; legacy direct calls still execute with a warning.
- **planner_visible**: false
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 搜索公开新闻信息
- **边界**: 不要用于本地文件

### `web.page.extract_links`

- **display_name**: 提取网页链接
- **execution_tool_id**: `web.extract_links`
- **legacy_aliases**: `web.extract_links`
- **category / group / action**: web / page / extract_links
- **capability_actions**: `web.official_docs.search`, `web.page.extract_links`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 从网页摘要中提取链接
- **边界**: 不要抓取私有站点

### `web.page.save_artifact`

- **display_name**: 保存网页摘要
- **execution_tool_id**: `web.save_to_artifact`
- **legacy_aliases**: `web.save_to_artifact`
- **category / group / action**: web / page / save_artifact
- **capability_actions**: `web.page.save_artifact`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 把网页安全摘要保存为 artifact
- **边界**: 不要保存未授权全文

### `web.page.summarize`

- **display_name**: 总结网页
- **execution_tool_id**: `web.fetch_summary`
- **legacy_aliases**: `web.fetch_summary`
- **category / group / action**: web / page / summarize
- **capability_actions**: `web.official_docs.search`, `web.page.summarize`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 获取公开网页摘要
- **边界**: 不要绕过 robots 或登录墙

### `web.search`

- **display_name**: Web 搜索
- **execution_tool_id**: `web.search`
- **legacy_aliases**: `web.search`
- **category / group / action**: web / search / general
- **capability_actions**: `web.official_docs.search`, `web.search`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 搜索公开 Web 信息
- **边界**: 不要用于 private/local 文件

### `web.weather.current`

- **display_name**: 当前天气
- **execution_tool_id**: `weather.current`
- **legacy_aliases**: `weather.current`
- **category / group / action**: web / weather / current
- **capability_actions**: `web.weather.current`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 查询公开天气信息
- **边界**: 不要用于本机环境状态

### `web.weather.forecast`

- **display_name**: 天气预报
- **execution_tool_id**: `weather.forecast`
- **legacy_aliases**: `weather.forecast`
- **category / group / action**: web / weather / forecast
- **capability_actions**: `web.weather.forecast`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 查询公开天气预报
- **边界**: 不要用于网络设备状态

### 5.9. Workspace 工作区 (`workspace`)

**说明**：工作区文件、Artifact 制品和 workspace 元数据

**典型场景**：工作区文件列表/读取/编辑、artifact 元数据、安全摘要读写

**不适用场景**：不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径

**包含 groups**：`artifact, document, file, metadata`

**canonical tools 数**：16

### `workspace.artifact.diff`

- **display_name**: 比较制品
- **execution_tool_id**: `artifact.diff`
- **legacy_aliases**: `artifact.diff`
- **category / group / action**: workspace / artifact / diff
- **capability_actions**: `workspace.artifact.diff`, `workspace.artifact.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 比较两个 workspace artifact 的安全摘要
- **边界**: 不要读取任意本地路径

### `workspace.artifact.export`

- **display_name**: 导出制品
- **execution_tool_id**: `artifact.export`
- **legacy_aliases**: `artifact.export`
- **category / group / action**: workspace / artifact / export
- **capability_actions**: `workspace.artifact.export`, `workspace.artifact.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 导出 workspace artifact 的安全格式
- **边界**: 不要导出 secret artifact

### `workspace.artifact.list`

- **display_name**: 列出制品
- **execution_tool_id**: `artifact.list`
- **legacy_aliases**: `artifact.list`
- **category / group / action**: workspace / artifact / list
- **capability_actions**: `workspace.artifact.list`, `workspace.artifact.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出 workspace 内 artifact 元数据
- **边界**: 不要用于文件系统遍历

### `workspace.artifact.read`

- **display_name**: 读取制品
- **execution_tool_id**: `artifact.read`
- **legacy_aliases**: `artifact.read`
- **category / group / action**: workspace / artifact / read
- **capability_actions**: `workspace.artifact.manage`, `workspace.artifact.read`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取允许访问的 artifact 安全内容
- **边界**: 不要绕过敏感内容策略

### `workspace.artifact.save`

- **display_name**: 保存结果制品
- **execution_tool_id**: `artifact.save_result`
- **legacy_aliases**: `artifact.save_result`
- **category / group / action**: workspace / artifact / save
- **capability_actions**: `report.create_and_save`, `workspace.artifact.manage`, `workspace.artifact.save`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 把工具结果保存为 workspace artifact
- **边界**: 不要保存未脱敏 secret

### `workspace.document.pdf.extract_text`

- **display_name**: 提取 PDF 文本
- **execution_tool_id**: `pdf.extract_text`
- **legacy_aliases**: `pdf.extract_text`
- **category / group / action**: workspace / document / extract_text
- **capability_actions**: `workspace.document.pdf.extract_text`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 提取 workspace PDF 文本
- **边界**: 不要读取非 PDF 或工作区外文件

### `workspace.file.edit`

- **display_name**: 编辑工作区文件
- **execution_tool_id**: `file.edit`
- **legacy_aliases**: `file.edit`
- **category / group / action**: workspace / file / edit
- **capability_actions**: `workspace.file.edit`, `workspace.file.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 替换 workspace 内文本文件片段
- **边界**: 不要编辑绝对路径或 secret 文件

### `workspace.file.exists`

- **display_name**: 检查文件存在
- **execution_tool_id**: `file.exists`
- **legacy_aliases**: `file.exists`
- **category / group / action**: workspace / file / exists
- **capability_actions**: `workspace.file.exists`, `workspace.file.manage`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 检查 workspace 文件是否存在
- **边界**: 不要用于 artifact id

### `workspace.file.list`

- **display_name**: 列出工作区文件
- **execution_tool_id**: `file.list`
- **legacy_aliases**: `file.list`
- **category / group / action**: workspace / file / list
- **capability_actions**: `workspace.file.list`, `workspace.file.manage`, `workspace.file.read`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出 workspace 文件
- **边界**: 不要列出系统目录

### `workspace.file.list_all`

- **display_name**: 列出工作区文件树
- **execution_tool_id**: `workspace.list_files`
- **legacy_aliases**: `workspace.list_files`, `workspace.file.list`
- **category / group / action**: workspace / file / list_all
- **capability_actions**: none  
  reason: internal/helper/manual-only
- **governance_status**: `merged`
- **replacement**: `workspace.file.list`  
  **migration_notes**: Use workspace.file.list; legacy execution remains registered for trace compatibility.
- **planner_visible**: false
- **risk_level**: low
- **requires_approval**: false
- **用途**: 列出 workspace 文件树预览
- **边界**: 不要列出系统目录

### `workspace.file.patch`

- **display_name**: 应用文件补丁
- **execution_tool_id**: `file.patch`
- **legacy_aliases**: `file.patch`
- **category / group / action**: workspace / file / patch
- **capability_actions**: `workspace.file.manage`, `workspace.file.patch`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 对 workspace 文件应用 unified diff
- **边界**: 不要修改工作区之外路径

### `workspace.file.path_exists`

- **display_name**: 检查工作区路径
- **execution_tool_id**: `workspace.path_exists`
- **legacy_aliases**: `workspace.path_exists`, `workspace.file.exists`
- **category / group / action**: workspace / file / path_exists
- **capability_actions**: none  
  reason: internal/helper/manual-only
- **governance_status**: `alias`
- **replacement**: `workspace.file.exists`  
  **migration_notes**: Resolve planner calls to workspace.file.exists; keep old id as alias only.
- **planner_visible**: false
- **risk_level**: low
- **requires_approval**: false
- **用途**: 检查 workspace 路径存在性
- **边界**: 不要检查工作区外路径

### `workspace.file.preview`

- **display_name**: 预览工作区文本
- **execution_tool_id**: `workspace.read_text_preview`
- **legacy_aliases**: `workspace.read_text_preview`
- **category / group / action**: workspace / file / preview
- **capability_actions**: `workspace.file.preview`, `workspace.file.read`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 workspace 文本文件安全预览
- **边界**: 不要读取完整大文件

### `workspace.file.read`

- **display_name**: 读取工作区文件
- **execution_tool_id**: `file.read`
- **legacy_aliases**: `file.read`
- **category / group / action**: workspace / file / read
- **capability_actions**: `workspace.file.read`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 workspace 内完整文本文件
- **边界**: 不要用于 artifact、知识库或任意绝对路径

### `workspace.file.write_artifact`

- **display_name**: 写入制品文件
- **execution_tool_id**: `workspace.write_artifact_file`
- **legacy_aliases**: `workspace.write_artifact_file`
- **category / group / action**: workspace / file / write_artifact
- **capability_actions**: `workspace.file.write_artifact`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: medium
- **requires_approval**: false
- **用途**: 向 workspace artifact 输出区写文件
- **边界**: 不要写任意路径

### `workspace.metadata.get`

- **display_name**: 读取工作区元数据
- **execution_tool_id**: `workspace.get_metadata`
- **legacy_aliases**: `workspace.get_metadata`
- **category / group / action**: workspace / metadata / get
- **capability_actions**: `workspace.metadata.get`
- **governance_status**: `keep`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **用途**: 读取 workspace 安全元数据
- **边界**: 不要返回 secret


## 6. Governance Summary

详见 §2.1 与 §7；此处汇总非 keep 工具的统计：

- alias: 1，merged: 1，deprecated: 1，removed_candidate: 1

## 7. Deprecated / Alias / Merged / Removed Candidate

| canonical_tool_id | governance_status | replacement | reason | migration_notes |
|---|---|---|---|---|
| `text.classify` | `removed_candidate` | `—` | Rule-only text classification is a future candidate for consolidation into text.process. | Keep in v2.3; require a deprecation release before any real removal. |
| `web.news.search` | `deprecated` | `—` | News search remains callable for legacy requests but is not a default planner action. | Do not select in planner; legacy direct calls still execute with a warning. |
| `workspace.file.list_all` | `merged` | `workspace.file.list` | workspace.list_files is a broader listing variant; keep compatibility but plan against workspace.file.list. | Use workspace.file.list; legacy execution remains registered for trace compatibility. |
| `workspace.file.path_exists` | `alias` | `workspace.file.exists` | workspace.path_exists is a compatibility alias for workspace.file.exists. | Resolve planner calls to workspace.file.exists; keep old id as alias only. |

## 8. Planner 可见工具

`planner_visible_count = 84`，等于 `governance.keep`。下面 88 个工具中，4 个不进 planner 候选。

### 8.1 planner 可见（keep）

- `agent.result.get`
- `agent.role.list`
- `agent.spawn`
- `agent.team.run`
- `data.csv.summarize`
- `data.json.validate`
- `data.table.extract`
- `data.table.render`
- `data.yaml.validate`
- `diagram.mermaid.render`
- `document.safe_summary.render`
- `host.command.slash_run`
- `host.powershell.exec`
- `host.python.exec`
- `host.shell.exec`
- `knowledge.chunk.list`
- `knowledge.chunk.read`
- `knowledge.import.document`
- `knowledge.import.file`
- `knowledge.parent.read`
- `knowledge.query`
- `knowledge.search`
- `knowledge.source.delete`
- `knowledge.source.disable`
- `knowledge.source.list`
- `knowledge.source.read`
- `knowledge.source.reindex`
- `memory.confirm`
- `memory.create`
- `memory.delete_soft`
- `memory.list`
- `memory.profile.get`
- `memory.profile.set`
- `memory.search`
- `memory.update`
- `network.config.parse`
- `network.config.translate`
- `network.interface.extract`
- `network.route.extract`
- `report.artifact.save`
- `report.markdown.render`
- `review.item.list`
- `review.item.update`
- `run.list`
- `run.summary.get`
- `runtime.diagnostics`
- `runtime.health`
- `session.checkpoint`
- `session.export`
- `session.list`
- `session.rewind`
- `session.snapshot.create`
- `session.snapshot.list`
- `session.summary.get`
- `skill.create`
- `skill.find`
- `skill.inspect`
- `skill.list`
- `skill.load`
- `skill.request_load`
- `text.diff`
- `text.keywords.extract`
- `text.redact`
- `web.docs.official_search`
- `web.page.extract_links`
- `web.page.save_artifact`
- `web.page.summarize`
- `web.search`
- `web.weather.current`
- `web.weather.forecast`
- `workspace.artifact.diff`
- `workspace.artifact.export`
- `workspace.artifact.list`
- `workspace.artifact.read`
- `workspace.artifact.save`
- `workspace.document.pdf.extract_text`
- `workspace.file.edit`
- `workspace.file.exists`
- `workspace.file.list`
- `workspace.file.patch`
- `workspace.file.preview`
- `workspace.file.read`
- `workspace.file.write_artifact`
- `workspace.metadata.get`

### 8.2 planner 不可见（非 keep）

- `text.classify` — `removed_candidate`
- `web.news.search` — `deprecated`
- `workspace.file.list_all` — `merged` → workspace.file.list
- `workspace.file.path_exists` — `alias` → workspace.file.exists

## 9. Legacy Compatibility

legacy_alias_count = 90，所有 legacy 别名都映射到 canonical id。

| legacy_alias | execution_tool_id | canonical_tool_id | governance_status |
|---|---|---|---|
| `agent.get_result` | `agent.get_result` | `agent.result.get` | `keep` |
| `agent.list_roles` | `agent.list_roles` | `agent.role.list` | `keep` |
| `agent.spawn` | `agent.spawn` | `agent.spawn` | `keep` |
| `agent.team` | `agent.team` | `agent.team.run` | `keep` |
| `csv.summarize` | `csv.summarize` | `data.csv.summarize` | `keep` |
| `json.validate` | `json.validate` | `data.json.validate` | `keep` |
| `table.extract` | `table.extract` | `data.table.extract` | `keep` |
| `table.render_markdown` | `table.render_markdown` | `data.table.render` | `keep` |
| `yaml.validate` | `yaml.validate` | `data.yaml.validate` | `keep` |
| `diagram.render_mermaid` | `diagram.render_mermaid` | `diagram.mermaid.render` | `keep` |
| `doc.render_from_safe_summary` | `doc.render_from_safe_summary` | `document.safe_summary.render` | `keep` |
| `slash.run` | `slash.run` | `host.command.slash_run` | `keep` |
| `powershell.exec` | `powershell.exec` | `host.powershell.exec` | `keep` |
| `python.exec` | `python.exec` | `host.python.exec` | `keep` |
| `shell.exec` | `shell.exec` | `host.shell.exec` | `keep` |
| `knowledge.list_chunks` | `knowledge.list_chunks` | `knowledge.chunk.list` | `keep` |
| `knowledge.read_chunk` | `knowledge.read_chunk` | `knowledge.chunk.read` | `keep` |
| `knowledge.import_document` | `knowledge.import_document` | `knowledge.import.document` | `keep` |
| `knowledge.import_file` | `knowledge.import_file` | `knowledge.import.file` | `keep` |
| `knowledge.read_parent` | `knowledge.read_parent` | `knowledge.parent.read` | `keep` |
| `knowledge.query` | `knowledge.query` | `knowledge.query` | `keep` |
| `knowledge.search_chunks` | `knowledge.search_chunks` | `knowledge.search` | `keep` |
| `knowledge.delete_source` | `knowledge.delete_source` | `knowledge.source.delete` | `keep` |
| `knowledge.disable_source` | `knowledge.disable_source` | `knowledge.source.disable` | `keep` |
| `knowledge.list_sources` | `knowledge.list_sources` | `knowledge.source.list` | `keep` |
| `knowledge.read_source` | `knowledge.read_source` | `knowledge.source.read` | `keep` |
| `knowledge.reindex_source` | `knowledge.reindex_source` | `knowledge.source.reindex` | `keep` |
| `memory.confirm` | `memory.confirm` | `memory.confirm` | `keep` |
| `memory.create` | `memory.create` | `memory.create` | `keep` |
| `memory.delete_soft` | `memory.delete_soft` | `memory.delete_soft` | `keep` |
| `memory.list` | `memory.list` | `memory.list` | `keep` |
| `memory.get_profile` | `memory.get_profile` | `memory.profile.get` | `keep` |
| `memory.set_profile` | `memory.set_profile` | `memory.profile.set` | `keep` |
| `memory.search` | `memory.search` | `memory.search` | `keep` |
| `memory.update` | `memory.update` | `memory.update` | `keep` |
| `parser.parse_config_text` | `parser.parse_config_text` | `network.config.parse` | `keep` |
| `config_translation.translate_config` | `config_translation.translate_config` | `network.config.translate` | `keep` |
| `parser.extract_interfaces` | `parser.extract_interfaces` | `network.interface.extract` | `keep` |
| `parser.extract_routes` | `parser.extract_routes` | `network.route.extract` | `keep` |
| `report.save_artifact` | `report.save_artifact` | `report.artifact.save` | `keep` |
| `report.render_markdown` | `report.render_markdown` | `report.markdown.render` | `keep` |
| `review.list_items` | `review.list_items` | `review.item.list` | `keep` |
| `review.update_item` | `review.update_item` | `review.item.update` | `keep` |
| `run.list_recent` | `run.list_recent` | `run.list` | `keep` |
| `run.get_summary` | `run.get_summary` | `run.summary.get` | `keep` |
| `runtime.diagnostics` | `runtime.diagnostics` | `runtime.diagnostics` | `keep` |
| `runtime.health` | `runtime.health` | `runtime.health` | `keep` |
| `session.checkpoint` | `session.checkpoint` | `session.checkpoint` | `keep` |
| `session.export` | `session.export` | `session.export` | `keep` |
| `session.list` | `session.list` | `session.list` | `keep` |
| `session.rewind` | `session.rewind` | `session.rewind` | `keep` |
| `session.snapshot` | `session.snapshot` | `session.snapshot.create` | `keep` |
| `session.list_snapshots` | `session.list_snapshots` | `session.snapshot.list` | `keep` |
| `session.get_summary` | `session.get_summary` | `session.summary.get` | `keep` |
| `skill.create` | `skill.create` | `skill.create` | `keep` |
| `skill.find_skills` | `skill.find_skills` | `skill.find` | `keep` |
| `skill.inspect` | `skill.inspect` | `skill.inspect` | `keep` |
| `skill.list` | `skill.list` | `skill.list` | `keep` |
| `skill.load` | `skill.load` | `skill.load` | `keep` |
| `skill.request_load` | `skill.request_load` | `skill.request_load` | `keep` |
| `text.classify` | `text.classify` | `text.classify` | `removed_candidate` |
| `text.diff` | `text.diff` | `text.diff` | `keep` |
| `text.extract_keywords` | `text.extract_keywords` | `text.keywords.extract` | `keep` |
| `text.redact` | `text.redact` | `text.redact` | `keep` |
| `web.official_doc_search` | `web.official_doc_search` | `web.docs.official_search` | `keep` |
| `news.search` | `news.search` | `web.news.search` | `deprecated` |
| `web.extract_links` | `web.extract_links` | `web.page.extract_links` | `keep` |
| `web.save_to_artifact` | `web.save_to_artifact` | `web.page.save_artifact` | `keep` |
| `web.fetch_summary` | `web.fetch_summary` | `web.page.summarize` | `keep` |
| `web.search` | `web.search` | `web.search` | `keep` |
| `weather.current` | `weather.current` | `web.weather.current` | `keep` |
| `weather.forecast` | `weather.forecast` | `web.weather.forecast` | `keep` |
| `artifact.diff` | `artifact.diff` | `workspace.artifact.diff` | `keep` |
| `artifact.export` | `artifact.export` | `workspace.artifact.export` | `keep` |
| `artifact.list` | `artifact.list` | `workspace.artifact.list` | `keep` |
| `artifact.read` | `artifact.read` | `workspace.artifact.read` | `keep` |
| `artifact.save_result` | `artifact.save_result` | `workspace.artifact.save` | `keep` |
| `pdf.extract_text` | `pdf.extract_text` | `workspace.document.pdf.extract_text` | `keep` |
| `file.edit` | `file.edit` | `workspace.file.edit` | `keep` |
| `file.exists` | `file.exists` | `workspace.file.exists` | `keep` |
| `file.list` | `file.list` | `workspace.file.list` | `keep` |
| `workspace.list_files` | `workspace.list_files` | `workspace.file.list_all` | `merged` |
| `workspace.file.list` | `workspace.list_files` | `workspace.file.list_all` | `merged` |
| `file.patch` | `file.patch` | `workspace.file.patch` | `keep` |
| `workspace.path_exists` | `workspace.path_exists` | `workspace.file.path_exists` | `alias` |
| `workspace.file.exists` | `workspace.path_exists` | `workspace.file.path_exists` | `alias` |
| `workspace.read_text_preview` | `workspace.read_text_preview` | `workspace.file.preview` | `keep` |
| `file.read` | `file.read` | `workspace.file.read` | `keep` |
| `workspace.write_artifact_file` | `workspace.write_artifact_file` | `workspace.file.write_artifact` | `keep` |
| `workspace.get_metadata` | `workspace.get_metadata` | `workspace.metadata.get` | `keep` |

## 10. 注意边界

- **不再以旧 execution id 为主标题**：三级标题一律为 canonical_tool_id。
- **不再只列 execution_tool_id**：每个工具都同时给出 execution / legacy / governance / planner_visible / capability_actions。
- **文档统计与 audit json 必须一致**：本文档由 `scripts/build_tool_catalog_v23.py` 生成，与 `reports/tool_architecture_audit.json` 的 summary 对齐。
- **planner 不选非 keep 工具**：deprecated / removed_candidate 仅保留为 兼容调用通道，rule_scene / capability_action 不会把它们加入候选。
- **host.* 高风险**：shell / powershell / python.exec 仅在本机执行，需要 approval_id，绝不用于网络设备 SSH/Telnet/SNMP。
- **network.* 离线**：解析/翻译/接口/路由全部离线，不登录真实设备，不生成 deployable_config。
- **artifact.read_safe 不再独立**：v2.3 起 `workspace.artifact.read` 是统一入口，安全语义由 policy + metadata 承担；`workspace.artifact.read_safe` 不再独立维护。
- **memory 不写 secret**：memory.create / profile.set 不写入 secret；confirm 留给用户决定是否升级为长期记忆。
- **web 公开 URL**：web.* 只访问公开 URL，私网/本地/登录墙 URL 被路径安全层直接拒绝。
