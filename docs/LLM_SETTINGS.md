# LLM Settings

## 配置优先级 (从高到低)

1. **UI Settings** (`config/LLM_setting.json`) — 最高优先级
2. **环境变量/桌面文件** — fallback
3. **`config/llm.yaml`** — 基础配置
4. **默认禁用** — 无配置时

如果 UI Settings 保存了 `enabled: false`，即使环境变量有 key，也不会启用。

## 配置路径

- 主路径: `config/LLM_setting.json` (UI 写入, gitignored)
- 模板: `config/LLM_setting.example.json` (tracked)
- 兜底: `config/llm.yaml` / `config/llm.local.yaml`

## UI Settings 结构

```json
{
  "enabled": true,
  "provider": "minimax",
  "safe_mode": true,
  "base_url": "https://api.minimax.chat/v1",
  "model": "MiniMax-M3",
  "temperature": 0.2,
  "max_tokens": 1200,
  "api_key": "sk-xxxx...xxxx",
  "updated_at": "2026-06-06T09:00:00Z"
}
```

## API

| 端点 | 说明 |
|------|------|
| `GET /api/agent/llm/config` | 读取配置 (不返回完整 key) |
| `POST /api/agent/llm/config` | 保存配置 |
| `DELETE /api/agent/llm/config` | 删除配置 |
| `GET /api/agent/llm/status` | LLM 连接状态 |
| `POST /api/agent/llm/test` | 连通性测试 |

## Security

- API key 仅本地存储
- API 返回 `key_preview` (如 sk-t****7890)，不返回完整 key
- UI 不写入 localStorage/sessionStorage
- UI 不打印完整 key 到 console
- `config/LLM_setting.json` 文件权限 600

## Runtime Wiring

- `agent/llm/settings.py` → 读取 `LLM_setting.json`
- `agent/llm/config.py` → 优先调用 `settings.resolve_effective_llm_config()`
- `agent/llm/runtime.py` → `safe_generate()` 使用统一 effective config
- `agent/llm/provider.py` → `generate()` 使用 UI settings 的 provider/model/base_url/api_key
- `agent/nodes/composer.py` → LLM metadata 包含 `config_source`

## 默认模型

**MiniMax-M3** — 所有默认值、示例、placeholder、文档统一使用 MiniMax-M3。
MiniMax-M1 仅在 migration code 中出现（M1 → M3 自动升级）。
