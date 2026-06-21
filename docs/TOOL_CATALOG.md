# Network Agent Tool Catalog (v3.0 canonical-only)

> Single source: `tool_runtime/tool_namespace.py` + `tool_runtime/tool_governance.py` + `tool_runtime/canonical_registry.py` + `tool_runtime/capability_actions.py`.

Machine-readable mirror: `reports/tool_catalog.json`. Verifier: `scripts/verify_tool_catalog_doc.py`.

## 1. Identity Contract

v3.0 tool IDs are canonical-only. Tools outside the active public surface are represented by governance_status `forbidden`.

- **canonical_tool_id**: the public tool ID used by the LLM, frontend, planner, API, docs, and trace.
- **handler_id**: an internal implementation key. It never appears in the public catalog, LLM prompt, frontend default view, or docs main tables.
- **capability_action**: a high-level planner verb that expands to one or more canonical_tool_ids.
- **governance_status**: one of `active | disabled | internal | forbidden`.

## 2. Summary

- **canonical_count**: 104
- **handler_count**: 104
- **planner_visible_count**: 104
- **capability_action_count**: 122
- **category_count**: 9

### 2.1 Governance Summary

| status | count | meaning |
|---|---|---|
| active | 104 | planner default candidate |
| disabled | 0 | not available right now |
| internal | 0 | runtime-only, never exposed |
| forbidden | 0 | refused by registry |

## 3. Capability Domains

| Domain | Description | Typical use | Not for | Groups | Tools | Planner visible |
|---|---|---|---|---|---|---|
| **Agent 多 Agent** (`agent`) | 技能、子 Agent、角色、团队和结果读取。 | 子 Agent、技能、角色、团队任务编排。 | agent.spawn 受 max_turns≤3 限制；skill.load 不加载未经审查的技能。 | 7 | 14 | 14 |
| **Host 本机环境** (`host`) | 当前运行机器上的本机 OS、Shell、PowerShell、Python 工具。 | 本机 shell / powershell / python 执行、slash 命令、运行诊断。 | 不用于网络设备 SSH / Telnet / SNMP / 真实设备访问；不用于解析配置文本。 | 4 | 4 | 4 |
| **Knowledge 知识库** (`knowledge`) | 知识库问答、检索、导入和索引管理。 | 知识库检索、chunk/source 维护、导入文件 / 文档。 | 不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体。 | 6 | 16 | 16 |
| **Memory 记忆** (`memory`) | 记忆搜索、创建、确认、profile 和更新。 | 用户偏好与历史记忆的搜索、写入、确认、profile。 | 不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认。 | 2 | 8 | 8 |
| **Network 网络分析** (`network`) | 离线网络配置解析、接口 / 路由提取和配置翻译。 | 解析 / 翻译 / 接口提取 / 路由提取等离线分析。 | 不登录真实设备；不下发配置；translated_config 不等于 deployable_config。 | 2 | 2 | 2 |
| **Report / Data / Text 输出处理** (`report_data`) | 报告、表格、文本、JSON / YAML / CSV 和图表处理。 | 报告 / 表格 / 图表 / JSON / YAML / CSV / 文本处理输出。 | 不包含原始敏感配置作为最终输出；text.redact 用于脱敏；validate 不执行代码。 | 8 | 13 | 13 |
| **Runtime 运行审计** (`runtime`) | 运行状态、session、run、review 和审计信息。 | 运行健康 / 诊断、session / run / review 审计。 | 不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物。 | 6 | 16 | 16 |
| **Web 外部资料** (`web`) | 公开 Web、官方文档、新闻、天气和网页摘要。 | 公开 Web 搜索、厂商官方文档、新闻、天气查询。 | 不抓私网 / 本地 / 登录墙 URL；weather 仅在明确天气需求时使用。 | 5 | 8 | 8 |
| **Workspace 工作区** (`workspace`) | 工作区文件、Artifact 制品和 workspace 元数据。 | 工作区文件列表 / 读取 / 编辑、artifact 元数据、安全摘要读写。 | 不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径。 | 4 | 23 | 23 |

## 4. Capability Actions

```text
user request
→ capability_action plan
→ canonical tools (preferred + fallback)
→ governance filter (status == active)
→ candidate_tools
→ ToolRouter
→ handler_id dispatch
```

