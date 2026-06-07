# LLM Settings

## 配置入口

LLM 配置由 `agent/llm/settings.py` 统一管理。

- **UI 配置文件**: `config/LLM_setting.json` (gitignored, 权限 600, owner-only)
- **配置模板**: `config/LLM_setting.example.json` (tracked, 不含 key)
- **兜底文件**: `config/llm.yaml`

## 配置优先级

1. UI Settings (`config/LLM_setting.json`) — 最高优先级
2. 环境变量 / 桌面文件 — fallback
3. `config/llm.yaml` — 基础兜底
4. default (disabled) — 无配置时默认禁用

## 默认模型

**MiniMax-M3** — 所有默认值、示例、placeholder 统一使用。

## Provider 类型

| provider | 说明 |
|----------|------|
| `disabled` | 禁用 LLM |
| `mock` | 测试用 mock 响应 |
| `minimax` | MiniMax API (默认) |
| `openai_compatible` | OpenAI 兼容接口 |
| `ollama_compatible` | Ollama 本地部署 |

## API

| 端点 | 说明 |
|------|------|
| `GET /api/agent/llm/config` | 读取配置，返回 `key_preview` (如 `sk-t****7890`)，不返回完整 key |
| `POST /api/agent/llm/config` | 保存配置 |
| `DELETE /api/agent/llm/config` | 删除配置 |
| `GET /api/agent/llm/status` | LLM 连接状态 |
| `POST /api/agent/llm/test` | 连通性测试 |

## LLM 红线

LLM 在任何情况下不得执行以下操作：

- 不生成/修改 deployable_config
- 不隐藏 manual_review 标记或声称可直接部署
- 不在输出中声称"可直接部署"
- 不伪造 job 状态、artifact 状态、run 状态
- 不输出 key / token / password / SNMP community 等敏感值
- 安全策略使用否定语境检测 (_is_negation_context)，LLM 表达边界免责声明时不会被误拦截

## Prompt Runtime 集成

LLM 调用通过 `safe_generate()` 统一入口，与 Prompt Runtime 集成：

- 模板定义: `prompts/registry.yaml`
- 渲染引擎: Jinja2 template renderer
- 安全策略: `agent/llm/policy.py` (request + response gate, 含否定语境检测)
  - `prompts/policy.py` (prompt input/output gate, 含 `_is_negation_context()` 否定语境检测)
- 上下文构建: `context/builder.py` → `safe_llm_context`

## Policy 审计历史

| Date | Change |
|------|--------|
| 2026-06-07 | `community\s+\S+` 从 FORBIDDEN_INPUT_PATTERNS 移除（与 `snmp-server\s+community\s+\S+` 冗余，导致 assistant_chat 模板误拦截） |
| 2026-06-07 | 新增 `_is_negation_context()` — 输出策略中检测 CN/EN 否定语境，避免安全免责声明被误拦截 |
| 2026-06-07 | `check_response()` 集成否定语境检测，LLM 表达的 "我不会声称'可直接下发'" 不再被拦截 |

## LLM Runtime Wiring

```
agent/llm/settings.py    → resolve_effective_llm_config()
agent/llm/config.py       → 优先 UI settings, fallback env/file
agent/llm/runtime.py      → safe_generate() 统一入口
agent/llm/provider.py     → 多 provider 适配
agent/llm/context_builder.py → safe_llm_context 构建
agent/llm/policy.py       → 输入/输出安全策略门控
```
