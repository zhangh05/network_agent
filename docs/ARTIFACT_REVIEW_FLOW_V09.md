# Artifact Consumption & Review Flow v0.9

> 后端能力搭建完成；本轮不做前端 API 对齐。
> 配套：[README.md](../README.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CAPABILITY_MANIFEST_V08.md](CAPABILITY_MANIFEST_V08.md) · [CAPABILITY_LAYER_V071.md](CAPABILITY_LAYER_V071.md) · [RELEASE_HISTORY.md](RELEASE_HISTORY.md)

## 1. 目标

把后端能力链搭完整：
- **artifact** capability：让 LLM 能浏览 / 读取 / diff / 导出已有 artifact
- **review** capability：让用户能逐条复核 manual_review_items 并打 status + user_note

为后续前端重设计提供**稳定后端能力**；本轮不开放任何真实设备能力，不改 v0.7.1 业务输出合同。

## 2. 新增 Capabilities (v0.9)

| capability_id | status | module | skills | visible tools |
|---|---|---|---|---|
| `artifact` | **enabled (NEW v0.9)** | `artifact` | `artifact_management` | `artifact.list`, `artifact.read`, `artifact.diff`, `artifact.export` |
| `review`   | **enabled (NEW v0.9)** | `review`   | `review_flow`       | `review.list_items`, `review.update_item` |

| capability_id | status |
|---|---|
| `config_translation` | enabled (existing) |
| `knowledge` | enabled (existing) |
| `topology` | **planned (unchanged)** |
| `inspection` | **planned (unchanged)** |
| `cmdb` | **planned (unchanged)** |

## 3. artifact Capability

### 3.1 `artifact.list`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`（必填）, `session_id`（可选）, `artifact_type`（可选）, `limit`（可选） |
| 输出 | `artifacts: list`，每条 `artifact_id` / `title` / `artifact_type` / `created_at` / `metadata` |
| 约束 | **不返回本地文件路径**；sanitized records |
| 失败 | `ok=false, errors=["missing_workspace_id"]` |

### 3.2 `artifact.read`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`（必填）, `artifact_id`（必填）, `allow_sensitive`（默认 False） |
| 输出 | `content` + `metadata` + `authoritative=false` + `deployable_config=false` |
| 失败 | `ok=false, errors=["artifact_not_found"]` / `["sensitivity_denied"]` |
| 不变量 | `translated_config` artifact 必须可读；`authoritative=false / deployable_config=false` 保留 |

### 3.3 `artifact.diff`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`, `left_artifact_id`, `right_artifact_id`, `max_lines`（默认 200） |
| 输出 | unified text diff（`fromfile/left`, `tofile/right`, n=2） |
| 失败 | `ok=false, errors=["artifact_not_found"]` 任一缺失时 |
| 不变量 | workspace owner 可读 sensitive artifacts（同 workspace） |

### 3.4 `artifact.export`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`, `artifact_id`, `format`（`txt` 或 `md`） |
| 输出 | `rendered` 文本 + `deployable_config=false` 标记 |
| 失败 | `ok=false, errors=["unsupported_format"]` / `["artifact_read_failed"]` |
| 不变量 | 纯本地文本渲染；**不发到真实设备**；**不生成 deployable_config** |
| md 格式 | 含 metadata header（artifact_id / type / sensitivity / authoritative / deployable_config） |

## 4. review Capability

### 4.1 `review.list_items`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`, `artifact_id` |
| 输出 | `items: list`，每条含 `item_id` / `severity` / `category` / `line_no` / `source_text` / `translated_text` / `reason` / `recommendation` / `status`（pending/accepted/ignored/modified）/ `user_note` / `updated_at` |
| 失败 | `ok=false, errors=["artifact_not_found"]` |
| 不变量 | item 来源 = `artifact.metadata.manual_review_items` ∪ sidecar；初态 `status="pending", user_note=""` |

### 4.2 `review.update_item`

| 字段 | 说明 |
|---|---|
| 输入 | `workspace_id`, `artifact_id`, `item_id`, `status`（pending/accepted/ignored/modified）, `user_note`（可选） |
| 输出 | 更新后的 `{status, user_note, updated_at}`；metadata 含 `original_artifact_modified=False, deployable_config_produced=False` |
| 失败 | `ok=false, errors=["invalid_status"]` / `["item_not_found"]` / `["artifact_not_found"]` / `["missing_inputs"]` |
| 不变量 | **不修改 translated_config 原文**；**不生成 deployable_config**；状态写入**sidecar JSON** `{ws_root}/{ws_id}/reviews/{art_id}.json` |