| capability_action | category | group | preferred_tools | fallback_tools | reason |
|---|---|---|---|---|---|
| `agent.result.get` | agent | result | `agent.result.get` | — | Direct canonical action. |
| `agent.role.list` | agent | role | `agent.role.list` | — | Direct canonical action. |
| `agent.skill.manage` | agent | skill | `skill.list`, `skill.search`, `skill.get`, `skill.load`, `skill.unload` | — | Discover, inspect, load and unload skills. |
| `agent.spawn` | agent | subagent | `agent.spawn` | — | Direct canonical action. |
| `agent.team.coordinate` | agent | team | `agent.spawn`, `agent.role.list`, `agent.result.get` | `agent.team.run`, `skill.list`, `skill.load` | Coordinate child-agent work under runtime limits. |
| `agent.team.run` | agent | team | `agent.team.run` | — | Direct canonical action. |
| `config.analysis` | network | config_analysis | `workspace.file.read`, `config.analysis.run` | — | Unified config analysis entrypoint. |
| `config.analysis.run` | network | config_analysis | `config.analysis.run` | — | Direct canonical action. |
| `config.translation` | network | config_analysis | `workspace.file.read`, `config.analysis.run` | — | Unified config translation entrypoint. |
| `data.csv.summarize` | report_data | csv | `data.csv.summarize` | — | Direct canonical action. |
| `data.json.validate` | report_data | json | `data.json.validate` | — | Direct canonical action. |
| `data.table.extract` | report_data | table | `data.table.extract` | — | Direct canonical action. |
| `data.table.render` | report_data | table | `data.table.render` | — | Direct canonical action. |
| `data.text.process` | report_data | text | `text.redact`, `text.diff`, `text.keywords.extract` | `data.json.validate`, `data.yaml.validate`, `data.csv.summarize`, `data.table.extract`, `data.table.render` | Process structured data and safe text outputs. |
| `data.yaml.validate` | report_data | yaml | `data.yaml.validate` | — | Direct canonical action. |
| `diagram.mermaid.render` | report_data | diagram | `diagram.mermaid.render` | — | Direct canonical action. |
| `document.safe_summary.render` | report_data | document | `document.safe_summary.render` | — | Direct canonical action. |
| `file.get` | workspace | file | `file.get` | — | Direct canonical action. |
| `file.import_workspace_path` | workspace | file | `file.import_workspace_path` | — | Direct canonical action. |
| `file.preview` | workspace | file | `file.preview` | — | Direct canonical action. |
| `file.references` | workspace | file | `file.references` | — | Direct canonical action. |
| `file.write_agent_output` | workspace | file | `file.write_agent_output` | — | Direct canonical action. |
| `host.command.slash_run` | host | command | `host.command.slash_run` | — | Direct canonical action. |
| `host.environment.inspect` | host | shell | `host.shell.exec`, `host.powershell.exec`, `host.python.exec`, `runtime.health`, `runtime.diagnostics` | `host.command.slash_run` | Inspect or operate on the current local host under approval policy. |
| `host.powershell.exec` | host | powershell | `host.powershell.exec` | — | Direct canonical action. |
| `host.python.exec` | host | python | `host.python.exec` | — | Direct canonical action. |
| `host.shell.exec` | host | shell | `host.shell.exec` | — | Direct canonical action. |
| `knowledge.chunk.list` | knowledge | chunk | `knowledge.chunk.list` | — | Direct canonical action. |
| `knowledge.chunk.read` | knowledge | chunk | `knowledge.chunk.read` | — | Direct canonical action. |
| `knowledge.chunk.summary` | knowledge | chunk | `knowledge.chunk.summary` | — | Direct canonical action. |
| `knowledge.import.artifact` | knowledge | import | `knowledge.import.artifact` | — | Direct canonical action. |
| `knowledge.import.document` | knowledge | import | `knowledge.import.document` | — | Direct canonical action. |
| `knowledge.import.file` | knowledge | import | `knowledge.import.file` | — | Direct canonical action. |
| `knowledge.maintain` | knowledge | import | `knowledge.import.file`, `knowledge.import.document`, `knowledge.import.artifact`, `knowledge.source.reindex` | `knowledge.source.reindex_all`, `knowledge.source.disable`, `knowledge.source.delete` | Maintain the knowledge base (import, reindex, retire). |
| `knowledge.not_found.explain` | knowledge | not_found | `knowledge.not_found.explain` | — | Direct canonical action. |
| `knowledge.parent.read` | knowledge | parent | `knowledge.parent.read` | — | Direct canonical action. |
| `knowledge.search` | knowledge | search | `knowledge.search` | — | Direct canonical action. |
| `knowledge.search_and_answer` | knowledge | search | `knowledge.search` | `knowledge.chunk.read`, `knowledge.source.read`, `knowledge.parent.read` | Search the knowledge base and answer from safe excerpts. |
| `knowledge.source.delete` | knowledge | source | `knowledge.source.delete` | — | Direct canonical action. |
| `knowledge.source.disable` | knowledge | source | `knowledge.source.disable` | — | Direct canonical action. |
| `knowledge.source.get` | knowledge | source | `knowledge.source.get` | — | Direct canonical action. |
| `knowledge.source.list` | knowledge | source | `knowledge.source.list` | — | Direct canonical action. |
| `knowledge.source.read` | knowledge | source | `knowledge.source.read` | — | Direct canonical action. |
| `knowledge.source.reindex` | knowledge | source | `knowledge.source.reindex` | — | Direct canonical action. |
| `knowledge.source.reindex_all` | knowledge | source | `knowledge.source.reindex_all` | — | Direct canonical action. |
| `memory.confirm` | memory | record | `memory.confirm` | — | Direct canonical action. |
| `memory.create` | memory | record | `memory.create` | — | Direct canonical action. |
| `memory.delete_soft` | memory | record | `memory.delete_soft` | — | Direct canonical action. |
| `memory.list` | memory | record | `memory.list` | — | Direct canonical action. |
| `memory.profile.get` | memory | profile | `memory.profile.get` | — | Direct canonical action. |
| `memory.profile.manage` | memory | profile | `memory.search`, `memory.list`, `memory.profile.get`, `memory.profile.set` | `memory.create`, `memory.confirm`, `memory.update`, `memory.delete_soft` | Search and manage memory records and profile fields. |
| `memory.profile.set` | memory | profile | `memory.profile.set` | — | Direct canonical action. |
| `memory.search` | memory | record | `memory.search` | — | Direct canonical action. |
| `memory.update` | memory | record | `memory.update` | — | Direct canonical action. |
| `pcap.analysis` | network | pcap_analysis | `workspace.file.read`, `pcap.analysis.run` | — | Unified PCAP analysis entrypoint. |
| `pcap.analysis.run` | network | pcap_analysis | `pcap.analysis.run` | — | Direct canonical action. |
| `report.artifact.save` | report_data | report | `report.artifact.save` | — | Direct canonical action. |
| `report.create_and_save` | report_data | report | `report.markdown.render`, `workspace.artifact.save` | `data.table.render`, `diagram.mermaid.render` | Render a report and save it as a workspace artifact. |
| `report.markdown.render` | report_data | report | `report.markdown.render` | — | Direct canonical action. |
| `review.item.list` | runtime | review | `review.item.list` | — | Direct canonical action. |
| `review.item.update` | runtime | review | `review.item.update` | — | Direct canonical action. |
| `run.list` | runtime | run | `run.list` | — | Direct canonical action. |
| `run.summary.get` | runtime | run | `run.summary.get` | — | Direct canonical action. |
| `runtime.archive.preview` | runtime | archive | `runtime.archive.preview` | — | Direct canonical action. |
| `runtime.audit.inspect` | runtime | audit | `runtime.health`, `runtime.diagnostics`, `run.list`, `run.summary.get`, `session.list`, `session.summary.get` | `session.snapshot.list`, `session.export`, `runtime.selfcheck` | Inspect runtime, run, and session audit metadata. |
| `runtime.diagnostics` | runtime | health | `runtime.diagnostics` | — | Direct canonical action. |
| `runtime.health` | runtime | health | `runtime.health` | — | Direct canonical action. |
| `runtime.retention.preview` | runtime | retention | `runtime.retention.preview` | — | Direct canonical action. |
| `runtime.review.manage` | runtime | review | `review.item.list`, `review.item.update` | — | List and update review items. |
| `runtime.selfcheck` | runtime | health | `runtime.selfcheck` | — | Direct canonical action. |
| `runtime.session.manage` | runtime | session | `session.snapshot.create`, `session.snapshot.list`, `session.checkpoint`, `session.rewind`, `session.export` | — | Manage session lifecycle and snapshots. |
| `session.checkpoint` | runtime | session | `session.checkpoint` | — | Direct canonical action. |
| `session.export` | runtime | session | `session.export` | — | Direct canonical action. |
| `session.list` | runtime | session | `session.list` | — | Direct canonical action. |
| `session.rewind` | runtime | session | `session.rewind` | — | Direct canonical action. |
| `session.snapshot.create` | runtime | session | `session.snapshot.create` | — | Direct canonical action. |
| `session.snapshot.list` | runtime | session | `session.snapshot.list` | — | Direct canonical action. |
| `session.summary.get` | runtime | session | `session.summary.get` | — | Direct canonical action. |
| `skill.create` | agent | skill | `skill.create` | — | Direct canonical action. |
| `skill.get` | agent | skill | `skill.get` | — | Direct canonical action. |
| `skill.install` | agent | skill | `skill.install` | — | Direct canonical action. |
| `skill.list` | agent | skill | `skill.list` | — | Direct canonical action. |
| `skill.load` | agent | skill | `skill.load` | — | Direct canonical action. |
| `skill.search` | agent | skill | `skill.search` | — | Direct canonical action. |
| `skill.unload` | agent | skill | `skill.unload` | — | Direct canonical action. |
| `slash.command.list` | agent | slash_command | `slash.command.list` | — | Direct canonical action. |
| `slash.command.run` | agent | slash_command | `slash.command.run` | — | Direct canonical action. |
| `text.classify` | report_data | text | `text.classify` | — | Direct canonical action. |
| `text.diff` | report_data | text | `text.diff` | — | Direct canonical action. |
| `text.keywords.extract` | report_data | text | `text.keywords.extract` | — | Direct canonical action. |
| `text.redact` | report_data | text | `text.redact` | — | Direct canonical action. |
| `tool.catalog.search` | agent | tool_catalog | `tool.catalog.search` | — | Direct canonical action. |
| `web.docs.official_search` | web | docs | `web.docs.official_search` | — | Direct canonical action. |
| `web.news.search` | web | news | `web.news.search` | — | Direct canonical action. |
| `web.official_docs.search` | web | docs | `web.docs.official_search`, `web.search`, `web.page.summarize` | `web.page.extract_links` | Search official documentation and summarize public pages. |
| `web.page.extract_links` | web | page | `web.page.extract_links` | — | Direct canonical action. |
| `web.page.save_artifact` | web | page | `web.page.save_artifact` | — | Direct canonical action. |
| `web.page.summarize` | web | page | `web.page.summarize` | — | Direct canonical action. |
| `web.search` | web | search | `web.search` | — | Direct canonical action. |
| `web.weather.current` | web | weather | `web.weather.current` | — | Direct canonical action. |
| `web.weather.forecast` | web | weather | `web.weather.forecast` | — | Direct canonical action. |
| `web.weather.read` | web | weather | `web.weather.current`, `web.weather.forecast` | — | Read weather for a public location. |
| `workspace.artifact.delete_soft` | workspace | artifact | `workspace.artifact.delete_soft` | — | Direct canonical action. |
| `workspace.artifact.diff` | workspace | artifact | `workspace.artifact.diff` | — | Direct canonical action. |
| `workspace.artifact.export` | workspace | artifact | `workspace.artifact.export` | — | Direct canonical action. |
| `workspace.artifact.list` | workspace | artifact | `workspace.artifact.list` | — | Direct canonical action. |
| `workspace.artifact.manage` | workspace | artifact | `workspace.artifact.list`, `workspace.artifact.search`, `workspace.artifact.read`, `workspace.artifact.save` | `workspace.artifact.diff`, `workspace.artifact.export`, `workspace.artifact.tag`, `workspace.artifact.delete_soft` | Work with workspace artifact metadata and safe content. |
| `workspace.artifact.read` | workspace | artifact | `workspace.artifact.read` | — | Direct canonical action. |
| `workspace.artifact.save` | workspace | artifact | `workspace.artifact.save` | — | Direct canonical action. |
| `workspace.artifact.search` | workspace | artifact | `workspace.artifact.search` | — | Direct canonical action. |
| `workspace.artifact.tag` | workspace | artifact | `workspace.artifact.tag` | — | Direct canonical action. |
| `workspace.document.pdf.extract_text` | workspace | document | `workspace.document.pdf.extract_text` | — | Direct canonical action. |
| `workspace.file.edit` | workspace | file | `workspace.file.edit` | — | Direct canonical action. |
| `workspace.file.exists` | workspace | file | `workspace.file.exists` | — | Direct canonical action. |
| `workspace.file.list` | workspace | file | `workspace.file.list` | — | Direct canonical action. |
| `workspace.file.manage` | workspace | file | `workspace.file.list`, `workspace.file.exists`, `workspace.file.edit`, `workspace.file.patch` | `workspace.file.read`, `workspace.file.preview`, `workspace.file.write_artifact` | Manage workspace files end-to-end. |
| `workspace.file.patch` | workspace | file | `workspace.file.patch` | — | Direct canonical action. |
| `workspace.file.preview` | workspace | file | `workspace.file.preview` | — | Direct canonical action. |
| `workspace.file.read` | workspace | file | `workspace.file.read` | — | Direct canonical action. |
| `workspace.file.read_image` | workspace | file | `workspace.file.read_image` | — | Direct canonical action. |
| `workspace.file.write_artifact` | workspace | file | `workspace.file.write_artifact` | — | Direct canonical action. |
| `workspace.metadata.get` | workspace | metadata | `workspace.metadata.get` | — | Direct canonical action. |

