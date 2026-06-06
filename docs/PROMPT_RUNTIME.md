# Prompt Runtime

## Main Chain

```
safe_generate → get_prompt_by_task → render_prompt → check_prompt_input
    → check_prompt_text → provider → check_prompt_output → deterministic_fallback
```

## Prompt Registry

- Default registry file: `prompts/registry.yaml`
- Currently registered: **7 prompts**
- Templates directory: `prompts/templates/*.md`

## Registered Prompts

| Prompt ID | Template | Purpose |
|-----------|----------|---------|
| `response.compose.v1` | `response_compose.md` | Main agent response composition |
| `context.qa.v1` | `context_qa.md` | Answer questions from safe context |
| `manual_review.explain.v1` | `manual_review_explain.md` | Explain manual review items |
| `result.summarize.v1` | `result_summarize.md` | Summarize run results |
| `job_failure.explain.v1` | `job_failure_explain.md` | Explain job failures |
| `report.summary.v1` | `report_summary.md` | Summarize reports |
| `artifact_summary.explain.v1` | `artifact_summary_explain.md` | Explain artifact contents |

## Provider Flow

1. `get_prompt_by_task(task)` → select prompt by task context
2. `render_prompt(prompt, context)` → fill template with safe context variables
3. `RenderedPrompt` → enters provider as `messages` with `rendered.text` in `user` content
4. `check_prompt_text(rendered.text)` → policy check on rendered text

## Guardrails

### check_prompt_text Failure

**BLOCKS provider execution.** No pass-through if text contains:
- Full device configs
- Secret/keys/passwords
- Deployable configuration
- Injection patterns

### check_prompt_output Failure

**Discards provider output entirely.** Falls through to deterministic fallback.

## Fallback Path

Old `agent.llm.tasks.prompts` path is **NOT** the default. It is only used as fallback when:
- Prompt registry is missing or unreadable
- Requested prompt ID is not in registry

## Prompt Policy

| Rule | Description |
|------|-------------|
| No full config | Content must be summarized, not raw |
| No secret | Keys, passwords, tokens stripped |
| No deployable code | Output configs blocked |
| No "可直接下发" | Cannot claim direct deployability |
| No fake refs | All artifact/run/job refs must be real |
| No hide manual_review | Must surface review items |
| Injection detection | SQL/script/command injection patterns blocked |

## Composer Task Selection

`_select_prompt_task()` routes to:

| Context | Prompt Task |
|---------|-------------|
| User question about context | `context_qa` |
| Job failure description | `job_failure` |
| Review explanation request | `manual_review` |
| Report summary request | `report` |
| Artifact explanation request | `artifact` |
| Run result summary | `result_summarize` |
| Default / general response | `response_compose` |
