# Network Agent Architecture

## Concept Taxonomy

### Module（模块）
固定产品功能模块。有 UI、API、后端服务、状态和测试。用户可在页面中点击进入。

| 模块 | 状态 | 说明 |
|------|------|------|
| config_translation | enabled | 网络配置跨厂商翻译 |
| topology | planned | 网络拓扑提取与绘图 |
| inspection | planned | 配置巡检与合规分析 |
| knowledge_base | planned | 网络知识库与经验积累 |

### Skill（技能）
Agent 可加载的能力包。描述 Agent 如何使用模块或工具，包含 SKILL.md 操作手册、skill.yaml 元数据、adapter.py 适配代码。Skill 不一定有 UI。

| Skill | 状态 | 关联模块 |
|------|------|----------|
| config_translation | enabled | config_translation |
| topology_draw | planned | topology |
| inspection_analyze | planned | inspection |
| knowledge_search | planned | knowledge_base |

### Memory（记忆）
Agent 原生记忆系统，SQLite/JSONL backend。不使用外部 Obsidian 作为核心。
记忆分为：short_term / project / long_term / decision / user_preference / device_profile / run_summary / knowledge_note。

### Workspace（工作区）
项目文件和运行状态的存放区。不等于 Memory。输入/输出/报告/会话状态都在 workspaces/ 下。

## 启动方式

```bash
python backend/main.py
# or
python -m backend.main --port 8010
```

正式服务监听 `127.0.0.1:8010`。8020 不是正式入口。

## API

| 端点 | 说明 |
|------|------|
| /api/health | 健康检查 (api_mode=unified) |
| /api/version | 版本信息 + embedded 状态 |
| /api/modules | 模块注册表 |
| /api/modules/{name}/status | 模块状态 |
| /api/modules/config-translation/translate | 配置翻译（模块 API） |
| /api/translate | 配置翻译（兼容 API） |
| /api/agent/run | Agent 执行 |
| /api/skills | 技能注册表 |
| /api/memory/status | 记忆系统状态 |
| /api/memory/write | 写入记忆 |
| /api/memory/search | 搜索记忆 |
| /api/workspace/status | 工作区状态 |

## Module Placement

config_translation 模块完整位于 `modules/config_translation/`：

```
modules/config_translation/
├── backend/         # service/schemas/client — canonical implementation
├── core/            # translate_bundle 确定性翻译管线
├── MODULE.md
└── module.yaml
```

- UI 由 network_agent 统一前端 `frontend/index.html` 提供
- LLM belongs to Network Agent orchestrator layer; module does NOT call LLM
- backend/services/config_translation/ is a compatibility shim only
- 旧 network-translator LLM / GraphAgent 翻译路径未迁入

## LLM 预留

- `backend/agent/` — 未来统一 Agent LLM 层预留
- `agent/` — 同上
- config_translation 模块不私接 LLM
- LLM must not modify deployable_config