## 5. Full Tool Listing

### 5.1. Agent 多 Agent (`agent`)

**Description**: 技能、子 Agent、角色、团队和结果读取。

**Typical use**: 子 Agent、技能、角色、团队任务编排。

**Not for**: agent.spawn 受 max_turns≤3 限制；skill.load 不加载未经审查的技能。

**Groups**: `result, role, skill, slash_command, subagent, team, tool_catalog`

**Canonical tools**: 14

### `agent.result.get`

- **display_name**: 读取 Agent 结果
- **category / group / action**: agent / result / get
- **capability_actions**: `agent.result.get`, `agent.team.coordinate`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get a sub-agent's result.
- **boundary**: Do not return unredacted payloads.

### `agent.role.list`

- **display_name**: 列出 Agent 角色
- **category / group / action**: agent / role / list
- **capability_actions**: `agent.role.list`, `agent.team.coordinate`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List agent roles.
- **boundary**: Do not invent roles.

### `agent.spawn`

- **display_name**: 创建子 Agent
- **category / group / action**: agent / subagent / spawn
- **capability_actions**: `agent.spawn`, `agent.team.coordinate`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Spawn a sub-agent for a task.
- **boundary**: max_turns is enforced; do not bypass it.

### `agent.team.run`

- **display_name**: 运行 Agent 团队
- **category / group / action**: agent / team / run
- **capability_actions**: `agent.team.coordinate`, `agent.team.run`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run a team of agents.
- **boundary**: max_turns and capability constraints apply.

### `skill.create`

- **display_name**: 创建新技能
- **category / group / action**: agent / skill / create
- **capability_actions**: `skill.create`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Create a new skill skeleton with SKILL.md and skill.yaml. Status: pending_review.
- **boundary**: Skills require manual review before activation.

### `skill.get`

- **display_name**: 读取技能详情
- **category / group / action**: agent / skill / get
- **capability_actions**: `agent.skill.manage`, `skill.get`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get details about a skill.
- **boundary**: Do not return untrusted skill bodies.

