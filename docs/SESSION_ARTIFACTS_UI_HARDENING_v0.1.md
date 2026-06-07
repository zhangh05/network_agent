# Session & Artifacts UI Consistency Hardening

**Date:** 2026-06-07
**Commits:** a869430 (base) → hardening v0.1 → stabilization v0.2

## Summary

收口现有 Session、Artifacts、LLM 设置、前后端 UI 一致性。拆出 backend/main.py 路由文件。

## Changes — v0.2 (stabilization)

### 1. Chat 安全摘要标签

- **Frontend:** 历史消息气泡新增 `🔒 安全摘要` 徽章，hover 显示 tooltip 说明
  - "恢复的是安全摘要，非完整原始内容。完整配置/敏感信息不在聊天历史中保存。"
- CSS: `.summary-badge` 样式，user/ai 气泡分别配色

### 2. Backend 路由拆分

| 之前 | 之后 | 变化 |
|------|------|------|
| `main.py` 898 行, 87 route | 244 行, 34 route | **-73%** |
| 全在 `create_app()` | 拆为 5 个 `register_*_routes(app)` | 模块化 |

新文件:
- `backend/api/artifact_routes.py` (174 行) — /api/workspaces/<ws>/artifacts/*
- `backend/api/job_routes.py` (172 行) — /api/jobs/*
- `backend/api/runtime_routes.py` (129 行) — /api/runtime/*, selfcheck, retention, archive
- `backend/api/context_routes.py` (102 行) — /api/context/*, /api/prompts/*, /api/harness/*
- `backend/api/workspace_routes.py` (198 行) — /api/workspaces, /api/runs/*, trace, reports

**API 路径不变，零行为变更。**

### 3. 测试更新

- `test_frontend_backend_alignment.py`: 路由检查改为搜索所有 route 文件
- `test_session_artifact_ui_hardening.py`: 新增 `TestBackendRouteIntegrity` class (2 tests)
  - `test_no_retired_routes`: 确认无 /api/translate, GraphAgent, network-translator, :8020
  - `test_all_required_routes_exist`: 确认所有 38 个必需路由仍在

## Changes — v0.1 (initial hardening)

### LLM max_tokens 前后端统一为 4096

- **Frontend:** HTML input value/placeholder、save 回退值、loadSettings 默认值、后端加载回退值全部改为 4096
- **Backend:** 已是 4096
- **Test:** harness/test_llm_settings_runtime_wiring.py 从 1200 → 4096

### Session ID 安全校验

- `workspace/ids.py` — `validate_session_id()` / `is_valid_session_id()`
- `backend/api/session_routes.py` — 所有 handler 添加校验
- `backend/api/agent.py` — agent run 添加可选校验

### Artifacts 类型统计对齐

- 统计卡片 `config` → `input_config || output_config`
- 筛选下拉增加 `input_config/output_config/temp/quarantine`
- Type badges 完整映射

### Artifact 删除语义

- confirm 文案 "此操作不可撤销" → "删除后文件标记为已删除，可联系管理员恢复"

### Artifact 表格新增 sensitivity / lifecycle 列

- "状态"列：活跃/已归档/已删除/已提升/已隔离（颜色编码）
- "敏感度"列：公开/内部/敏感/机密（颜色编码）

### 翻译页面刷新恢复安全摘要

- 从最近 translate_config run 恢复 quality_summary, manual_review_count, deployable_lines
- 不恢复完整配置内容
- 显示"安全摘要恢复"提示

## Test Results (current)

| Command | Result |
|---------|--------|
| `git diff --check` | ✅ clean |
| `pytest harness -q` | ✅ 1148 passed, 7 skipped |
| `pytest harness -q -rs` | ✅ 7 skipped (LLM live API) |
| `pytest harness -q -k "session or artifact or frontend_backend or ui or llm_settings or design_purity or config_translation or retired"` | ✅ 395 passed |

## Files Changed (cumulative)

```
M  backend/api/agent.py
M  backend/api/session_routes.py
M  frontend/index.html
M  harness/test_frontend_backend_alignment.py
M  harness/test_llm_settings_runtime_wiring.py
M  workspace/ids.py
A  backend/api/artifact_routes.py
A  backend/api/job_routes.py
A  backend/api/runtime_routes.py
A  backend/api/context_routes.py
A  backend/api/workspace_routes.py
A  harness/test_session_artifact_ui_hardening.py
A  docs/SESSION_ARTIFACTS_UI_HARDENING_v0.1.md
```

## Prohibited Items — All Respected

| 禁止项 | 状态 |
|--------|------|
| 不改 translate_bundle | ✅ |
| LLM 不参与 deployable_config | ✅ |
| 不新增 Tool invoke API/UI | ✅ |
| 不接真实设备执行 | ✅ |
| 不接 SSH/Telnet/SNMP/nmap/ping sweep | ✅ |
| 不做配置下发 | ✅ |
| 不恢复 retired surfaces | ✅ |
| 不进入 Knowledge/Topology/Inspection/CMDB | ✅ |
| 不放宽 gate | ✅ |
| 不扩大 skipped | ✅ (仍是 7 skipped) |
| 不把完整聊天/配置/prompt/secret 存 localStorage | ✅ |
| 不把完整 source_config/deployable_config 塞进 LLM | ✅ |

## Open Items

1. Session 跨浏览器恢复依赖 localStorage — 换浏览器后需重新选择 session（正确设计）
2. `backend/main.py` 剩余 34 route 大多是 session/llm/modules/memory 的 thin wrapper，后续可继续提取
3. `test_frontend_backend_alignment.py` 中的 route 检查机制可进一步优化为自动扫描
