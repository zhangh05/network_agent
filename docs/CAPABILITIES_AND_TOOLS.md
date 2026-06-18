# 工具与能力

## 工具分类 (104 个)

### web (8 个) — 外部网络访问
| tool_id | 说明 |
|---------|------|
| `web.search` | DuckDuckGo 网页搜索 |
| `web.page.summarize` | 网页正文提取 |
| `web.page.extract_links` | 网页链接提取 |
| `web.page.save_artifact` | 网页保存为制品 |
| `web.docs.official_search` | 厂商官方文档搜索 (Cisco/Huawei/H3C/...) |
| `web.news.search` | 新闻搜索 |
| `web.weather.current` | 实时天气 (Open-Meteo) |
| `web.weather.forecast` | 天气预报 |

### knowledge (16 个) — 知识库
| tool_id | 说明 |
|---------|------|
| `knowledge.search` | BM25 全文搜索 |
| `knowledge.import.file` | 文件导入 |
| `knowledge.import.document` | 文本导入 |
| `knowledge.source.list/get/read/delete/disable/reindex` | 来源管理 |
| `knowledge.chunk.list/read/summary` | chunk 操作 |

### network (8 个) — 网络配置
| tool_id | 说明 |
|---------|------|
| `network.config.parse` | 配置文件解析 |
| `network.config.translate` | 配置翻译 (H3C↔Cisco) |
| `network.interface.extract` | 接口信息提取 |
| `network.route.extract` | 路由表提取 |
| `network.pcap.parse/session/filter/align` | 抓包分析 |

### memory (8 个) — 记忆系统
| tool_id | 说明 |
|---------|------|
| `memory.search/list/create/update/confirm/delete_soft` | CRUD |
| `memory.profile.get/set` | 用户画像 |

### host (4 个) — 系统命令
| tool_id | 说明 | 审批 |
|---------|------|------|
| `host.shell.exec` | Shell 命令 | 需审批 |
| `host.python.exec` | Python 脚本 | 需审批 |
| `host.powershell.exec` | PowerShell | 需审批 |
| `host.command.slash_run` | 斜杠命令 | 需审批 |

### workspace (18 个) — 文件与制品
文件读写、制品管理、PDF 提取等。

### 其他
- `agent.*` (4) — 结果获取、角色、子代理
- `session.*` (7) — 会话管理
- `skill.*` (7) — 技能管理
- `data.*` (5) — CSV/JSON/YAML/表格
- `text.*` (4) — 分类/对比/关键词/脱敏
- `report.*` (2) — 报告生成
- `review.*` (2) — 审阅
- `runtime.*` (5) — 运行时诊断
- `run.*` (2) — 运行记录
- `slash.*` (2) — 斜杠命令
- `diagram.*` (1) — Mermaid 图表
- `document.*` (1) — 文档摘要

## 能力声明

每个领域模块声明 `CapabilityManifest`，包含 operations、tools、safety rules。

通过 `/api/capabilities` 查看所有已注册能力。