### `skill.install`

- **display_name**: 安装技能
- **category / group / action**: agent / skill / install
- **capability_actions**: `skill.install`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Install a skill from local directory, archive URL (.zip/.tar.gz), or SKILL.md markdown content. Status: pending_review.
- **boundary**: Installed skills require manual review before activation.

### `skill.list`

- **display_name**: 列出技能
- **category / group / action**: agent / skill / list
- **capability_actions**: `agent.skill.manage`, `agent.team.coordinate`, `skill.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List available skills.
- **boundary**: Do not enable untrusted skills.

### `skill.load`

- **display_name**: 加载技能
- **category / group / action**: agent / skill / load
- **capability_actions**: `agent.skill.manage`, `agent.team.coordinate`, `skill.load`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Load a skill into current turn context.
- **boundary**: Do not load untrusted skills.

### `skill.search`

- **display_name**: 搜索技能
- **category / group / action**: agent / skill / search
- **capability_actions**: `agent.skill.manage`, `skill.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search for a skill by name.
- **boundary**: Do not enable untrusted skills.

### `skill.unload`

- **display_name**: 卸载技能
- **category / group / action**: agent / skill / unload
- **capability_actions**: `agent.skill.manage`, `skill.unload`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Unload a skill from context.
- **boundary**: Do not unload safety-relevant skills.

### `slash.command.list`

- **display_name**: 列出 Slash 命令
- **category / group / action**: agent / slash_command / list
- **capability_actions**: `slash.command.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List registered slash commands.
- **boundary**: Do not invent commands.

### `slash.command.run`

- **display_name**: 执行 Slash 命令
- **category / group / action**: agent / slash_command / run
- **capability_actions**: `slash.command.run`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run a registered slash command.
- **boundary**: Do not run unregistered commands.

### `tool.catalog.search`

- **display_name**: 搜索工具目录
- **category / group / action**: agent / tool_catalog / search
- **capability_actions**: `tool.catalog.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search the full tool catalog when the visible tools are not enough or the request is ambiguous. Returns tool_ids that can be loaded into the current turn.
- **boundary**: Do not execute work by itself; use it only to discover the right specialized tool.

### 5.2. Host 本机环境 (`host`)

**Description**: 当前运行机器上的本机 OS、Shell、PowerShell、Python 工具。

**Typical use**: 本机 shell / powershell / python 执行、slash 命令、运行诊断。

**Not for**: 不用于网络设备 SSH / Telnet / SNMP / 真实设备访问；不用于解析配置文本。

**Groups**: `command, powershell, python, shell`

**Canonical tools**: 4

### `host.command.slash_run`

- **display_name**: Slash 命令执行
- **category / group / action**: host / command / slash_run
- **capability_actions**: `host.command.slash_run`, `host.environment.inspect`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run a slash command on the local host.
- **boundary**: Do not use for unregistered slash commands.

### `host.powershell.exec`

- **display_name**: 本机 PowerShell 执行
- **category / group / action**: host / powershell / exec
- **capability_actions**: `host.environment.inspect`, `host.powershell.exec`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **usage**: Run PowerShell on THIS local machine. Opens approval popup.
- **boundary**: Do not use for network device access.

### `host.python.exec`

- **display_name**: 本机 Python 执行
- **category / group / action**: host / python / exec
- **capability_actions**: `host.environment.inspect`, `host.python.exec`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **usage**: Run Python on the local host (sandboxed). Use for approved computation, data processing, custom parsing, or tasks that need code.
- **boundary**: Do not use for network device access. Prefer specialized workspace/network/knowledge tools when they directly satisfy the task.

### `host.shell.exec`

- **display_name**: 本机 Shell 执行
- **category / group / action**: host / shell / exec
- **capability_actions**: `host.environment.inspect`, `host.shell.exec`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: high
- **requires_approval**: true
- **usage**: Run a shell command on THIS local machine (NOT a remote device). Opens approval popup. Use for: ip lookup, system info, local diagnostics.
- **boundary**: Do not use for network device access. Prefer workspace/network tools for direct workspace-file or config parsing tasks.

### 5.3. Knowledge 知识库 (`knowledge`)

**Description**: 知识库问答、检索、导入和索引管理。

**Typical use**: 知识库检索、chunk/source 维护、导入文件 / 文档。

**Not for**: 不替代 Web 搜索；不返回未经脱敏全文；不删除 artifact 本体。

**Groups**: `chunk, import, not_found, parent, search, source`

**Canonical tools**: 16

### `knowledge.chunk.list`

- **display_name**: 列出知识块
- **category / group / action**: knowledge / chunk / list
- **capability_actions**: `knowledge.chunk.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List all chunks for a knowledge source.
- **boundary**: Do not include full content.

### `knowledge.chunk.read`

- **display_name**: 读取知识块
- **category / group / action**: knowledge / chunk / read
- **capability_actions**: `knowledge.chunk.read`, `knowledge.search_and_answer`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read a knowledge chunk's content by id. Use after knowledge.search to get full details.
- **boundary**: Do not return unredacted secrets.

### `knowledge.chunk.summary`

- **display_name**: 知识块摘要
- **category / group / action**: knowledge / chunk / summary
- **capability_actions**: `knowledge.chunk.summary`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get a summary of a knowledge chunk.
- **boundary**: Do not return the full chunk body when not needed.

### `knowledge.import.artifact`

- **display_name**: 导入知识制品
- **category / group / action**: knowledge / import / artifact
- **capability_actions**: `knowledge.import.artifact`, `knowledge.maintain`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Import a workspace artifact into the knowledge base.
- **boundary**: Do not import unredacted artifacts.

### `knowledge.import.document`

- **display_name**: 导入知识文档
- **category / group / action**: knowledge / import / document
- **capability_actions**: `knowledge.import.document`, `knowledge.maintain`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Import a document from URL into the knowledge base.
- **boundary**: Do not import unredacted secrets.

### `knowledge.import.file`

- **display_name**: 导入知识文件
- **category / group / action**: knowledge / import / file
- **capability_actions**: `knowledge.import.file`, `knowledge.maintain`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Import an uploaded file into the knowledge base.
- **boundary**: Do not import unredacted secrets.

### `knowledge.not_found.explain`

- **display_name**: 解释未命中
- **category / group / action**: knowledge / not_found / explain
- **capability_actions**: `knowledge.not_found.explain`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Explain why a search returned no results.
- **boundary**: Use only when a query has no result.

### `knowledge.parent.read`

- **display_name**: 读取父文档
- **category / group / action**: knowledge / parent / read
- **capability_actions**: `knowledge.parent.read`, `knowledge.search_and_answer`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read the parent document of a matched chunk.
- **boundary**: Do not return unredacted full text.

### `knowledge.search`

- **display_name**: 知识库检索
- **category / group / action**: knowledge / search / search
- **capability_actions**: `knowledge.search`, `knowledge.search_and_answer`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search the workspace knowledge base for indexed documents and chunks. Use for facts from uploaded files, previous research, or stored configs.
- **boundary**: Do not return unredacted full text.

### `knowledge.source.delete`

- **display_name**: 删除知识源
- **category / group / action**: knowledge / source / delete
- **capability_actions**: `knowledge.maintain`, `knowledge.source.delete`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Permanently delete a knowledge source.
- **boundary**: Do not delete without explicit confirmation.

### `knowledge.source.disable`

- **display_name**: 停用知识源
- **category / group / action**: knowledge / source / disable
- **capability_actions**: `knowledge.maintain`, `knowledge.source.disable`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Disable a knowledge source from searches.
- **boundary**: Do not delete sources.

### `knowledge.source.get`

- **display_name**: 获取知识源元数据
- **category / group / action**: knowledge / source / get
- **capability_actions**: `knowledge.source.get`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get details of a specific knowledge source.
- **boundary**: Do not return full content; use knowledge.source.read.

### `knowledge.source.list`

- **display_name**: 列出知识源
- **category / group / action**: knowledge / source / list
- **capability_actions**: `knowledge.source.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List all indexed knowledge sources with status and count.
- **boundary**: Do not include full content.

