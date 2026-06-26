# Network Agent Tool Catalog (v3.9)

> Source of truth: `tool_runtime/tool_namespace_data.py` + `tool_runtime/tool_governance.py` + `tool_runtime/canonical_registry.py`.
> Machine-readable mirror: `reports/tool_catalog.json`.

## 1. Overview

| Metric | Value |
|--------|-------|
| canonical tools | 73 |
| categories | 13 |
| governance status | all active |
| capability domains | 13 |

### Categories

| Category | Count | Tools |
|----------|-------|-------|
| agent | 5 | agent.result.get, agent.role.list, agent.spawn, agent.team.run, tool.catalog.search |
| browser | 4 | browser.click, browser.extract, browser.navigate, browser.screenshot |
| code | 1 | code.search |
| config | 2 | config.analysis.run, pcap.analysis.run |
| data | 9 | data.csv.summarize, data.table.*, data.validate, diagram.mermaid.render, document.safe_summary.render, report.*, text.analyze |
| device | 4 | device.add, device.delete, device.get, device.list |
| exec | 3 | exec.python, exec.run, exec.slash |
| git | 5 | git.commit, git.diff, git.log, git.push, git.status |
| knowledge | 8 | knowledge.chunk.list, knowledge.import, knowledge.* |
| memory | 3 | memory.manage, memory.profile, memory.search |
| system | 9 | system.diagnostics, system.review.*, system.run.get, system.session.* |
| web | 3 | web.page.process, web.search, web.weather |
| workspace | 17 | file.*, workspace.artifact.*, workspace.file.*, workspace.metadata.get |

## 2. Full Tool List

### agent (5)
| ID | Label | Description |
|----|-------|-------------|
| agent.result.get | 读取 Agent 结果 | Read the current agent run result |
| agent.role.list | 列出 Agent 角色 | List available agent roles |
| agent.spawn | 创建子 Agent | Spawn a sub-agent for delegation |
| agent.team.run | 运行 Agent 团队 | Run a multi-agent team |
| tool.catalog.search | 搜索工具目录 | Search the tool catalog |

### browser (4)
| ID | Label | Description |
|----|-------|-------------|
| browser.click | 网页点击 | Click an element on a web page |
| browser.extract | 浏览器内容提取 | Extract content from web pages |
| browser.navigate | 浏览器导航 | Navigate to a URL |
| browser.screenshot | 网页截图 | Take a screenshot of a page |

### code (1)
| ID | Label | Description |
|----|-------|-------------|
| code.search | 代码搜索 | Search code in the workspace |

### config (2)
| ID | Label | Description |
|----|-------|-------------|
| config.analysis.run | 配置分析 | Analyze network configs |
| pcap.analysis.run | PCAP 分析 | Analyze packet captures |

### data (9)
| ID | Label | Description |
|----|-------|-------------|
| data.csv.summarize | 汇总 CSV | Summarize CSV data |
| data.table.extract | 提取表格 | Extract tables from documents |
| data.table.render | 渲染表格 | Render a data table |
| data.validate | 数据校验 | Validate data against schema |
| diagram.mermaid.render | 渲染 Mermaid 图 | Render Mermaid diagrams |
| document.safe_summary.render | 渲染安全摘要 | Render sanitized summaries |
| report.artifact.save | 保存报告制品 | Save a report artifact |
| report.markdown.render | 渲染 Markdown 报告 | Render markdown reports |
| text.analyze | 文本分析 | Analyze text content |

### device (4)
| ID | Label | Description |
|----|-------|-------------|
| device.add | 添加设备 | Add a network device to CMDB |
| device.delete | 删除设备 | Delete a device from CMDB |
| device.get | 获取设备详情 | Get device details by ID |
| device.list | 列出设备资产 | List all registered devices |

### exec (3)
| ID | Label | Description |
|----|-------|-------------|
| exec.python | Python 执行 | Run Python code (sandboxed) |
| exec.run | 命令执行 | Execute commands (target=local/ssh/telnet) |
| exec.slash | Slash 命令 | Run registered slash commands |

