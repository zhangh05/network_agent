# LLM Settings Redesign — 2026-06-11

## Goal

让 `/settings` 页面变成 internal dev 真能用的 LLM 控制台，**不**是空 form。

## Layout (User-approved: B)

```
┌─────────────────────────────────────────────────────────────┐
│ HealthBar  (顶部, 全宽) — 来自 /api/agent/llm/status        │
│ 🟢 已连接 · MiniMax-M3 · 0 错误 · key 加载自 env           │
├──────────────┬──────────────────────────────────────────────┤
│ PROVIDER     │ Form (右侧)                                   │
│ ┌──────────┐ │ ┌────────────────────────────────────────┐   │
│ │ MiniMax ●│ │ │ BASE_URL: [____________________]      │   │
│ │ OpenAI   │ │ │ MODEL:    [____________________]      │   │
│ │ DeepSeek │ │ │ API_KEY:  [eyJ0****8a3f  ✓] [显示]  │   │
│ │ Ollama   │ │ │ ENABLED  ●—○   SAFE_MODE ●—○          │   │
│ │ Custom   │ │ │ TEMP: [0.2]  MAX_TOKENS: [1200]       │   │
│ └──────────┘ │ ├────────────────────────────────────────┤   │
│              │ │ [🧪 测试]  [保存]    [重置为默认]      │   │
│              │ │ updated_at: 2026-06-11 · source: ui    │   │
│              │ └────────────────────────────────────────┘   │
└──────────────┴──────────────────────────────────────────────┘
```

## Features (User-approved, 6 of 6)

1. **api_key 输入框** — password 风格, "已配置 / 显示 / 替换" 三态
2. **enabled 开关** — 后端 sanitize 返回的 `enabled`
3. **preset provider 卡片** — MiniMax / OpenAI / DeepSeek / Ollama / Custom, 点一下预填 base_url+model
4. **test 连通性按钮** — POST /api/agent/llm/test (result_summarize), 结果 inline
5. **health 状态条 (顶部)** — GET /api/agent/llm/status, 实时
6. **delete 按钮 (重置为默认)** — DELETE /api/agent/llm/config + confirm

## Architecture

**前端 only** — 后端 0 改动。5 个端点全用 (`GET config` / `POST config` / `DELETE config` / `GET status` / `POST test`)。

## File changes

| 文件 | 改动 |
|---|---|
| `frontend/src/types/index.ts` | + `LlmConfig` / `LlmStatus` / `LlmTestResult` |
| `frontend/src/api/index.ts` | + `settingsApi.llmStatus()` / `deleteLlmConfig()` / `llmTest()` |
| `frontend/src/pages/Settings/Settings.tsx` | 完全重写 (~300 行), 包含 HealthBar / Sidebar / Form 内联组件 |
| `frontend/src/test/settingsLlm.test.tsx` | + 8 case (initial load / preset fill / save / test / delete / health error / api_key 替换 / safe_mode 切换) |
| `e2e/12-llm-settings.spec.ts` | + 1 spec (preset 切换 + 改 enabled + 保存后看到 health 更新) |

## 不变量

- 后端 0 改动
- Tool count 仍 73, planned 仍 0 可见
- `config.push` 永久禁止
- 不接真实设备