### `knowledge.source.read`

- **display_name**: 读取知识源
- **category / group / action**: knowledge / source / read
- **capability_actions**: `knowledge.search_and_answer`, `knowledge.source.read`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read the full content of a knowledge source.
- **boundary**: Do not return unredacted full content.

### `knowledge.source.reindex`

- **display_name**: 重建索引
- **category / group / action**: knowledge / source / reindex
- **capability_actions**: `knowledge.maintain`, `knowledge.source.reindex`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Reindex a specific knowledge source.
- **boundary**: Do not run against untrusted source without review.

### `knowledge.source.reindex_all`

- **display_name**: 重建全部索引
- **category / group / action**: knowledge / source / reindex_all
- **capability_actions**: `knowledge.maintain`, `knowledge.source.reindex_all`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Reindex ALL knowledge sources (destructive, slow).
- **boundary**: Do not run in production without explicit approval.

### 5.4. Memory 记忆 (`memory`)

**Description**: 记忆搜索、创建、确认、profile 和更新。

**Typical use**: 用户偏好与历史记忆的搜索、写入、确认、profile。

**Not for**: 不保存 secret；profile 更新需要边界说明；confirm 用于重要记忆确认。

**Groups**: `profile, record`

**Canonical tools**: 8

### `memory.confirm`

- **display_name**: 确认记忆
- **category / group / action**: memory / record / confirm
- **capability_actions**: `memory.confirm`, `memory.profile.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Confirm or resolve a conflicting memory.
- **boundary**: Use for important memory only.

### `memory.create`

- **display_name**: 创建记忆
- **category / group / action**: memory / record / create
- **capability_actions**: `memory.create`, `memory.profile.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Create a new memory record.
- **boundary**: Do not store secrets.

### `memory.delete_soft`

- **display_name**: 软删除记忆
- **category / group / action**: memory / record / delete_soft
- **capability_actions**: `memory.delete_soft`, `memory.profile.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Soft-delete a memory record.
- **boundary**: Do not hard-delete.

### `memory.list`

- **display_name**: 列出记忆
- **category / group / action**: memory / record / list
- **capability_actions**: `memory.list`, `memory.profile.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List all memory records.
- **boundary**: Do not include secrets.

### `memory.profile.get`

- **display_name**: 读取 Profile
- **category / group / action**: memory / profile / get
- **capability_actions**: `memory.profile.get`, `memory.profile.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read user profile from memory.
- **boundary**: Do not include secrets.

### `memory.profile.set`

- **display_name**: 更新 Profile
- **category / group / action**: memory / profile / set
- **capability_actions**: `memory.profile.manage`, `memory.profile.set`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Update user profile in memory.
- **boundary**: Do not store secrets.

### `memory.search`

- **display_name**: 搜索记忆
- **category / group / action**: memory / record / search
- **capability_actions**: `memory.profile.manage`, `memory.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search user persistent memory for past preferences and facts.
- **boundary**: Do not store secrets.

### `memory.update`

- **display_name**: 更新记忆
- **category / group / action**: memory / record / update
- **capability_actions**: `memory.profile.manage`, `memory.update`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Update an existing memory record.
- **boundary**: Do not store secrets.

### 5.5. Network 网络分析 (`network`)

**Description**: 离线网络配置解析、接口 / 路由提取和配置翻译。

**Typical use**: 解析 / 翻译 / 接口提取 / 路由提取等离线分析。

**Not for**: 不登录真实设备；不下发配置；translated_config 不等于 deployable_config。

**Groups**: `config_analysis, pcap_analysis`

**Canonical tools**: 2

### `config.analysis.run`

- **display_name**: 配置分析统一入口
- **category / group / action**: network / config_analysis / run
- **capability_actions**: `config.analysis`, `config.analysis.run`, `config.translation`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run config analysis actions: parse, translate, extract_interfaces, extract_routes, diff, summarize.
- **boundary**: Do not claim translated config is production-ready.

### `pcap.analysis.run`

- **display_name**: PCAP 分析统一入口
- **category / group / action**: network / pcap_analysis / run
- **capability_actions**: `pcap.analysis`, `pcap.analysis.run`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run PCAP analysis actions: parse, session, filter, align.
- **boundary**: Do not use for text configs.

### 5.6. Report / Data / Text 输出处理 (`report_data`)

**Description**: 报告、表格、文本、JSON / YAML / CSV 和图表处理。

**Typical use**: 报告 / 表格 / 图表 / JSON / YAML / CSV / 文本处理输出。

**Not for**: 不包含原始敏感配置作为最终输出；text.redact 用于脱敏；validate 不执行代码。

**Groups**: `csv, diagram, document, json, report, table, text, yaml`

**Canonical tools**: 13

### `data.csv.summarize`

- **display_name**: 汇总 CSV
- **category / group / action**: report_data / csv / summarize
- **capability_actions**: `data.csv.summarize`, `data.text.process`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Summarize CSV — columns, types, stats.
- **boundary**: Do not execute embedded code.

### `data.json.validate`

- **display_name**: 校验 JSON
- **category / group / action**: report_data / json / validate
- **capability_actions**: `data.json.validate`, `data.text.process`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Validate JSON structure.
- **boundary**: Do not execute embedded code.

### `data.table.extract`

- **display_name**: 提取表格
- **category / group / action**: report_data / table / extract
- **capability_actions**: `data.table.extract`, `data.text.process`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Extract table from text or markdown.
- **boundary**: Do not execute embedded code.

### `data.table.render`