### git (5)
| ID | Label | Description |
|----|-------|-------------|
| git.commit | Git 提交 | Commit changes |
| git.diff | Git 差异 | Show working tree diff |
| git.log | Git 提交历史 | Show commit history |
| git.push | Git 推送 | Push commits to remote |
| git.status | Git 状态检查 | Show working tree status |

### knowledge (8)
| ID | Label | Description |
|----|-------|-------------|
| knowledge.chunk.list | 列出知识块 | List knowledge chunks |
| knowledge.import | 导入知识 | Import documents into knowledge base |
| knowledge.not_found.explain | 解释未命中 | Explain why nothing was found |
| knowledge.read | 读取知识内容 | Read a knowledge entry |
| knowledge.search | 知识库检索 | Search the knowledge base |
| knowledge.source.list | 列出知识源 | List knowledge sources |
| knowledge.source.manage | 管理知识源 | Manage knowledge source settings |
| knowledge.source.reindex | 重建索引 | Rebuild knowledge indexes |

### memory (3)
| ID | Label | Description |
|----|-------|-------------|
| memory.manage | 管理记忆 | List/create/delete memory entries |
| memory.profile | Profile 管理 | Get/set memory profiles |
| memory.search | 搜索记忆 | Search memory with BM25 |

### system (9)
| ID | Label | Description |
|----|-------|-------------|
| system.diagnostics | 运行诊断 | Runtime health diagnostics |
| system.review.item.list | 列出评审项 | List review items |
| system.review.item.update | 更新评审项 | Update review item status |
| system.run.get | 运行记录 | Get a run record by ID |
| system.session.checkpoint | 会话检查点 | Create/view session checkpoints |
| system.session.export | 导出会话 | Export session data |
| system.session.get | 会话管理 | Get session metadata |
| system.session.rewind | 会话回滚 | Rewind session to checkpoint |
| system.session.snapshot | 会话快照 | Take a session snapshot |

### web (3)
| ID | Label | Description |
|----|-------|-------------|
| web.page.process | 网页操作 | Fetch/summarize/save web pages |
| web.search | 公开 Web 搜索 | Search the public web |
| web.weather | 天气查询 | Get weather for a location |

### workspace (17)
| ID | Label | Description |
|----|-------|-------------|
| file.import_workspace_path | 导入文件 | Import a file into the workspace |
| file.references | 查询文件引用 | Look up file references |
| workspace.artifact.delete_soft | 软删除制品 | Soft-delete an artifact |
| workspace.artifact.diff | 制品差异 | Diff artifacts |
| workspace.artifact.export | 导出制品 | Export artifact to file |
| workspace.artifact.list | 列出制品 | List workspace artifacts |
| workspace.artifact.read | 读取制品 | Read artifact content |
| workspace.artifact.save | 保存制品 | Save a new artifact |
| workspace.artifact.tag | 制品标签 | Tag an artifact |
| workspace.document.pdf.extract_text | 提取 PDF 文本 | Extract text from PDFs |
| workspace.file.edit | 编辑工作区文件 | Edit a file in the workspace |
| workspace.file.list | 列出工作区文件 | List workspace files |
| workspace.file.patch | 工作区文件补丁 | Apply a patch to a file |
| workspace.file.read | 读取工作区文件 | Read a workspace file |
| workspace.file.read_image | 读取图片信息 | Read image metadata |
| workspace.file.write_artifact | 写入制品文件 | Write artifact to file |
| workspace.metadata.get | 读取工作区元数据 | Get workspace metadata |

## 3. Governance

All 73 tools are `active` with `planner_visible=True`. No tools are in `disabled` or `internal` status. The ability-based routing system determines which tools are visible per turn based on the user's intent and the active capability packages.

## 4. Capability Routing

The system uses a 12-domain capability framework. Each capability domain maps to a set of tools. The router selects capability domains based on the user's request, then builds the visible tool set from the matching domains plus 16 core tools that are always available.

Core tools: `exec.run, exec.python, exec.slash, workspace.file.list, workspace.file.read, workspace.artifact.list, workspace.artifact.read, web.search, web.weather, git.status, git.log, git.diff, code.search, system.diagnostics, tool.catalog.search, device.list`
