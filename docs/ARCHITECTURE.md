# Network Agent Architecture

## 总体架构

```
Frontend → API (8010) → Agent (LangGraph)
                           ├── Context (loader, resolver, builder)
                           ├── Registry / Capability / Skill / Module
                           ├── Verifier
                           ├── Composer (LLM)
                           └── Memory (writer, redaction, policy)

Horizontal base:
Workspace / Memory / Artifact / Report / Job / Trace /
LLM Settings / Prompt / Harness
```

## Agent 调用链

```
POST /api/agent/run → graph
  → context_loader   (上下文加载、压缩、构建 ContextBundle)
  → planner          (任务分解、Skill 选取)
  → executor         (调用 Skill adapter → Module service)
  → verifier         (结果校验)
  → composer         (LLM 响应合成)
  → memory_writer    (记忆写入、Workspace 更新、Run 落盘)
```

## config_translation 调用链

```
Agent → capability: config.translate
      → skill: config_translation (adapter)
      → module: config_translation (service)
      → translate_bundle (核心管线)
```

## Job 调用链

```
POST /api/jobs → JobManager → Worker → JobRunner
  → run_agent() → Agent Runtime (同上 Agent 调用链)
Job 状态机: queued → running → succeeded / failed / cancelled
Job 默认归属当前 workspace。
```

## LLM / Prompt 链

```
Composer → safe_generate
  → prompts.loader (registry.yaml 加载模板)
  → renderer       (Jinja2 渲染)
  → policy input   (安全策略门控)
  → provider       (MiniMax / OpenAI Compatible / Ollama / Mock)
  → policy output  (安全策略门控)
```

## Context 链

```
context_ref → resolver → loader → selector
  → compressor → builder
  → ContextBundle { execution_context, safe_llm_context }
```

ContextBundle 的 `safe_llm_context` 经过脱敏和截断后方可进入 LLM prompt。

## Artifact 统一文件基座

所有文件 I/O 通过 `ArtifactStore`：
- artifact_scopes: `workspace`, `run`, `shared`, `temp`
- artifact_types: `input`, `output`, `report`, `intermediate`
- sensitive artifacts 标记并限制访问
- 产物引用在 Memory / Run / Trace 中仅存 `artifact_id` + `summary`

## Report / Export 管线

```
ReportComposer → render (Jinja2) → export (HTML/Markdown/JSON)
  → ArtifactStore (report artifact)
  → Memory (report summary + artifact_ref)
```

## 安全边界

- **LLM 红线**: 不生成 deployable_config，不声称可直接部署，不隐藏 manual_review 标记
- **Key 保护**: API key 仅本地存储，API 返回 key_preview，不进 log/trace/memory/state
- **Redaction 层**: Memory 写入、Trace 写入、State 写入、Run 写入均经 redaction
- **Artifact 隔离**: sensitive artifact 标记，跨 workspace 访问默认拒绝
- **Module 隔离**: Module / Skill 不得私接 LLM