- **display_name**: 渲染表格
- **category / group / action**: report_data / table / render
- **capability_actions**: `data.table.render`, `data.text.process`, `report.create_and_save`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Render tabular data as a table.
- **boundary**: Do not include raw sensitive rows.

### `data.yaml.validate`

- **display_name**: 校验 YAML
- **category / group / action**: report_data / yaml / validate
- **capability_actions**: `data.text.process`, `data.yaml.validate`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Validate YAML structure.
- **boundary**: Do not execute embedded code.

### `diagram.mermaid.render`

- **display_name**: 渲染 Mermaid 图
- **category / group / action**: report_data / diagram / mermaid_render
- **capability_actions**: `diagram.mermaid.render`, `report.create_and_save`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Render a Mermaid.js diagram.
- **boundary**: Do not render untrusted raw diagrams.

### `document.safe_summary.render`

- **display_name**: 渲染安全摘要
- **category / group / action**: report_data / document / safe_summary_render
- **capability_actions**: `document.safe_summary.render`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Render a safe summary of scanned document.
- **boundary**: Do not include raw sensitive config.

### `report.artifact.save`

- **display_name**: 保存报告制品
- **category / group / action**: report_data / report / artifact_save
- **capability_actions**: `report.artifact.save`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Save a report as artifact. Use after render.
- **boundary**: Do not include raw sensitive config as final output.

### `report.markdown.render`

- **display_name**: 渲染 Markdown 报告
- **category / group / action**: report_data / report / markdown_render
- **capability_actions**: `report.create_and_save`, `report.markdown.render`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Render a structured markdown report.
- **boundary**: Do not include raw sensitive config as final output.

### `text.classify`

- **display_name**: 文本分类
- **category / group / action**: report_data / text / classify
- **capability_actions**: `text.classify`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Classify text into categories.
- **boundary**: Use only for safe, well-known categories.

### `text.diff`

- **display_name**: 文本差异
- **category / group / action**: report_data / text / diff
- **capability_actions**: `data.text.process`, `text.diff`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Compute diff between two texts.
- **boundary**: Do not execute embedded code.

### `text.keywords.extract`

- **display_name**: 提取关键词
- **category / group / action**: report_data / text / keywords_extract
- **capability_actions**: `data.text.process`, `text.keywords.extract`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Extract key terms and identifiers.
- **boundary**: Do not return secrets.

### `text.redact`

- **display_name**: 文本脱敏
- **category / group / action**: report_data / text / redact
- **capability_actions**: `data.text.process`, `text.redact`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Redact sensitive data from text.
- **boundary**: Use before persisting to memory or artifact.

### 5.7. Runtime 运行审计 (`runtime`)

**Description**: 运行状态、session、run、review 和审计信息。

**Typical use**: 运行健康 / 诊断、session / run / review 审计。

**Not for**: 不读取 trace 全量；不跨 workspace 泄露；review.update 不修改原产物。

**Groups**: `archive, health, retention, review, run, session`

**Canonical tools**: 16

### `review.item.list`

- **display_name**: 列出评审项
- **category / group / action**: runtime / review / item_list
- **capability_actions**: `review.item.list`, `runtime.review.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List review items needing human attention.
- **boundary**: Do not modify artifacts.

### `review.item.update`

- **display_name**: 更新评审项
- **category / group / action**: runtime / review / item_update
- **capability_actions**: `review.item.update`, `runtime.review.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Update a review item status.
- **boundary**: Do not modify the original artifact body.

### `run.list`

- **display_name**: 列出运行
- **category / group / action**: runtime / run / list
- **capability_actions**: `run.list`, `runtime.audit.inspect`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List recent agent runs with status and intent.
- **boundary**: Do not return full trace bodies.

### `run.summary.get`

- **display_name**: 运行摘要
- **category / group / action**: runtime / run / summary_get
- **capability_actions**: `run.summary.get`, `runtime.audit.inspect`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get detailed summary of a specific run.
- **boundary**: Do not return full trace bodies.

### `runtime.archive.preview`

- **display_name**: 归档预览
- **category / group / action**: runtime / archive / preview
- **capability_actions**: `runtime.archive.preview`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Preview data affected by archive operation.
- **boundary**: Do not execute archive without explicit approval.

### `runtime.diagnostics`

- **display_name**: 运行诊断
- **category / group / action**: runtime / health / diagnostics
- **capability_actions**: `host.environment.inspect`, `runtime.audit.inspect`, `runtime.diagnostics`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run full diagnostic on agent runtime.
- **boundary**: Do not include sensitive trace payloads.

### `runtime.health`

- **display_name**: 运行健康检查
- **category / group / action**: runtime / health / health
- **capability_actions**: `host.environment.inspect`, `runtime.audit.inspect`, `runtime.health`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Check runtime health — LLM connectivity, tool registry, modules. Use before heavy operations.
- **boundary**: Do not include sensitive trace payloads.

### `runtime.retention.preview`

- **display_name**: 保留预览
- **category / group / action**: runtime / retention / preview
- **capability_actions**: `runtime.retention.preview`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Preview retention policy effects.
- **boundary**: Do not execute retention without explicit approval.

### `runtime.selfcheck`

- **display_name**: 运行时自检
- **category / group / action**: runtime / health / selfcheck
- **capability_actions**: `runtime.audit.inspect`, `runtime.selfcheck`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Run a self-check on all core subsystems.
- **boundary**: Do not include sensitive trace payloads.

### `session.checkpoint`

- **display_name**: 会话检查点
- **category / group / action**: runtime / session / checkpoint
- **capability_actions**: `runtime.session.manage`, `session.checkpoint`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Create session checkpoint for rewind.
- **boundary**: Do not include secrets.

### `session.export`

- **display_name**: 导出会话
- **category / group / action**: runtime / session / export
- **capability_actions**: `runtime.audit.inspect`, `runtime.session.manage`, `session.export`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Export session to JSON/Markdown.
- **boundary**: Do not include secrets in exported artifacts.

### `session.list`

