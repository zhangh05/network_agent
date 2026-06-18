# 网工智枢 (Network Agent)

网络工程智能助手 — Flask + React/TypeScript + LLM Agent 平台。

## 快速开始

```bash
# 后端
pip install -r requirements.txt
python -m backend.main --port 8010

# 前端
cd frontend && npm install && npm run dev
```

访问 http://localhost:5173

## 架构概览

```
用户 → React 前端 (5173) → Flask API (8010) → RuntimeLoop → LLM (MiniMax M3)
                                                    ↓
                                              ContextStore ← UnifiedRetriever (BM25)
                                              (items.jsonl)   ↑
                                                    ↓         |
                                              104 个工具 → 工具执行 → 结果返回
```

### 统一上下文架构 (v3.1.0)

所有可检索数据存储在单一文件 `workspaces/{ws}/context/items.jsonl`：

| item_type | 说明 | 数量 |
|-----------|------|------|
| `knowledge_chunk` | 知识库文档片段 | ~200 |
| `knowledge_source` | 知识库来源 | ~10 |
| `memory_hit` | Agent 记忆 | ~20 |
| `profile` | 用户画像 | 1 |

**统一检索**：`UnifiedRetriever` 提供单一 BM25 引擎，支持 CJK n-gram、scope boost、Jaccard 去重。

### 工具系统

104 个注册工具，按 15 个分类：

| 分类 | 数量 | 示例 |
|------|------|------|
| web | 8 | web.search, web.page.summarize |
| knowledge | 16 | knowledge.search, knowledge.import.file |
| network | 8 | network.config.parse, network.pcap.parse |
| memory | 8 | memory.create, memory.search |
| workspace | 18 | workspace.file.read, workspace.artifact.save |
| host | 4 | host.shell.exec, host.python.exec |
| agent | 4 | agent.spawn, agent.team.run |
| 其他 | 38 | data.*, text.*, session.*, skill.* 等 |

每个场景保证 15+ 可见工具（含基线工具集），意图专属工具在基线之上叠加。

### 安全层

- 全链路注入扫描（knowledge/memory/tool_result）
- action_class 5 级分级（read/write/mutate/execute/external）
- argument_source 追踪（user/rag/memory/unknown）
- 高危工具审批门控
- schema 驱动的敏感字段过滤（白名单，非黑名单）

### 自动上下文压缩

三级压缩防止上下文溢出：

1. **RAG 压缩**：类型限额 + 语义去重 + 字符预算
2. **Auto-compact**：85% 阈值触发，4 层逐级压缩
3. **会话压缩**：旧对话摘要化，保留最近 3 轮

## 目录结构

```
agent/                 Agent 核心引擎（runtime, llm, modules, tools）
backend/               Flask HTTP/WS 后端
frontend/              React/TS 前端
context/               统一上下文系统（ContextStore, UnifiedRetriever, schema_registry）
memory/                记忆系统（委托到 ContextStore）
tool_runtime/          工具运行时（104 个工具注册、分类、权限）
modules/               领域模块（配置翻译、巡检、拓扑）
prompts/               Prompt 模板系统
config/                LLM 配置
workspaces/            工作区运行时数据
```

## 技术栈

- **后端**: Python 3.13, Flask
- **前端**: React 18, TypeScript, Vite, Zustand
- **LLM**: MiniMax M3 (245K context window)
- **检索**: BM25 + CJK bigram/trigram
- **存储**: JSONL（追加写入 + 墓碑删除 + compact GC）
- **通信**: WebSocket (流式) + HTTP (fallback)

## 测试

```bash
python3 -m pytest harness -q
cd frontend && npm run typecheck
```

## 文档

- [DESIGN.md](DESIGN.md) — 架构设计
- [AGENTS.md](AGENTS.md) — Agent 系统
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构详解
- [docs/API.md](docs/API.md) — API 参考
- [docs/CAPABILITIES_AND_TOOLS.md](docs/CAPABILITIES_AND_TOOLS.md) — 工具目录
- [docs/FRONTEND.md](docs/FRONTEND.md) — 前端架构
- [docs/RUNTIME.md](docs/RUNTIME.md) — 运行时系统