### 4.3 Review item status

| status | 含义 | LLM 行为建议 |
|---|---|---|
| `pending` | 待人工复核（初态） | 必须 surface 给用户 |
| `accepted` | 人工接受 | 可继续用 translated_config 作为参考 |
| `ignored` | 人工忽略 | 不影响后续步骤 |
| `modified` | 人工已修改建议 | **注意**：仅 sidecar 记录；translated_config 原文未变 |

## 5. 不变量

| 强制 | 说明 |
|---|---|
| **artifact 不下发** | `artifact.export` 是本地文本渲染；**不**调任何 device call |
| **artifact 不生产 deployable_config** | 4 个 tool 全部 `produces_deployable_config=False`；`authoritative=False` 强制 |
| **review 不改原文** | 状态 / user_note 写 sidecar JSON；原始 artifact 一字不动 |
| **review 不生产 deployable_config** | 2 个 tool 全部 `produces_deployable_config=False` |
| **不接真实设备** | 2 个 capability 的 `real_device_access=False` |
| **不开 SSH/Telnet/SNMP/nmap** | 0 启用；ToolRuntime 拦截表未触碰 |
| **config.push 永久禁止** | 0 触碰 |
| **planned 永不暴露** | topology / inspection / cmdb 仍是 `callable_by_llm=False`；`visible_tool_ids()` fail-closed |
| **v0.7.1 capability tests 零回归** | 41/41 passed |

## 6. Tool Count 变化

| 维度 | v0.8.2 | v0.9 |
|---|---|---|
| Capability 层 enabled tool 数 | 2 + 0 + 0 = 2 | 2 + 4 + 2 = **8** |
| 实际 catalog 总数 | 57 | **62**（+5） |
| 差异原因 | — | v0.9 计划新增 6 个 tool_id（4 artifact + 2 review），但 `artifact.list` 已存在于 ToolRuntime catalog，被 `register_capability_tools` 去重，所以净增 5 个：57 + 5 = 62 |

**说明**：spec 预期 57 → 63（+6），实际 57 → 62（+5），因为 v0.8 baseline 的 ToolRuntime catalog 已经含 `artifact.list` 这一项。该 tool 的 capability 层 v0.8.2 还没有，但 catalog 已有。v0.9 让 capability 层显式声明 4 个 artifact tool，但其中 1 个被去重。

## 7. CapabilityRegistry 变化

| 维度 | v0.8.2 | v0.9 |
|---|---|---|
| `list_all()` | 5 个 | **7 个**（+artifact, +review） |
| `list_enabled()` | 2 个 | **4 个**（+artifact, +review） |
| `list_planned()` | 3 个 | **3 个**（不变） |
| `visible_tool_ids()` | 2 个 | **8 个**（+6） |

## 8. 模块接入现状

| Module | service 函数 | `to_module_result` | `ToolResult.from_module_result` |
|---|---|---|---|
| `config_translation` | `translate_config()` | ✓ | ✓ |
| `knowledge` | `query_knowledge()` | ✓ | ✓ |
| **`artifact`** (NEW v0.9) | `list_artifacts_for_session` / `read_artifact` / `diff_artifacts` / `export_artifact` | ✓ | ✓ |
| **`review`** (NEW v0.9) | `list_review_items` / `update_review_item` | ✓ | ✓ |
| `topology` (planned) | — | — | — |
| `inspection` (planned) | — | — | — |
| `cmdb` (planned) | — | — | — |

## 9. v0.7.1 测试零回归证据

```
v0.7/v0.7.1 capability tests:  41 passed, 0 failed
  test_capability_config_translation_v07.py
  test_capability_knowledge_v07.py
  test_capability_artifacts_v071.py
  test_capability_knowledge_sources_v071.py
```

`config_translation.service.translate_config` / `knowledge.service.query_knowledge` 的 dict 业务输出合同**一字不动**；v0.9 的 review sidecar 只读 `metadata.manual_review_items`，不修改翻译输出。

## 10. 后续 (v0.9.x / v0.10)

| 版本 | 主题 |
|---|---|
| v0.9.x | 前端 API 对齐（FastAPI 路由 / SSE 推送 review 状态变更） |
| v0.9.x | LLM-based SkillSelector（用模型替代 rule-based） |
| v0.10 | topology capability 启用（从 planned → enabled） |