- **display_name**: 列出会话
- **category / group / action**: runtime / session / list
- **capability_actions**: `runtime.audit.inspect`, `session.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List active sessions with metadata.
- **boundary**: Do not include sensitive trace payloads.

### `session.rewind`

- **display_name**: 会话回滚
- **category / group / action**: runtime / session / rewind
- **capability_actions**: `runtime.session.manage`, `session.rewind`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Rewind session to checkpoint (destructive).
- **boundary**: Do not include secrets in rewind steps.

### `session.snapshot.create`

- **display_name**: 创建会话快照
- **category / group / action**: runtime / session / snapshot_create
- **capability_actions**: `runtime.session.manage`, `session.snapshot.create`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Create session snapshot for audit.
- **boundary**: Do not include secrets in snapshots.

### `session.snapshot.list`

- **display_name**: 列出快照
- **category / group / action**: runtime / session / snapshot_list
- **capability_actions**: `runtime.audit.inspect`, `runtime.session.manage`, `session.snapshot.list`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List session snapshots.
- **boundary**: Do not return sensitive payloads.

### `session.summary.get`

- **display_name**: 会话摘要
- **category / group / action**: runtime / session / summary_get
- **capability_actions**: `runtime.audit.inspect`, `session.summary.get`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get session summary.
- **boundary**: Do not include sensitive trace payloads.

### 5.8. Web 外部资料 (`web`)

**Description**: 公开 Web、官方文档、新闻、天气和网页摘要。

**Typical use**: 公开 Web 搜索、厂商官方文档、新闻、天气查询。

**Not for**: 不抓私网 / 本地 / 登录墙 URL；weather 仅在明确天气需求时使用。

**Groups**: `docs, news, page, search, weather`

**Canonical tools**: 8

### `web.docs.official_search`

- **display_name**: 官方文档检索
- **category / group / action**: web / docs / official_search
- **capability_actions**: `web.docs.official_search`, `web.official_docs.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search official vendor documentation and technical references.
- **boundary**: Do not query private documentation portals.

### `web.news.search`

- **display_name**: 公开新闻搜索
- **category / group / action**: web / news / search
- **capability_actions**: `web.news.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search news sources for recent articles on a topic.
- **boundary**: Do not query private / local / login-walled URLs.

### `web.page.extract_links`

- **display_name**: 提取网页链接
- **category / group / action**: web / page / extract_links
- **capability_actions**: `web.official_docs.search`, `web.page.extract_links`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Extract all links from a web page. Use before web.page.summarize to find specific URLs.
- **boundary**: Do not query private / local / login-walled URLs.

### `web.page.save_artifact`

- **display_name**: 保存网页到制品
- **category / group / action**: web / page / save_artifact
- **capability_actions**: `web.page.save_artifact`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Save a web page as a workspace artifact.
- **boundary**: Do not save authenticated pages.

### `web.page.summarize`

- **display_name**: 网页摘要
- **category / group / action**: web / page / summarize
- **capability_actions**: `web.official_docs.search`, `web.page.summarize`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Fetch and summarize a public web page by URL. Use when user provides a URL to analyze.
- **boundary**: Do not query private / local / login-walled URLs.

### `web.search`

- **display_name**: 公开 Web 搜索
- **category / group / action**: web / search / search
- **capability_actions**: `web.official_docs.search`, `web.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search the public web for current facts, news, vendor docs, or information not in workspace. Falls back to web.docs.official_search.
- **boundary**: Do not query private / local / login-walled URLs.

### `web.weather.current`

- **display_name**: 当前天气
- **category / group / action**: web / weather / current
- **capability_actions**: `web.weather.current`, `web.weather.read`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get current weather conditions for a location.
- **boundary**: Use only when an explicit weather question is asked.

### `web.weather.forecast`

- **display_name**: 天气预报
- **category / group / action**: web / weather / forecast
- **capability_actions**: `web.weather.forecast`, `web.weather.read`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get weather forecast for a location.
- **boundary**: Use only when an explicit weather question is asked.

### 5.9. Workspace 工作区 (`workspace`)

**Description**: 工作区文件、Artifact 制品和 workspace 元数据。

**Typical use**: 工作区文件列表 / 读取 / 编辑、artifact 元数据、安全摘要读写。

**Not for**: 不跨 workspace；不绕过 artifact 安全策略；不访问绝对路径。

**Groups**: `artifact, document, file, metadata`

**Canonical tools**: 23

### `file.get`

- **display_name**: 读取FileStore文件
- **category / group / action**: workspace / file / get
- **capability_actions**: `file.get`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read text content of a FileStore-managed file by file_id.
- **boundary**: Not for binary files.

### `file.import_workspace_path`

- **display_name**: 导入文件到FileStore
- **category / group / action**: workspace / file / import
- **capability_actions**: `file.import_workspace_path`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Import a workspace-relative file into FileStore.
- **boundary**: Path must be in allowed current directories.

### `file.preview`

- **display_name**: 预览FileStore文件
- **category / group / action**: workspace / file / preview
- **capability_actions**: `file.preview`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Preview metadata and first lines of a FileStore file.
- **boundary**: Not for reading full binary content.

### `file.references`

- **display_name**: 查询文件引用
- **category / group / action**: workspace / file / references
- **capability_actions**: `file.references`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Query cross-references for a FileStore file.
- **boundary**: 

### `file.write_agent_output`

- **display_name**: 写入Agent输出
- **category / group / action**: workspace / file / write
- **capability_actions**: `file.write_agent_output`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Write content through FileStore and return file_id.
- **boundary**: Not for arbitrary paths.

### `workspace.artifact.delete_soft`

- **display_name**: 软删除制品
- **category / group / action**: workspace / artifact / delete_soft
- **capability_actions**: `workspace.artifact.delete_soft`, `workspace.artifact.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Soft-delete an artifact. Requires approval.
- **boundary**: Do not perform hard deletion.

### `workspace.artifact.diff`

- **display_name**: 制品差异
- **category / group / action**: workspace / artifact / diff
- **capability_actions**: `workspace.artifact.diff`, `workspace.artifact.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Diff two artifacts or files.
- **boundary**: Do not use for non-artifact files.

### `workspace.artifact.export`

- **display_name**: 导出制品
- **category / group / action**: workspace / artifact / export
- **capability_actions**: `workspace.artifact.export`, `workspace.artifact.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Export an artifact to external format.
- **boundary**: Do not export outside the workspace.

### `workspace.artifact.list`

- **display_name**: 列出制品
- **category / group / action**: workspace / artifact / list
- **capability_actions**: `workspace.artifact.list`, `workspace.artifact.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List workspace artifacts.
- **boundary**: Do not return artifact bodies; use workspace.artifact.read.

### `workspace.artifact.read`

- **display_name**: 读取制品
- **category / group / action**: workspace / artifact / read
- **capability_actions**: `workspace.artifact.manage`, `workspace.artifact.read`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read an artifact's content.
- **boundary**: Do not use to bypass artifact safety policy.

### `workspace.artifact.save`

- **display_name**: 保存制品
- **category / group / action**: workspace / artifact / save
- **capability_actions**: `report.create_and_save`, `workspace.artifact.manage`, `workspace.artifact.save`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Save content as a new artifact.
- **boundary**: Do not save secrets; route through review when claiming deployable.

### `workspace.artifact.search`

- **display_name**: 搜索制品
- **category / group / action**: workspace / artifact / search
- **capability_actions**: `workspace.artifact.manage`, `workspace.artifact.search`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Search artifacts by title or type.
- **boundary**: Do not return artifact bodies.

### `workspace.artifact.tag`

- **display_name**: 制品标签
- **category / group / action**: workspace / artifact / tag
- **capability_actions**: `workspace.artifact.manage`, `workspace.artifact.tag`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Tag an artifact.
- **boundary**: Do not modify artifact body content.

