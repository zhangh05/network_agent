# Network Agent

面向网络运维的 AI Agent 操作台。支持 PCAP 分析、配置翻译、拓扑构建、CMDB、SSH/Telnet 远程执行、知识库检索、浏览器自动化等多维能力。

## 快速开始

```bash
# 安装依赖并启动
bash start.sh

# 访问
# Frontend: http://localhost:5173
# Backend:  http://localhost:8010

# 停止
bash stop.sh
```

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12+, Flask |
| 前端 | React 18, TypeScript, Vite |
| 状态管理 | Zustand |
| 虚拟列表 | react-virtuoso |
| LLM | MiniMax M3 (245K 上下文) |
| 实时通信 | WebSocket (流式) + HTTP (回退) |
| 终端仿真 | xterm.js |
| 存储 | JSONL (append + tombstone), JSON |
| 检索 | BM25 + CJK bigram/trigram |

## 核心能力

- **PCAP 分析**：TCP 流重建、协议检测、异常分析
- **配置翻译**：多厂商网络配置互译 (Cisco/Huawei/Juniper/Arista)
- **拓扑构建**：自动发现 + LLM 推断网络拓扑
- **CMDB**：资产管理与查询
- **远程执行**：SSH/Telnet 远程设备命令执行
- **Python 沙箱**：安全执行 Python 脚本分析数据
- **知识库**：Markdown 文档索引与检索
- **浏览器**：基于 Playwright 的浏览器自动化
- **Git/代码**：代码库搜索与分析

## 项目结构

```
network_agent/
├── agent/              # Agent 引擎：runtime, capabilities, skills, tools
├── backend/            # Flask API 服务 (main.py 唯一入口)
│   ├── api/            # REST 路由
│   └── ws/             # WebSocket 处理
├── frontend/           # React/TS 前端
├── tool_runtime/       # 73 工具规范注册表 + 执行沙箱
├── jobs/               # Job 状态机、lifecycle、worker
├── workspace/          # Session / Run 存储与生命周期
├── context/            # 上下文构建与注入
├── storage/            # FileStore 抽象层
├── artifacts/          # Artifact 管理与持久化
├── observability/      # Trace / EventStore
├── modules/            # 业务模块 (config_translation, topology, ...)
├── skills/             # Skill 实现 (SA 层)
├── prompts/            # LLM Prompt 模板
├── harness/            # pytest 测试
└── docs/               # 文档
```

## 架构原则

- **Backend 为 API 契约唯一来源**：前端类型从后端 API 响应派生
- **workspace_id 为全局标识符**：贯穿 session/artifact/pcap/job/run/memory 所有子系统
- **无默认回退**：非法或空 workspace_id 返回 400
- **数据状态即真相**：单源渲染，流式数据通过 Zustand → Virtuoso 单路径输出
- **级联清理**：删除资源时同步清理关联数据
