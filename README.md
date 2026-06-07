# Network Agent

Network Agent 是一个网络工程本地 Agent 平台，面向网络工程师提供配置翻译、拓扑发现、巡检分析、知识管理等 AI 驱动的网络运维能力。平台基于 LangGraph 运行时调度，以 Module / Skill / Memory 三层架构组织，统一入口端口 8010。

## Platform Runtime Closure — Current Baseline

Current commit: `2002069`

Current test baseline: `pytest harness -q = 945 passed, 7 skipped, 0 failed`.

Network Agent is a new local network-engineering Agent platform, not a legacy framework migration. The current runtime chain is:

```
router → context → planner → executor → verifier → composer → memory
```

Current enabled business module: **config_translation** only. `assistant_chat` is an Agent base capability, not a business module. Topology, Inspection, CMDB, and Knowledge remain planned/coming_soon and must not fabricate runtime data.

Run history is backend/workspace-backed. Browser `localStorage` is for UI preferences only, not run history, configs, prompts, keys, jobs, reports, or artifacts.

LLM settings saved from the frontend are persisted by the backend through `POST /api/agent/llm/config` into gitignored `config/LLM_setting.json`; later Agent runs resolve that file before env/file fallback. The browser does not persist the API key.

Tool Runtime has Foundation + Client + Integration contracts and writes safe ToolResult metadata into observability traces when invoked with trace context. It still does **not** support SSH/Telnet/SNMP/nmap/ping sweep/arbitrary shell/config push or real device execution.

`quality_summary` is part of the platform summary chain for config translation. If `source_residue_count > 0` or `silent_drop_count > 0`, the result requires warnings/manual review and must not be described as ready for device execution.

## Foundation Baseline (historical)

| # | 组件 | 状态 |
|---|------|------|
| 1 | LangGraph Runtime (7 trace nodes) | completed |
| 2 | Registry / Capability / Skill / Module Contract | completed |
| 3 | LLM Settings (MiniMax-M3 default) | completed |
| 4 | Workspace Runtime | completed |
| 5 | Memory Runtime | completed |
| 6 | Run History | completed |
| 7 | Observability / Trace / Timeline | completed |
| 8 | Artifact / File Pipeline | completed |
| 9 | Report / Export Pipeline | completed |
| 10 | Job / Task Runtime | completed |
| 11 | Context Runtime | completed |
| 12 | Prompt Runtime | completed |
| 13 | Harness Runtime | completed |

## Business Module

当前仅启用一个业务模块：**config_translation**，核心管线为 `translate_bundle`。

| Module | Status | Entry API |
|--------|--------|-----------|
| config_translation | enabled | `POST /api/modules/config-translation/translate` |

## 快速启动

```bash
cd network_agent
pip install -r requirements.txt
python backend/main.py --port 8010
# 本机访问 http://127.0.0.1:8010
# 局域网访问 http://<这台机器的网口IP>:8010
```

## 入口 API

| 端点 | 说明 |
|------|------|
| `POST /api/agent/run` | Agent 执行入口 |
| `POST /api/modules/config-translation/translate` | 配置翻译 |
| `POST /api/jobs` | 任务提交 |
| `GET /api/runs/recent` | 后端工作区运行历史摘要 |
| `GET /api/runs/{run_id}` | 默认/指定工作区运行详情 |
| `GET /api/workspaces/{id}/history` | 指定工作区运行历史 |
| `GET /api/agent/status` | Agent 状态 |
| `GET /api/agent/llm/config` | LLM 配置（不返回完整 key） |
| `GET /api/workspaces/{id}/state` | 工作区状态 |
| `GET /api/memory/list` | 记忆列表 |

## 测试

```bash
pytest harness -q
# 945 passed, 7 skipped, 0 failed
```

## 目录结构

```
network_agent/
├── agent/                    # Agent 主框架 (LangGraph + LLM)
│   ├── nodes/                # 7 节点: router, context, planner, executor, verifier, composer, memory
│   └── llm/                  # safe_generate, provider, policy, context_builder
├── modules/                  # 业务模块
│   └── config_translation/   # translate_bundle 管线
├── skills/                   # Agent 技能包 (adapter → module)
├── memory/                   # JSONL 记忆系统 (redaction + policy)
├── workspace/                # 工作区运行时 (state, runs, artifacts)
├── harness/                  # pytest 测试
├── frontend/                 # 统一前端
├── config/                   # LLM 配置 (LLM_setting.json gitignored)
├── scripts/                  # 审计/清理工具
└── reports/                  # 审计报告
```

## 下一步

1. Tool / Command Runtime
2. Knowledge / Index Runtime
3. Platform Hardening
4. Business Modules: topology, inspection, knowledge, CMDB

## 安全基线

- LLM 不改 deployable_config，不产生可直接部署的输出
- 不宣称"可直接部署"，不以 AI 能力绕过人工复核
- API key 仅本地存储，API 返回 `key_preview` 不返回完整 key
- 所有 Memory/Workspace/Run/Trace 写入走 redaction + policy 门控
- `config/LLM_setting.json` 权限 600，不进 Git
- Module / Skill 不得私接 LLM
- 跨工作区访问默认拒绝