### `workspace.document.pdf.extract_text`

- **display_name**: 提取 PDF 文本
- **category / group / action**: workspace / document / pdf_extract_text
- **capability_actions**: `workspace.document.pdf.extract_text`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Extract text from a PDF.
- **boundary**: Do not use for non-PDF files.

### `workspace.file.edit`

- **display_name**: 编辑工作区文件
- **category / group / action**: workspace / file / edit
- **capability_actions**: `workspace.file.edit`, `workspace.file.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Edit a file with string replacement. Requires approval.
- **boundary**: Do not use for absolute paths outside the workspace.

### `workspace.file.exists`

- **display_name**: 检查工作区文件是否存在
- **category / group / action**: workspace / file / exists
- **capability_actions**: `workspace.file.exists`, `workspace.file.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Check if a file exists.
- **boundary**: Do not use outside the current workspace.

### `workspace.file.list`

- **display_name**: 列出工作区文件
- **category / group / action**: workspace / file / list
- **capability_actions**: `workspace.file.list`, `workspace.file.manage`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: List workspace files with names and sizes.
- **boundary**: Do not cross workspaces or list absolute paths.

### `workspace.file.patch`

- **display_name**: 工作区文件补丁
- **category / group / action**: workspace / file / patch
- **capability_actions**: `workspace.file.manage`, `workspace.file.patch`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Apply a diff/patch to a file. Requires approval.
- **boundary**: Do not use for absolute paths outside the workspace.

### `workspace.file.preview`

- **display_name**: 工作区文本预览
- **category / group / action**: workspace / file / preview
- **capability_actions**: `workspace.file.manage`, `workspace.file.preview`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Preview first lines of a file.
- **boundary**: Do not read full large files; use workspace.file.read.

### `workspace.file.read`

- **display_name**: 读取工作区文件
- **category / group / action**: workspace / file / read
- **capability_actions**: `config.analysis`, `config.translation`, `pcap.analysis`, `workspace.file.manage`, `workspace.file.read`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read a workspace file. MUST be called first before config.analysis.run — read the config content, then pass it to analysis tools. Use for: uploaded configs, logs, reports, any text file in workspace.
- **boundary**: Do not use for artifacts, knowledge base, or arbitrary absolute paths.

### `workspace.file.read_image`

- **display_name**: 读取图片信息
- **category / group / action**: workspace / file / read_image
- **capability_actions**: `workspace.file.read_image`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Read image file metadata — dimensions, format, size. Does NOT OCR. Ask user to describe content.
- **boundary**: Do not use for text/code files. Not for OCR.

### `workspace.file.write_artifact`

- **display_name**: 写入制品文件
- **category / group / action**: workspace / file / write_artifact
- **capability_actions**: `workspace.file.manage`, `workspace.file.write_artifact`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Write content and register as artifact.
- **boundary**: Do not write to arbitrary paths.

### `workspace.metadata.get`

- **display_name**: 读取工作区元数据
- **category / group / action**: workspace / metadata / get
- **capability_actions**: `workspace.metadata.get`
- **governance_status**: `active`
- **planner_visible**: true
- **risk_level**: low
- **requires_approval**: false
- **usage**: Get workspace metadata and stats.
- **boundary**: Do not return secrets.


## 6. Governance Summary

active=104 disabled=0 internal=0 forbidden=0

## 7. Disabled / Internal / Forbidden

| canonical_tool_id | governance_status | reason |
|---|---|---|

## 8. Planner Visible Tools

- `agent.result.get`
- `agent.role.list`
- `agent.spawn`
- `agent.team.run`
- `config.analysis.run`
- `data.csv.summarize`
- `data.json.validate`
- `data.table.extract`
- `data.table.render`
- `data.yaml.validate`
- `diagram.mermaid.render`
- `document.safe_summary.render`
- `file.get`
- `file.import_workspace_path`
- `file.preview`
- `file.references`
- `file.write_agent_output`
- `host.command.slash_run`
- `host.powershell.exec`
- `host.python.exec`
- `host.shell.exec`
- `knowledge.chunk.list`
- `knowledge.chunk.read`
- `knowledge.chunk.summary`
- `knowledge.import.artifact`
- `knowledge.import.document`
- `knowledge.import.file`
- `knowledge.not_found.explain`
- `knowledge.parent.read`
- `knowledge.search`
- `knowledge.source.delete`
- `knowledge.source.disable`
- `knowledge.source.get`
- `knowledge.source.list`
- `knowledge.source.read`
- `knowledge.source.reindex`
- `knowledge.source.reindex_all`
- `memory.confirm`
- `memory.create`
- `memory.delete_soft`
- `memory.list`
- `memory.profile.get`
- `memory.profile.set`
- `memory.search`
- `memory.update`
- `pcap.analysis.run`
- `report.artifact.save`
- `report.markdown.render`
- `review.item.list`
- `review.item.update`
- `run.list`
- `run.summary.get`
- `runtime.archive.preview`
- `runtime.diagnostics`
- `runtime.health`
- `runtime.retention.preview`
- `runtime.selfcheck`
- `session.checkpoint`
- `session.export`
- `session.list`
- `session.rewind`
- `session.snapshot.create`
- `session.snapshot.list`
- `session.summary.get`
- `skill.create`
- `skill.get`
- `skill.install`
- `skill.list`
- `skill.load`
- `skill.search`
- `skill.unload`
- `slash.command.list`
- `slash.command.run`
- `text.classify`
- `text.diff`
- `text.keywords.extract`
- `text.redact`
- `tool.catalog.search`
- `web.docs.official_search`
- `web.news.search`
- `web.page.extract_links`
- `web.page.save_artifact`
- `web.page.summarize`
- `web.search`
- `web.weather.current`
- `web.weather.forecast`
- `workspace.artifact.delete_soft`
- `workspace.artifact.diff`
- `workspace.artifact.export`
- `workspace.artifact.list`
- `workspace.artifact.read`
- `workspace.artifact.save`
- `workspace.artifact.search`
- `workspace.artifact.tag`
- `workspace.document.pdf.extract_text`
- `workspace.file.edit`
- `workspace.file.exists`
- `workspace.file.list`
- `workspace.file.patch`
- `workspace.file.preview`
- `workspace.file.read`
- `workspace.file.read_image`
- `workspace.file.write_artifact`
- `workspace.metadata.get`

## 9. Internal Handler Map (Runtime Only)

`handler_id` is internal-only and is NOT part of the public catalog. The dispatch table lives in `tool_runtime/canonical_registry.py` and is not surfaced in this document.

## 10. Boundaries

- canonical_tool_id is the only public tool ID.
- handler_id is internal-only.
- capability_action is a planner verb, never a tool ID.
- governance_status values are active / disabled / internal / forbidden only.
- The public surface has no transition / retirement fields.
